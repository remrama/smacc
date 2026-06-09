"""Dream-recording window: microphone capture, input level meter, and survey."""

from __future__ import annotations

import webbrowser

import sounddevice as sd
import soundfile as sf
from PyQt6 import QtCore, QtWidgets

from .. import audio
from ..config import SURVEY_OPTIONS
from ..dialogs import ManageSurveysDialog
from ..session import SmaccSession
from ..utils import format_elapsed
from .base import ModalityWindow, describe_target, make_section_title


class RecordingWindow(ModalityWindow):
    """Record a spoken dream report, monitor input level, and open a survey.

    Capture and the level meter both run on sounddevice (PortAudio), so the
    microphone is identified the same way everywhere — one device string, no
    Qt-name-to-PortAudio matching. A report is written straight to a WAV in the
    run folder as it records.
    """

    TITLE = "Dream recording"

    def __init__(self, session: SmaccSession, parent: QtWidgets.QWidget | None = None):
        super().__init__(session, parent)
        self.n_report_counter = 0  # cumulative counter for determining filenames
        self.init_recorder()
        self.init_level_meter()
        self.setCentralWidget(self._build())

    def _build(self) -> QtWidgets.QWidget:
        # Microphone is chosen in the Devices window; show where it resolves to.
        self.deviceLabel = QtWidgets.QLabel(self)
        self.deviceLabel.setStatusTip("Set in the Devices window (Dream-report mic).")
        self.refresh_device_indicator()

        micrecordButton = QtWidgets.QPushButton("Record dream report", self)
        micrecordButton.setStatusTip("Ask for a dream report and start recording.")
        micrecordButton.setCheckable(True)
        micrecordButton.clicked.connect(self.start_or_stop_recording)
        self.micrecordButton = micrecordButton
        if not self.session.can_record:
            # The study designer has no run folder to record into; configuring the
            # device and surveys still works, so only the recording itself is off.
            micrecordButton.setEnabled(False)
            micrecordButton.setToolTip(
                "Recording is available when running a session, not in the designer."
            )

        # Recording indicator (replaces the old log-viewer red border).
        self.recordingIndicatorLabel = QtWidgets.QLabel("■ idle", self)
        self.recordingIndicatorLabel.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

        # Live input level meter (#25): monitor microphone/room level in dBFS.
        monitorCheckBox = QtWidgets.QCheckBox(self)
        monitorCheckBox.setStatusTip(
            "Show the live input level from the selected microphone, in dBFS."
        )
        monitorCheckBox.toggled.connect(self.toggle_level_monitor)
        self.monitorCheckBox = monitorCheckBox

        levelMeterBar = QtWidgets.QProgressBar(self)
        levelMeterBar.setRange(0, 100)
        levelMeterBar.setValue(0)
        levelMeterBar.setTextVisible(True)
        levelMeterBar.setFormat("")
        self.levelMeterBar = levelMeterBar

        levelLayout = QtWidgets.QHBoxLayout()
        levelLayout.addWidget(monitorCheckBox)
        levelLayout.addWidget(levelMeterBar)

        # Survey selector: editable dropdown of named presets (or a typed-in URL).
        surveyComboBox = QtWidgets.QComboBox(self)
        surveyComboBox.setEditable(True)
        surveyComboBox.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        surveyComboBox.setStatusTip(
            "Survey opened in the browser when a dream report starts. "
            "Pick a preset or type a URL (leave blank for none)."
        )
        surveyComboBox.addItem("", "")  # Blank default == no survey.
        for label, url in SURVEY_OPTIONS.items():
            surveyComboBox.addItem(label, url)
        self.surveyComboBox = surveyComboBox

        # "Manage…" opens the add/edit/remove dialog; saved surveys persist in YAML.
        manageSurveysButton = QtWidgets.QPushButton("Manage…", self)
        manageSurveysButton.setStatusTip("Add, edit, or remove saved survey URLs.")
        manageSurveysButton.clicked.connect(self.manage_surveys)
        surveyRow = QtWidgets.QHBoxLayout()
        surveyRow.addWidget(surveyComboBox, 1)
        surveyRow.addWidget(manageSurveysButton)

        layout = QtWidgets.QFormLayout()
        layout.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        layout.addRow(make_section_title("Dream recording"))
        layout.addRow("Device:", self.deviceLabel)
        layout.addRow("Survey:", surveyRow)
        layout.addRow(micrecordButton)
        layout.addRow(self.recordingIndicatorLabel)
        layout.addRow("Show input level:", levelLayout)
        central = QtWidgets.QWidget()
        central.setLayout(layout)
        return central

    # ----- microphone / recording -------------------------------------------

    def init_recorder(self) -> None:
        """Initialize the dream-report recorder state (a sounddevice input stream)."""
        self._record_stream: sd.InputStream | None = None
        self._record_file: sf.SoundFile | None = None

    def _selected_input_device(self) -> str | None:
        """The mic device for the dream-report role (None == system default)."""
        return self.session.devices.device_for("report_in") or None

    def refresh_device_indicator(self) -> None:
        """Show where the mic resolves and switch a live meter over to it."""
        self.deviceLabel.setText(describe_target(self.session, "report_in"))
        self._restart_meter_if_monitoring()

    def is_streaming(self) -> bool:
        """True while the level meter is open or a dream report is recording."""
        return self.meter_stream is not None or self._record_stream is not None

    def start_or_stop_recording(self):
        """Start or stop a dream report (the button's checked state is the intent)."""
        if self.micrecordButton.isChecked():
            if not self._start_recording():
                self.micrecordButton.setChecked(False)  # start failed; revert
                return
            if survey_url := self.current_survey_url():
                self.open_survey_url(survey_url, self.surveyComboBox.currentText())
            # Stamp the report with the time since the "Start recording" marker so
            # it can be found in the EEG file later (#60). With no marker yet, still
            # log the report right away, then tell the user it's untimed. When the
            # registry's increment flag is on, each start also advances its code
            # (201, 202, …) automatically, so reports stay individually findable.
            elapsed = self.session.elapsed_since_recording()
            if elapsed is None:
                self.session.emit_event("DreamReportStarted")
                self.session.show_info_popup(
                    "Recording start not marked.",
                    "This dream report was logged, but the “Start recording” "
                    "marker hasn’t been set, so it carries no time-since-recording "
                    "stamp. Press “Start recording” when the EEG recording begins.",
                    parent=self,
                )
            else:
                self.session.emit_event(
                    "DreamReportStarted", detail=f"t+{format_elapsed(elapsed)}"
                )
        else:
            self._stop_recording()
            self.session.emit_event("DreamReportStopped")

    def _start_recording(self) -> bool:
        """Open the mic stream and the report WAV; return True on success.

        Reports live in this run's session folder; the folder already namespaces
        them, so a short report-NN name is enough.
        """
        device = self._selected_input_device()
        self.n_report_counter += 1
        assert self.session.session_dir is not None  # recording is gated on can_record
        export_path = (
            self.session.session_dir / f"report-{self.n_report_counter:02d}.wav"
        )
        try:
            rate = int(sd.query_devices(device, "input")["default_samplerate"])
            self._record_file = sf.SoundFile(
                str(export_path),
                mode="w",
                samplerate=rate,
                channels=1,
                subtype="PCM_16",
            )
            self._record_stream = sd.InputStream(
                device=device,
                channels=1,
                samplerate=rate,
                callback=self._record_callback,
            )
            self._record_stream.start()
        except Exception as exc:  # PortAudio / file-open errors
            self._teardown_recording()
            self.n_report_counter -= 1  # this attempt produced no report
            self.session.show_error_popup(
                "Could not start recording.", str(exc), parent=self
            )
            return False
        self._set_recording_indicator(True)
        return True

    def _stop_recording(self) -> None:
        """Stop the mic stream and finalize the report WAV."""
        self._teardown_recording()
        self._set_recording_indicator(False)

    def _teardown_recording(self) -> None:
        """Close the recording stream and file if open (safe to call repeatedly)."""
        if self._record_stream is not None:
            self._record_stream.abort()
            self._record_stream.close()
            self._record_stream = None
        if self._record_file is not None:
            self._record_file.close()
            self._record_file = None

    def _record_callback(self, indata, frames, time, status) -> None:
        """sounddevice callback (audio thread): append captured frames to the WAV."""
        if self._record_file is not None:
            self._record_file.write(indata.copy())

    def _set_recording_indicator(self, recording: bool) -> None:
        """Reflect the recording state in the on-panel indicator label."""
        if recording:
            self.recordingIndicatorLabel.setText("● recording")
            self.recordingIndicatorLabel.setStyleSheet("color: red; font-weight: bold;")
        else:
            self.recordingIndicatorLabel.setText("■ idle")
            self.recordingIndicatorLabel.setStyleSheet("")

    # ----- input level meter (#25) ------------------------------------------

    def init_level_meter(self) -> None:
        """Set up the input level meter stream and its refresh timer."""
        self.meter_stream: sd.InputStream | None = None
        self._input_level_db = audio.FLOOR_DBFS
        self.meter_timer = QtCore.QTimer(self)
        self.meter_timer.setInterval(50)  # ~20 Hz display refresh
        self.meter_timer.timeout.connect(self.update_level_meter)

    def _restart_meter_if_monitoring(self) -> None:
        """Re-open the level meter on the current device if it's running."""
        if self.meter_stream is not None:
            self.toggle_level_monitor(False)
            self.toggle_level_monitor(True)

    def toggle_level_monitor(self, enabled: bool) -> None:
        """Start/stop monitoring the selected input device's level."""
        self.session.log_interaction(f"Input level meter {'on' if enabled else 'off'}")
        if enabled:
            try:
                self.meter_stream = sd.InputStream(
                    channels=1,
                    device=self._selected_input_device(),
                    callback=self._meter_callback,
                )
                self.meter_stream.start()
            except Exception as exc:  # PortAudio errors, no device, etc.
                self.session.show_error_popup(
                    "Could not open input for monitoring.", str(exc), parent=self
                )
                self.monitorCheckBox.setChecked(False)
                self.meter_stream = None
                return
            self.meter_timer.start()
        else:
            self.meter_timer.stop()
            if self.meter_stream is not None:
                self.meter_stream.abort()
                self.meter_stream.close()
                self.meter_stream = None
            self.levelMeterBar.setValue(0)
            self.levelMeterBar.setFormat("")

    def _meter_callback(self, indata, frames, time, status) -> None:
        """sounddevice callback (audio thread): stash the latest input level."""
        self._input_level_db = audio.rms_dbfs(indata)

    def update_level_meter(self) -> None:
        """GUI-thread timer: render the latest level onto the meter bar."""
        db = self._input_level_db
        self.levelMeterBar.setValue(audio.dbfs_to_meter(db))
        self.levelMeterBar.setFormat(f"{db:.0f} dBFS")

    # ----- survey + settings state ------------------------------------------

    def current_survey_url(self) -> str:
        """Resolve the survey URL from the dropdown (preset data or typed text)."""
        data = self.surveyComboBox.currentData()
        if data:
            return str(data)
        return self.surveyComboBox.currentText().strip()

    def open_survey_url(self, url: str, name: str | None = None) -> None:
        """Open ``url`` in the browser and log a SurveyOpened event marker.

        Shared by the record-start auto-open and the File → Surveys standalone
        open, so every survey launch surfaces a marker (``name`` labels the line).
        """
        webbrowser.open(url, new=1, autoraise=False)
        self.session.emit_event("SurveyOpened", detail=name or url)

    def _current_survey_options(self) -> dict[str, str]:
        """The dropdown's saved presets as a ``{name: url}`` mapping."""
        return {
            self.surveyComboBox.itemText(i): self.surveyComboBox.itemData(i)
            for i in range(self.surveyComboBox.count())
            if self.surveyComboBox.itemData(i)
        }

    def saved_surveys(self) -> dict[str, str]:
        """Public view of the saved survey presets (for the File → Surveys menu)."""
        return self._current_survey_options()

    def manage_surveys(self) -> None:
        """Add/edit/remove saved surveys, then rebuild the dropdown in place."""
        dialog = ManageSurveysDialog(self._current_survey_options(), parent=self)
        if dialog.exec():
            self._apply_survey_state(
                {
                    "survey_options": dialog.get_options(),
                    "survey_url": self.current_survey_url(),
                }
            )

    def _apply_survey_state(self, state: dict) -> None:
        """Rebuild the survey dropdown from saved presets and select the saved URL."""
        options = state.get("survey_options") or {}
        self.surveyComboBox.blockSignals(True)
        self.surveyComboBox.clear()
        self.surveyComboBox.addItem("", "")  # Blank default == no survey.
        for label, url in options.items():
            self.surveyComboBox.addItem(label, url)
        self.surveyComboBox.blockSignals(False)
        survey_url = state.get("survey_url", "")
        for i in range(self.surveyComboBox.count()):
            if self.surveyComboBox.itemData(i) == survey_url:
                self.surveyComboBox.setCurrentIndex(i)
                return
        self.surveyComboBox.setEditText(survey_url)

    def gather_state(self) -> dict:
        return {
            "survey_url": self.current_survey_url(),
            "survey_options": self._current_survey_options(),
        }

    def apply_state(self, state: dict) -> None:
        self._apply_survey_state(state)

    def cleanup(self) -> None:
        self.meter_timer.stop()
        if self.meter_stream is not None:
            self.meter_stream.abort()
            self.meter_stream.close()
            self.meter_stream = None
        self._teardown_recording()
