"""Dream-recording window: microphone capture, input level meter, and survey."""

from __future__ import annotations

import webbrowser
from functools import partial

import sounddevice as sd
import soundfile as sf
from PyQt6 import QtCore, QtWidgets

from .. import surveys
from ..config import SURVEY_OPTIONS
from ..dialogs import ManageSurveysDialog
from ..paths import BUNDLED_SURVEYS_DIR, SURVEYS_DIR
from ..session import SmaccSession
from ..utils import format_elapsed
from .base import ModalityWindow, describe_target, make_section_title
from .meter import InputLevelMeter
from .survey import SurveyWindow


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
        # In-app surveys (#114): built-ins bundled with SMACC plus the user's own,
        # keyed by survey key; refreshed when the Manage dialog changes files.
        self._survey_registry = self._load_survey_registry()
        self._survey_windows: list[SurveyWindow] = []  # keep open windows alive
        self.init_recorder()
        # Built before _build(): refresh_device_indicator() (called inside _build)
        # restarts the meter, so the widget must already exist.
        self.levelMeter = InputLevelMeter(self)
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

        levelLayout = QtWidgets.QHBoxLayout()
        levelLayout.addWidget(monitorCheckBox)
        levelLayout.addWidget(self.levelMeter)

        # Survey selector: editable dropdown of named presets (or a typed-in URL).
        surveyComboBox = QtWidgets.QComboBox(self)
        surveyComboBox.setEditable(True)
        surveyComboBox.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        surveyComboBox.setStatusTip(
            "Survey opened when a dream report starts — built-ins open in a "
            "SMACC window, URLs in the browser (leave blank for none)."
        )
        self.surveyComboBox = surveyComboBox
        self._populate_survey_combo(SURVEY_OPTIONS)

        # "Manage…" handles built-ins (view), custom surveys (build/edit), and
        # web URLs (saved with the study).
        manageSurveysButton = QtWidgets.QPushButton("Manage…", self)
        manageSurveysButton.setStatusTip("View, build, or remove surveys and URLs.")
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
        return self.levelMeter.is_active() or self._record_stream is not None

    def start_or_stop_recording(self):
        """Start or stop a dream report (the button's checked state is the intent)."""
        if self.micrecordButton.isChecked():
            if not self._start_recording():
                self.micrecordButton.setChecked(False)  # start failed; revert
                return
            if survey_url := self.current_survey_url():
                # Attach the survey to this report's number, so its response file
                # is named after (and sorts beside) the report's WAV.
                self.open_survey_url(
                    survey_url,
                    self.surveyComboBox.currentText(),
                    report_number=self.n_report_counter,
                )
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

    # ----- input level meter (#25, shared widget #37) -----------------------

    def _restart_meter_if_monitoring(self) -> None:
        """Re-open the level meter on the current device if it's running."""
        if self.levelMeter.is_active():
            self.toggle_level_monitor(False)
            self.toggle_level_monitor(True)

    def toggle_level_monitor(self, enabled: bool) -> None:
        """Start/stop monitoring the selected input device's level."""
        self.session.log_interaction(f"Input level meter {'on' if enabled else 'off'}")
        if enabled:
            try:
                self.levelMeter.start(self._selected_input_device())
            except Exception as exc:  # PortAudio errors, no device, etc.
                self.session.show_error_popup(
                    "Could not open input for monitoring.", str(exc), parent=self
                )
                self.monitorCheckBox.setChecked(False)
        else:
            self.levelMeter.stop()

    # ----- survey + settings state ------------------------------------------

    def _load_survey_registry(self) -> dict[str, surveys.SurveyDef]:
        """Load the in-app surveys (bundled built-ins + the user's own)."""
        loaded, problems = surveys.all_surveys(BUNDLED_SURVEYS_DIR, SURVEYS_DIR)
        for problem in problems:
            self.session.logger.warning(f"Survey file skipped: {problem}")
        return loaded

    def _populate_survey_combo(self, options: dict[str, str]) -> None:
        """Fill the dropdown: blank, in-app surveys, then web URL presets.

        In-app surveys always show (they come from definition files, not the
        study); only the URL presets in ``options`` travel with the ``.smacc``.
        """
        self.surveyComboBox.addItem("", "")  # Blank default == no survey.
        for survey in self._survey_registry.values():
            self.surveyComboBox.addItem(survey.name, survey.url)
        for label, url in options.items():
            self.surveyComboBox.addItem(label, url)

    def current_survey_url(self) -> str:
        """Resolve the survey URL from the dropdown (preset data or typed text)."""
        data = self.surveyComboBox.currentData()
        if data:
            return str(data)
        return self.surveyComboBox.currentText().strip()

    def open_survey_url(
        self, url: str, name: str | None = None, *, report_number: int | None = None
    ) -> None:
        """Open a survey and log a SurveyOpened event marker.

        A ``smacc://survey/<key>`` URL opens the in-app survey window —
        ``report_number`` links a record-start auto-open to its dream report —
        and anything else opens in the browser. Shared by the record-start
        auto-open and the File → Surveys standalone open, so every survey launch
        surfaces a marker (``name`` labels the line).
        """
        key = surveys.survey_key_from_url(url)
        if key is not None:
            survey = self._survey_registry.get(key)
            if survey is None:
                self.session.show_error_popup(
                    "Survey not found.",
                    f"No survey is registered for {url!r}; its file may have "
                    "been removed. Check Manage… in the Dream-recording panel.",
                    parent=self,
                )
                return
            window = SurveyWindow(survey, self.session, report_number=report_number)
            self._survey_windows.append(window)
            window.finished.connect(partial(self._forget_survey_window, window))
            window.show()
            window.raise_()
            self.session.emit_event("SurveyOpened", detail=name or survey.name)
            return
        webbrowser.open(url, new=1, autoraise=False)
        self.session.emit_event("SurveyOpened", detail=name or url)

    def _forget_survey_window(self, window: SurveyWindow, _result: int = 0) -> None:
        """Drop a closed survey window from the keep-alive list."""
        if window in self._survey_windows:
            self._survey_windows.remove(window)

    def _current_survey_options(self) -> dict[str, str]:
        """The dropdown's saved *web* presets as a ``{name: url}`` mapping.

        In-app (``smacc://``) entries are excluded: they come from survey
        definition files, so persisting them in the study would only go stale.
        """
        return {
            self.surveyComboBox.itemText(i): data
            for i in range(self.surveyComboBox.count())
            if (data := self.surveyComboBox.itemData(i))
            and surveys.survey_key_from_url(data) is None
        }

    def available_surveys(self) -> dict[str, str]:
        """Every offered survey as ``{name: url}`` (for the File → Surveys menu)."""
        out = {s.name: s.url for s in self._survey_registry.values()}
        out.update(self._current_survey_options())
        return out

    def manage_surveys(self) -> None:
        """View/build/remove surveys and URLs, then rebuild the dropdown in place.

        Custom-survey file changes apply even when the dialog is cancelled (the
        files are already written/deleted); the URL mapping applies on accept.
        """
        dialog = ManageSurveysDialog(
            self._current_survey_options(),
            builtin_dir=BUNDLED_SURVEYS_DIR,
            user_dir=SURVEYS_DIR,
            parent=self,
        )
        accepted = dialog.exec()
        if dialog.files_changed:
            self._survey_registry = self._load_survey_registry()
        if accepted or dialog.files_changed:
            self._apply_survey_state(
                {
                    "survey_options": (
                        dialog.get_options()
                        if accepted
                        else self._current_survey_options()
                    ),
                    "survey_url": self.current_survey_url(),
                }
            )

    def _apply_survey_state(self, state: dict) -> None:
        """Rebuild the survey dropdown from saved presets and select the saved URL."""
        options = state.get("survey_options") or {}
        self.surveyComboBox.blockSignals(True)
        self.surveyComboBox.clear()
        self._populate_survey_combo(options)
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
        self.levelMeter.stop()
        self._teardown_recording()
        for window in list(self._survey_windows):
            window.close()
