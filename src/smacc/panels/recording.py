"""Dream-recording window: microphone capture, input level meter, and survey."""

from __future__ import annotations

import webbrowser

import sounddevice as sd
from PyQt5 import QtCore, QtMultimedia, QtWidgets

from .. import audio
from ..config import SURVEY_OPTIONS
from ..dialogs import ManageSurveysDialog
from ..session import SmaccSession
from ..utils import format_elapsed
from .base import ModalityWindow, make_section_title


class RecordingWindow(ModalityWindow):
    """Record a spoken dream report, monitor input level, and open a survey."""

    TITLE = "Dream recording"

    def __init__(self, session: SmaccSession, parent: QtWidgets.QWidget | None = None):
        super().__init__(session, parent)
        self.n_report_counter = 0  # cumulative counter for determining filenames
        self.init_microphone()
        self.init_level_meter()
        self.setCentralWidget(self._build())

    def _build(self) -> QtWidgets.QWidget:
        # Microphone device picker: QComboBox signal --> update device slot
        available_microphones_dropdown = QtWidgets.QComboBox()
        available_microphones_dropdown.setStatusTip("Select microphone")
        available_microphones_dropdown.setPlaceholderText("No microphones were found.")
        available_microphones_dropdown.currentTextChanged.connect(
            self.set_new_microphone
        )
        self.available_microphones_dropdown = available_microphones_dropdown
        self.refresh_available_microphones()

        micrecordButton = QtWidgets.QPushButton("Record dream report", self)
        micrecordButton.setStatusTip("Ask for a dream report and start recording.")
        micrecordButton.setCheckable(True)
        micrecordButton.clicked.connect(self.start_or_stop_recording)
        if not self.session.can_record:
            # The study designer has no run folder to record into; configuring the
            # device and surveys still works, so only the recording itself is off.
            micrecordButton.setEnabled(False)
            micrecordButton.setToolTip(
                "Recording is available when running a session, not in the designer."
            )

        # Recording indicator (replaces the old log-viewer red border).
        self.recordingIndicatorLabel = QtWidgets.QLabel("■ idle", self)
        self.recordingIndicatorLabel.setAlignment(QtCore.Qt.AlignCenter)

        # Live input level meter (#25): monitor microphone/room level in dBFS.
        monitorCheckBox = QtWidgets.QCheckBox(self)
        monitorCheckBox.setStatusTip(
            "Show the live input level from the default microphone, in dBFS."
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
        surveyComboBox.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
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
        layout.setLabelAlignment(QtCore.Qt.AlignRight)
        layout.addRow(make_section_title("Dream recording"))
        layout.addRow("Device:", available_microphones_dropdown)
        layout.addRow("Survey:", surveyRow)
        layout.addRow(micrecordButton)
        layout.addRow(self.recordingIndicatorLabel)
        layout.addRow("Show input level:", levelLayout)
        central = QtWidgets.QWidget()
        central.setLayout(layout)
        return central

    # ----- microphone / recording -------------------------------------------

    def init_microphone(self):
        """Initialize the microphone/recorder used to collect dream reports."""
        settings = QtMultimedia.QAudioEncoderSettings()
        settings.setEncodingMode(QtMultimedia.QMultimedia.ConstantQualityEncoding)
        settings.setQuality(QtMultimedia.QMultimedia.NormalQuality)
        microphone = QtMultimedia.QAudioRecorder()
        microphone.setEncodingSettings(settings)
        microphone.stateChanged.connect(self.update_microphone_status)
        self.microphone = microphone

    def set_new_microphone(self, text: str) -> None:
        """Apply the selected microphone to the recorder and live level meter."""
        name = self.available_microphones_dropdown.currentData()
        if name:
            self.microphone.setAudioInput(name)
        self.session.log_interaction(f"Microphone set to {text}")
        self._restart_meter_if_monitoring()  # switch a live meter over too

    def refresh_available_microphones(self):
        """Populate the microphone dropdown with available audio input devices.

        Items carry the raw input name (the value ``setAudioInput`` expects) as data
        and show a friendlier description as text.
        """
        self.available_microphones_dropdown.clear()
        names = self.microphone.audioInputs()
        for name in names:
            description = self.microphone.audioInputDescription(name) or name
            self.available_microphones_dropdown.addItem(description, name)
        if names:
            self.available_microphones_dropdown.setCurrentIndex(0)
        elif self.session.can_record:
            # In the designer there's no recording, so don't nag about missing mics.
            self.session.show_error_popup("No microphones found.", parent=self)

    def record(self):
        state = self.microphone.state()  # recording / paused / stopped
        if state == QtMultimedia.QMediaRecorder.StoppedState:
            self.n_report_counter += 1
            # Reports live in this run's session folder; the folder already
            # namespaces them, so a short report-NN name is enough.
            basename = f"report-{self.n_report_counter:02d}.wav"
            export_fname = self.session.session_dir / basename
            self.microphone.setOutputLocation(
                QtCore.QUrl.fromLocalFile(str(export_fname))
            )
            self.microphone.record()
        elif state == QtMultimedia.QMediaRecorder.RecordingState:
            self.microphone.stop()

    def update_microphone_status(self, state):
        if state == QtMultimedia.QMediaRecorder.RecordingState:
            self.recordingIndicatorLabel.setText("● recording")
            self.recordingIndicatorLabel.setStyleSheet("color: red; font-weight: bold;")
        else:
            self.recordingIndicatorLabel.setText("■ idle")
            self.recordingIndicatorLabel.setStyleSheet("")

    def start_or_stop_recording(self):
        self.record()  # starts OR stops, whichever isn't currently happening
        if self.sender().isChecked():
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
            self.session.emit_event("DreamReportStopped")

    # ----- input level meter (#25) ------------------------------------------

    def init_level_meter(self) -> None:
        """Set up the input level meter stream and its refresh timer."""
        self.meter_stream: sd.InputStream | None = None
        self._input_level_db = audio.FLOOR_DBFS
        self.meter_timer = QtCore.QTimer(self)
        self.meter_timer.setInterval(50)  # ~20 Hz display refresh
        self.meter_timer.timeout.connect(self.update_level_meter)

    def _meter_device(self) -> int | None:
        """Best-effort PortAudio index for the selected recorder input.

        Qt and PortAudio name devices differently, so match the selected input name
        against PortAudio input devices by substring; return ``None`` (the default
        input) when there's no confident match.
        """
        name = self.available_microphones_dropdown.currentData()
        if not name:
            return None
        try:
            devices = sd.query_devices()
        except Exception:
            return None
        name_low = name.lower()
        for idx, dev in enumerate(devices):
            dev_low = dev["name"].lower()
            if dev["max_input_channels"] > 0 and (
                name_low in dev_low or dev_low in name_low
            ):
                return idx
        return None

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
                    device=self._meter_device(),
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
        if self.microphone.state() == QtMultimedia.QMediaRecorder.RecordingState:
            self.microphone.stop()
