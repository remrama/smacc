"""Dream-recording window: microphone capture, input level meter, and survey."""

from __future__ import annotations

import webbrowser

import sounddevice as sd
from PyQt5 import QtCore, QtMultimedia, QtWidgets

from .. import audio
from ..config import SURVEY_OPTIONS
from ..paths import dreams_directory
from ..session import SmaccSession
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

        layout = QtWidgets.QFormLayout()
        layout.setLabelAlignment(QtCore.Qt.AlignRight)
        layout.addRow(make_section_title("Dream recording"))
        layout.addRow("Device:", available_microphones_dropdown)
        layout.addRow("Survey:", surveyComboBox)
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
        """Handle a new microphone selection."""
        self.session.logger.debug(f"New microphone {text} selected!")

    def refresh_available_microphones(self):
        """Populate the microphone dropdown with available audio input devices."""
        self.available_microphones_dropdown.clear()
        devices = QtMultimedia.QAudioDeviceInfo.availableDevices(
            QtMultimedia.QAudio.AudioInput
        )
        for device in devices:
            device_name = device.deviceName()
            device_realm = device.realm()
            device_str = f"{device_name} [{device_realm}]"
            self.available_microphones_dropdown.addItem(device_str)
        if devices:
            self.available_microphones_dropdown.setCurrentIndex(0)
        else:
            self.session.show_error_popup("No microphones found.", parent=self)

    def record(self):
        state = self.microphone.state()  # recording / paused / stopped
        if state == QtMultimedia.QMediaRecorder.StoppedState:
            self.n_report_counter += 1
            basename = (
                f"sub-{self.session.subject}_ses-{self.session.session}"
                f"_report-{self.n_report_counter:02d}.wav"
            )
            export_fname = dreams_directory / basename
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
                webbrowser.open(survey_url, new=1, autoraise=False)
            port_msg = "DreamReportStarted"
        else:
            port_msg = "DreamReportStopped"
        self.session.send_event_marker(self.session.portcodes[port_msg], port_msg)

    # ----- input level meter (#25) ------------------------------------------

    def init_level_meter(self) -> None:
        """Set up the input level meter stream and its refresh timer."""
        self.meter_stream: sd.InputStream | None = None
        self._input_level_db = audio.FLOOR_DBFS
        self.meter_timer = QtCore.QTimer(self)
        self.meter_timer.setInterval(50)  # ~20 Hz display refresh
        self.meter_timer.timeout.connect(self.update_level_meter)

    def toggle_level_monitor(self, enabled: bool) -> None:
        """Start/stop monitoring the default input device's level."""
        if enabled:
            try:
                self.meter_stream = sd.InputStream(
                    channels=1, callback=self._meter_callback
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

    # ----- survey + study state ---------------------------------------------

    def current_survey_url(self) -> str:
        """Resolve the survey URL from the dropdown (preset data or typed text)."""
        data = self.surveyComboBox.currentData()
        if data:
            return str(data)
        return self.surveyComboBox.currentText().strip()

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
        survey_options = {
            self.surveyComboBox.itemText(i): self.surveyComboBox.itemData(i)
            for i in range(self.surveyComboBox.count())
            if self.surveyComboBox.itemData(i)
        }
        return {
            "survey_url": self.current_survey_url(),
            "survey_options": survey_options,
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
