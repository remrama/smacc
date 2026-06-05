"""Initialize a new session and open the main interface."""

from __future__ import annotations

import logging
import os
import shutil
import time
import webbrowser
from collections.abc import Callable
from pathlib import Path

import sounddevice as sd
from pylsl import StreamInfo, StreamOutlet
from PyQt5 import QtCore, QtGui, QtMultimedia, QtWidgets

from smacc import bids, study, utils

from .config import (
    DEVELOPMENT_ID,
    PPORT_ADDRESS,
    PPORT_CODES,
    SURVEY_OPTIONS,
    VERSION,
)

try:
    from blinkstick import blinkstick
except ImportError:
    blinkstick = None


# Define directories.
data_directory = utils.get_data_directory()
logs_directory = data_directory / "logs"
cues_directory = data_directory / "cues"
dreams_directory = data_directory / "dreams"
logs_directory.mkdir(exist_ok=True)
cues_directory.mkdir(exist_ok=True)
dreams_directory.mkdir(exist_ok=True)

COMMON_EVENT_CODES = {
    "REM detected": 41,
    "Tech in room": 42,
    "TLR training start": 43,
    "TLR training end": 44,
    "LRLR detected": 45,
    "Sleep onset": 46,
    "Lights off": 47,
    "Lights on": 48,
    "Clapper": 49,
}

COMMON_EVENT_TIPS = {
    "Lights off": "Mark the beginning of sleep session",
    "Lights on": "Mark the end of sleep session",
    "TLR training start": "Mark the start of Targeted Lucidity Reactivation training",
    "TLR training end": "Mark the end of Targeted Lucidity Reactivation training",
    "Tech in room": "Mark the entry of an experimenter/technician in the participant bedroom",
    "Sleep onset": "Mark observed sleep onset",
    "REM detected": "Mark observed REM",
    "LRLR detected": "Mark an observed left-right-left-right lucid signal",
    "Clapper": "Synchronize a marker with EEG",
    "Note": "Mark a note and enter free text",
}


#########################################################
#########    Create some custom PyQt classes    #########
#########################################################


class BorderWidget(QtWidgets.QFrame):
    """thing to make a border https://stackoverflow.com/a/7351943"""

    def __init__(self, *args):
        super().__init__(*args)
        self.setStyleSheet(
            "background-color: rgb(0,0,0,0); margin:0px; border:4px solid rgb(0, 0, 0); border-radius: 25px; "
        )


class SubjectSessionRequest(QtWidgets.QDialog):
    """A popup window that pops up once during initialization
    to get subject and session IDs from the user.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Subject and session information")
        # Removes the default "What's this?" question mark icon from the titlebar.
        self.setWindowFlags(self.windowFlags() ^ QtCore.Qt.WindowContextHelpButtonHint)
        # self.setWhatsThis("What's this?")
        # Create subject and session text inputs.
        self.subject_id = QtWidgets.QLineEdit(self)
        self.session_id = QtWidgets.QLineEdit(self)
        self.subject_id.setText(str(DEVELOPMENT_ID))
        self.session_id.setText("1")
        self.subject_id.setValidator(
            QtGui.QIntValidator(0, 999)
        )  # Require a 3-digit number
        self.session_id.setValidator(
            QtGui.QIntValidator(0, 999)
        )  # Require a 3-digit number
        # Create buttons to accept values or cancel.
        buttonBox = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self
        )
        buttonBox.accepted.connect(self.accept)
        buttonBox.rejected.connect(self.reject)
        # Put everything in a layout.
        layout = QtWidgets.QFormLayout(self)
        layout.addRow("Subject ID", self.subject_id)
        layout.addRow("Session ID", self.session_id)
        layout.addWidget(buttonBox)

    def get_inputs(self) -> tuple[int, int]:
        """Return user-specified subject and session IDs as integers."""
        subject_int = int(self.subject_id.text())
        session_int = int(self.session_id.text())
        return subject_int, session_int


#####################################
#########    Main window    #########
#####################################


class SmaccWindow(QtWidgets.QMainWindow):
    """Main interface."""

    def __init__(self, subject_id: int, session_id: int) -> None:
        super().__init__()

        self.n_report_counter = 0  # cumulative counter for determining filenames

        # store the subject and session IDs
        # self.subject_id = subject_id
        # self.session_id = session_id
        # build a stringy-thing that will be used for lots of filenames
        self.subject = subject_id
        self.session = session_id

        self.init_logger()

        self.pport_address = PPORT_ADDRESS
        self.portcodes = PPORT_CODES

        self.cues_directory = cues_directory
        # self.noise_directory = noise_directory

        self.init_blinkstick()
        self.init_audio_stimulation_setup()
        self.init_noise_player()
        self.init_microphone()

        self.init_main_window()

        init_msg = "Opened SMACC v" + VERSION
        self.log_info_msg(init_msg)

        self.init_lsl_stream()

    def show_error_popup(self, short_msg, long_msg=None):
        # self.log_info_msg("ERROR")
        win = QtWidgets.QMessageBox()
        # # win.setIcon(QtWidgets.QMessageBox.Question)
        # win.setWindowIcon(QtGui.QIcon("./thumb-small.png"))
        # win.setIconPixmap(QtGui.QPixmap("./thumb.png"))
        win.setText(short_msg)
        if long_msg is not None:
            win.setInformativeText(long_msg)
        win.setWindowTitle("Error")
        win.exec()

    # def show_error_popup(self, short_msg):
    #     em = QtWidgets.QErrorMessage()
    #     em.showMessage(short_msg)
    #     em.exec()

    def log_info_msg(self, msg):
        """wrapper just to make sure msg goes to viewer too
        (should probably split up)
        """
        # log the message
        self.logger.info(msg)

        # print message to the GUI viewer box thing
        self.logviewList.addItem(time.strftime("%H:%M:%S") + " - " + msg)
        self.logviewList.repaint()
        self.logviewList.scrollToBottom()
        # item = pg.QtGui.QListWidgetItem(msg)
        # if warning: # change txt color
        #     item.setForeground(pg.QtCore.Qt.red)
        # self.eventList.addItem(item)
        # self.eventList.update()

    def init_lsl_stream(self, stream_id: str = "myuidw43536") -> None:
        """Create the LSL marker stream and its outlet."""
        self.info = StreamInfo("MyMarkerStream", "Markers", 1, 0, "string", stream_id)
        self.outlet = StreamOutlet(self.info)

    def send_event_marker(self, portcode: int, port_msg: str) -> None:
        """Wrapper to avoid rewriting if not None a bunch
        to make sure the msg also gets logged to output file and gui
        """
        self.outlet.push_sample([str(portcode)])
        log_msg = f"{port_msg} - portcode {portcode}"
        self.log_info_msg(log_msg)

    def init_logger(self) -> None:
        """Initialize the logger that writes to a per-session log file."""
        path_name = f"sub-{self.subject:03d}_ses-{self.session:03d}_smacc-{VERSION}.log"
        log_path = logs_directory / path_name
        self.log_path = log_path  # kept for BIDS events export
        self.logger = logging.getLogger("smacc")
        self.logger.setLevel(logging.DEBUG)
        # open file handler to save external file
        write_mode = "w" if self.subject == DEVELOPMENT_ID else "x"
        fh = logging.FileHandler(log_path, mode=write_mode, encoding="utf-8")
        fh.setLevel(logging.DEBUG)  # this determines what gets written to file
        # create formatter and add it to the handlers
        formatter = logging.Formatter(
            fmt="%(asctime)s.%(msecs)03d, %(levelname)s, %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        fh.setFormatter(formatter)
        # add the handler to the logger
        self.logger.addHandler(fh)

    def init_main_window(self):
        """
        Initialize SMACC's main window, just the frame.
        This is the "bars" (menu bar, tool bar, status bar)
        And the widgets.
        """

        ########################################################################
        # MENU BAR
        ########################################################################

        aboutAction = QtWidgets.QAction(
            self.style().standardIcon(QtWidgets.QStyle.SP_MessageBoxInformation),
            "&About",
            self,
        )
        aboutAction.setStatusTip("About SMACC")
        aboutAction.triggered.connect(self.show_about_popup)

        quitAction = QtWidgets.QAction(
            self.style().standardIcon(QtWidgets.QStyle.SP_BrowserStop), "&Quit", self
        )
        quitAction.setShortcut("Ctrl+Q")
        quitAction.setStatusTip("Quit/close interface")
        quitAction.triggered.connect(self.close)  # close goes to closeEvent

        # File -> Save/Load study: persist session setup to a reusable study.json.
        saveStudyAction = QtWidgets.QAction("&Save study…", self)
        saveStudyAction.setStatusTip("Save the current setup to a study folder.")
        saveStudyAction.triggered.connect(self.save_study)
        loadStudyAction = QtWidgets.QAction("&Load study…", self)
        loadStudyAction.setStatusTip("Load setup from a saved study.json.")
        loadStudyAction.triggered.connect(self.load_study)

        exportEventsAction = QtWidgets.QAction("&Export events (BIDS)…", self)
        exportEventsAction.setStatusTip(
            "Export this session's events log as a BIDS events.tsv."
        )
        exportEventsAction.triggered.connect(self.export_events_bids)

        # View -> Always on top: keep the control window above the dimmed bedroom screen.
        alwaysOnTopAction = QtWidgets.QAction("Always on &top", self)
        alwaysOnTopAction.setStatusTip("Keep the SMACC window above all other windows.")
        alwaysOnTopAction.setCheckable(True)
        alwaysOnTopAction.setChecked(True)
        alwaysOnTopAction.toggled.connect(self.toggle_always_on_top)

        menuBar = self.menuBar()
        # menuBar.setNativeMenuBar(False)  # needed for pyqt5 on Mac
        fileMenu = menuBar.addMenu("&File")
        fileMenu.addAction(saveStudyAction)
        fileMenu.addAction(loadStudyAction)
        fileMenu.addSeparator()
        fileMenu.addAction(exportEventsAction)
        helpMenu = menuBar.addMenu("&Help")
        helpMenu.addAction(aboutAction)
        helpMenu.addAction(quitAction)
        viewMenu = menuBar.addMenu("&View")
        viewMenu.addAction(alwaysOnTopAction)

        ########################################################################
        # TOOL BAR
        ########################################################################

        toolBar = QtWidgets.QToolBar("Visual parameters", self)
        self.addToolBar(QtCore.Qt.LeftToolBarArea, toolBar)
        # toolBar.addAction(colorpickerAction)

        ########################################################################
        # STATUS BAR
        ########################################################################

        self.statusBar().showMessage("Ready")

        ########################################################################
        # VISUAL STIMULATION WIDGETS AND LAYOUT (BUTTON STACK)
        ########################################################################

        visualtitleLabel = QtWidgets.QLabel("Visual stimulation")
        visualtitleLabel.setAlignment(QtCore.Qt.AlignCenter)
        # titleLabel.setStyleSheet("font: 30pt Comic Sans MS")
        visualtitleLabel.setStyleSheet("font: 18pt")

        # Visual device picker: QComboBox signal --> update device slot
        available_blinksticks_dropdown = QtWidgets.QComboBox()
        available_blinksticks_dropdown.setStatusTip("Select visual stimulation device")
        # available_blinksticks_dropdown.setMaximumWidth(200)
        available_blinksticks_dropdown.currentTextChanged.connect(
            self.set_new_blinkstick
        )
        # > populate this dropdown with refresh function, so it can happen later outside init too
        self.available_blinksticks_dropdown = available_blinksticks_dropdown
        self.refresh_available_blinksticks()

        # Visual play button: QPushButton signal --> visual_stim slot
        blinkButton = QtWidgets.QPushButton("Play BlinkStick", self)
        blinkButton.setStatusTip("Present visual stimulus.")
        blinkButton.clicked.connect(self.stimulate_visual)

        # Visual color picker: QPushButton signal --> QColorPicker slot
        colorpickerButton = QtWidgets.QPushButton("Select color", self)
        colorpickerButton.setStatusTip("Pick the visual stimulus color.")
        colorpickerButton.setIcon(QtGui.QIcon("./color.png"))
        colorpickerButton.clicked.connect(self.pick_color)

        # Visual frequency selector: QDoubleSpinBox signal --> update visual parameters slot
        freqSpinBox = QtWidgets.QDoubleSpinBox(self)
        freqSpinBox.setStatusTip(
            "Pick light stimulation length (how long the light will stay on in seconds)."
        )
        # freqSpinBox.setRange(0, 100)
        freqSpinBox.setMinimum(0)
        freqSpinBox.setMaximum(60)
        # freqSpinBox.setPrefix("Blink length: ")
        freqSpinBox.setSuffix(" seconds")
        freqSpinBox.setSingleStep(0.1)
        freqSpinBox.valueChanged.connect(self.handle_freq_change)
        # freqSpinBox.textChanged.connect(self.value_changed_str)
        freqSpinBox.setValue(self.bstick_blink_freq)
        self.freqSpinBox = freqSpinBox

        # Compile them into a vertical layout
        visualstimLayout = QtWidgets.QFormLayout()
        visualstimLayout.setLabelAlignment(QtCore.Qt.AlignRight)
        visualstimLayout.addRow(visualtitleLabel)
        visualstimLayout.addRow("Device:", available_blinksticks_dropdown)
        visualstimLayout.addRow("Color:", colorpickerButton)
        visualstimLayout.addRow("Length:", freqSpinBox)
        visualstimLayout.addRow(blinkButton)

        ########################################################################
        # AUDIO STIMULATION WIDGET
        ########################################################################

        audiotitleLabel = QtWidgets.QLabel("Audio stimulation")
        audiotitleLabel.setAlignment(QtCore.Qt.AlignCenter)
        audiotitleLabel.setStyleSheet("font: 18pt")

        # Audio stimulation device picker: QComboBox signal --> update device slot
        available_speakers_dropdown = QtWidgets.QComboBox()
        available_speakers_dropdown.setStatusTip("Select audio stimulation device")
        available_speakers_dropdown.setPlaceholderText("No speaker devices were found.")
        # available_speakers_dropdown.setMaximumWidth(200)
        # inputIcon = self.style().standardIcon(getattr(QtWidgets.QStyle, "SP_DialogNoButton"))
        available_speakers_dropdown.currentTextChanged.connect(self.set_new_speakers)
        self.available_speakers_dropdown = available_speakers_dropdown
        self.refresh_available_speakers()

        wavselectorLayout = QtWidgets.QHBoxLayout()
        wavselectorLabel = QtWidgets.QLabel("Sound:", self)
        wavselectorEdit = QtWidgets.QLineEdit(self)
        wavselectorButton = QtWidgets.QPushButton("Browse", self)
        wavselectorButton.clicked.connect(self.open_wav_selector)
        wavselectorLayout.addWidget(wavselectorLabel)
        wavselectorLayout.addWidget(wavselectorEdit)
        wavselectorLayout.addWidget(wavselectorButton)
        wavselectorEdit.textChanged.connect(
            self.update_audio_source
        )  # For programmatic changes
        # wavselectorEdit.textEdited.connect(self.update_audio_source)  # For user changes
        wavselectorEdit.editingFinished.connect(
            self.update_audio_source
        )  # For user changes
        self.wavselectorEdit = wavselectorEdit

        # Audio volume selector: QDoubleSpinBox signal --> update audio volume slot
        volumeSpinBox = QtWidgets.QDoubleSpinBox(self)
        volumeSpinBox.setStatusTip(
            "Select volume of audio stimulation (must be in range 0-1)."
        )
        # volumeSpinBox.setRange(0, 1)
        volumeSpinBox.setMinimum(0)
        volumeSpinBox.setMaximum(
            1
        )  # Currently using QSoundEffect which only allows 0-1
        # volumeSpinBox.setPrefix("Volume: ")
        # volumeSpinBox.setSuffix(" dB")
        volumeSpinBox.setSingleStep(0.01)
        volumeSpinBox.valueChanged.connect(self.update_audio_volume)
        volumeSpinBox.setValue(0.2)
        self.volumeSpinBox = volumeSpinBox

        # Loop toggle: when checked, the cue repeats until stopped.
        loopCheckBox = QtWidgets.QCheckBox("Loop until stopped", self)
        loopCheckBox.setStatusTip(
            "Repeat the cue continuously until the Stop button is pressed."
        )
        loopCheckBox.toggled.connect(self.update_audio_loop)
        self.loopCheckBox = loopCheckBox

        # Play/Stop buttons: QPushButton signals --> play/stop functions
        playButton = QtWidgets.QPushButton("Play soundfile", self)
        playButton.setStatusTip("Play the selected sound file.")
        # playButton.setIcon(QtGui.QIcon("./color.png"))
        playButton.clicked.connect(self.stimulate_audio)
        stopcueButton = QtWidgets.QPushButton("Stop", self)
        stopcueButton.setStatusTip("Stop the currently playing cue.")
        stopcueButton.clicked.connect(self.stop_audio)
        playstopcueLayout = QtWidgets.QHBoxLayout()
        playstopcueLayout.addWidget(playButton)
        playstopcueLayout.addWidget(stopcueButton)

        # Visible "playing/looping" indicator so a cue is never left running silently.
        cueStatusLabel = QtWidgets.QLabel("■ stopped", self)
        cueStatusLabel.setAlignment(QtCore.Qt.AlignCenter)
        self.cueStatusLabel = cueStatusLabel

        # Compile them into a vertical layout
        audiostimLayout = QtWidgets.QFormLayout()
        audiostimLayout.setLabelAlignment(QtCore.Qt.AlignRight)
        audiostimLayout.addRow(audiotitleLabel)
        audiostimLayout.addRow("Device:", available_speakers_dropdown)
        audiostimLayout.addRow("Volume:", volumeSpinBox)
        audiostimLayout.addRow(wavselectorLayout)
        audiostimLayout.addRow(loopCheckBox)
        audiostimLayout.addRow(playstopcueLayout)
        audiostimLayout.addRow(cueStatusLabel)

        # #### audio device list menu
        # audioMenu = menuBar.addMenu("&Audio")
        # inputMenu = audioMenu.addMenu(inputIcon, "&Input device")
        # # outputMenu = audioMenu.addMenu(QtGui.QIcon("./img/output.png"), "&Output device")

        ########################################################################
        # DREAM REPORT WIDGET
        ########################################################################

        recordingtitleLabel = QtWidgets.QLabel("Dream recording")
        recordingtitleLabel.setAlignment(QtCore.Qt.AlignCenter)
        recordingtitleLabel.setStyleSheet("font: 18pt")

        # Microphone device picker: QComboBox signal --> update device slot
        available_microphones_dropdown = QtWidgets.QComboBox()
        available_microphones_dropdown.setStatusTip("Select microphone")
        available_microphones_dropdown.setPlaceholderText("No microphones were found.")
        # available_microphones_dropdown.setMaximumWidth(200)
        available_microphones_dropdown.currentTextChanged.connect(
            self.set_new_microphone
        )
        self.available_microphones_dropdown = available_microphones_dropdown
        self.refresh_available_microphones()

        micrecordButton = QtWidgets.QPushButton("Record dream report", self)
        micrecordButton.setStatusTip("Ask for a dream report and start recording.")
        micrecordButton.setCheckable(True)
        micrecordButton.clicked.connect(self.start_or_stop_recording)

        # Survey selector: editable dropdown of named presets (or a typed-in URL).
        # The chosen survey opens in the browser when a dream report starts.
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

        microphoneLayout = QtWidgets.QFormLayout()
        microphoneLayout.setLabelAlignment(QtCore.Qt.AlignRight)
        microphoneLayout.setLabelAlignment(QtCore.Qt.AlignRight)
        microphoneLayout.addRow(recordingtitleLabel)
        microphoneLayout.addRow("Device:", available_microphones_dropdown)
        microphoneLayout.addRow("Survey:", surveyComboBox)
        microphoneLayout.addRow("Play/Stop:", micrecordButton)

        ########################################################################
        # NOISE PLAYER WIDGET
        ########################################################################

        noisetitleLabel = QtWidgets.QLabel("Noise machine")
        noisetitleLabel.setAlignment(QtCore.Qt.AlignCenter)
        noisetitleLabel.setStyleSheet("font: 18pt")

        # Noise device picker: QComboBox signal --> update device slot
        available_noisespeakers_dropdown = QtWidgets.QComboBox()
        available_noisespeakers_dropdown.setStatusTip("Select speakers for noise")
        # available_noisespeakers_dropdown.setMaximumWidth(200)
        available_noisespeakers_dropdown.currentTextChanged.connect(
            self.set_new_noisespeakers
        )
        self.available_noisespeakers_dropdown = available_noisespeakers_dropdown
        self.refresh_available_noisespeakers()

        # Noise color picker: QComboBox signal --> update noise color parameter
        available_noisecolors = ["white", "pink", "brown"]
        available_noisecolors_dropdown = QtWidgets.QComboBox()
        available_noisecolors_dropdown.setStatusTip("Select speakers for noise")
        available_noisecolors_dropdown.currentTextChanged.connect(
            self.set_new_noisecolor
        )
        # available_noisecolors_dropdown.addItems(available_noisecolors)
        for color in available_noisecolors:
            pixmap = QtGui.QPixmap(16, 16)
            pixmap.fill(QtGui.QColor(color))
            icon = QtGui.QIcon(pixmap)
            available_noisecolors_dropdown.addItem(icon, color)
        self.available_noisecolors_dropdown = available_noisecolors_dropdown

        # Noise volume selector: QDoubleSpinBox signal --> update audio volume slot
        noisevolumeSpinBox = QtWidgets.QDoubleSpinBox(self)
        noisevolumeSpinBox.setStatusTip(
            "Select volume of noise (must be in range 0-1)."
        )
        # noisevolumeSpinBox.setRange(0, 1)
        noisevolumeSpinBox.setMinimum(0)
        noisevolumeSpinBox.setMaximum(
            1
        )  # Currently using QSoundEffect which only allows 0-1
        # noisevolumeSpinBox.setPrefix("Volume: ")
        # noisevolumeSpinBox.setSuffix(" dB")
        noisevolumeSpinBox.setSingleStep(0.01)
        noisevolumeSpinBox.valueChanged.connect(self.update_noise_volume)
        noisevolumeSpinBox.setValue(0.2)
        self.noisevolumeSpinBox = noisevolumeSpinBox

        # Play button: QPushButton signal --> play function
        playnoiseButton = QtWidgets.QPushButton("Play noise", self)
        playnoiseButton.setStatusTip("Play the selected noise color.")
        # playButton.setIcon(QtGui.QIcon("./color.png"))
        playnoiseButton.clicked.connect(self.play_noise)
        # Stop button: QPushButton signal --> stop function
        stopnoiseButton = QtWidgets.QPushButton("Stop noise", self)
        stopnoiseButton.setStatusTip("Stop the selected noise color.")
        stopnoiseButton.clicked.connect(self.stop_noise)

        playstopnoiseLayout = QtWidgets.QHBoxLayout()
        playstopnoiseLayout.addWidget(playnoiseButton)
        playstopnoiseLayout.addWidget(stopnoiseButton)

        noiseLayout = QtWidgets.QFormLayout()
        noiseLayout.setLabelAlignment(QtCore.Qt.AlignRight)
        noiseLayout.addRow(noisetitleLabel)
        noiseLayout.addRow("Device:", available_noisespeakers_dropdown)
        noiseLayout.addRow("Color/Type:", available_noisecolors_dropdown)
        noiseLayout.addRow("Volume:", noisevolumeSpinBox)
        noiseLayout.addRow(playstopnoiseLayout)

        ########################################################################
        # COMMON EVENT MARKERS WIDGET
        ########################################################################

        eventmarkertitleLabel = QtWidgets.QLabel("Event logging")
        eventmarkertitleLabel.setAlignment(QtCore.Qt.AlignCenter)
        eventmarkertitleLabel.setStyleSheet("font: 18pt")

        eventsLayout = QtWidgets.QGridLayout()
        eventsLayout.addWidget(eventmarkertitleLabel, 0, 0, 1, 2)
        n_events = len(COMMON_EVENT_TIPS)
        for i, (event, tip) in enumerate(COMMON_EVENT_TIPS.items()):
            shortcut = str(i + 1)
            label = f"{event} ({shortcut})"
            button = QtWidgets.QPushButton(label, self)
            button.setStatusTip(tip)
            button.setShortcut(shortcut)
            # button.setCheckable(False)
            if event == "Note":
                button.clicked.connect(self.open_note_marker_dialogue)
            else:
                button.clicked.connect(self.handle_event_button)
            row = 1 + i
            if i >= (halfsize := int(n_events / 2)):
                row -= halfsize
            col = 1 if i >= halfsize else 0
            eventsLayout.addWidget(button, row, col)

        ########################################################################
        # LOG VIEWER WIDGET
        ########################################################################

        logviewertitleLabel = QtWidgets.QLabel("Log viewer")
        logviewertitleLabel.setAlignment(QtCore.Qt.AlignCenter)
        logviewertitleLabel.setStyleSheet("font: 18pt")

        # Events log viewer --> gets updated when events are logged
        logviewList = QtWidgets.QListWidget()
        logviewList.setAutoScroll(True)
        # logviewList.setGeometry(20,20,100,700)
        self.logviewList = logviewList

        logviewLayout = QtWidgets.QFormLayout()
        logviewLayout.addRow(logviewertitleLabel)
        logviewLayout.addRow(logviewList)

        ########################################################################
        # COMPILE ALL WIDGETS INTO CENTRAL WIDGET
        ########################################################################

        central_layout = QtWidgets.QGridLayout()
        central_layout.addLayout(visualstimLayout, 0, 0)
        central_layout.addLayout(audiostimLayout, 1, 0)
        central_layout.addLayout(noiseLayout, 2, 0)
        central_layout.addLayout(logviewLayout, 0, 1)
        central_layout.addLayout(microphoneLayout, 1, 1)
        central_layout.addLayout(eventsLayout, 2, 1)
        central_widget = QtWidgets.QWidget()
        central_widget.setContentsMargins(5, 5, 5, 5)
        central_widget.move(100, 100)
        central_widget.setLayout(central_layout)
        self.setCentralWidget(central_widget)

        # # main window stuff
        # xywh = (50, 100, self.winWidth, self.winHeight) # xloc, yloc, width, height
        # self.setGeometry(*xywh)
        # self.setMinimumSize(300, 200)
        self.setWindowTitle("SMACC")
        windowIcon = self.style().standardIcon(
            QtWidgets.QStyle.SP_ToolBarHorizontalExtensionButton
        )
        self.setWindowIcon(windowIcon)
        # self.openAction = QAction(QIcon(":file-open.svg"), "&Open...", self)
        # self.setGeometry(100, 100, 600, 400)
        self.resize(1200, 500)
        # Match the default-checked "Always on top" menu action.
        self.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, True)
        self.show()

    def toggle_always_on_top(self, enabled: bool) -> None:
        """Toggle the window's always-on-top hint (from the View menu)."""
        self.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, enabled)
        # Re-applying window flags hides the window on some platforms; re-show it.
        self.show()
        self.log_info_msg(f"Always-on-top {'enabled' if enabled else 'disabled'}")

    def show_about_popup(self):
        win = QtWidgets.QMessageBox()
        # win.setIcon(QtWidgets.QMessageBox.Question)
        # win.setWindowIcon(QtGui.QIcon("./thumb-small.png"))
        # win.setIconPixmap(QtGui.QPixmap("./thumb.png"))
        win.setStandardButtons(QtWidgets.QMessageBox.Ok)
        win.setWindowTitle("About SMACC")
        win.setText("Sleep Manipulation and Communication Clickything")
        win.setInformativeText(f"version: v{VERSION}\nhttps://github.com/remrama/smacc")
        # win.setDetailedText("detailshere")
        # win.setStyleSheet("QLabel{min-width:500 px; font-size: 24px;} QPushButton{ width:250px; font-size: 18px; }");
        # win.setGeometry(200, 150, 100, 40)
        win.exec()

    def handle_event_button(self):
        sender = self.sender()
        text = sender.text().split("(")[0].strip()
        code = COMMON_EVENT_CODES[text]
        self.send_event_marker(code, text)

    def open_wav_selector(self):
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select a File", str(self.cues_directory), "Audio (*.wav)"
        )
        if filename:
            path = Path(filename)
            self.wavselectorEdit.setText(str(path))

    def set_new_noisecolor(self, text: str) -> None:
        """Restart noise playback when the noise color changes (``text``)."""
        # filepath = Path(".") / text
        # content = QtCore.QUrl.fromLocalFile(str(filepath))
        # self.noiseplayer.setSource(content)
        if self.noise_stream is not None:  # or isactive
            self.stop_noise()
            self.play_noise()

    def set_new_speakers(self, text: str) -> None:
        """Handle a new audio-stimulation speaker selection."""
        print(f"New speakers {text} selected!")

    def set_new_noisespeakers(self, text: str) -> None:
        """Text is the device name, with host api string appended to the end."""
        self.noiseplayer_device = text

    def set_new_microphone(self, text: str) -> None:
        """Handle a new microphone selection."""
        print(f"New microphone {text} selected!")

    ############################################################################
    # Functions for refreshing/searching for connected devices (inputs and outputs)
    ############################################################################

    def refresh_available_noisespeakers(self):
        """
        Populate the audio stimulation device selection menu with currently
        available speakers.

        seealso: refresh_available_speakers
        """
        self.available_noisespeakers_dropdown.clear()
        HOST_API = "Windows WASAPI"
        hostapi = [api["name"] for api in sd.query_hostapis()].index(HOST_API)
        devices = sd.query_devices()
        for device in devices:
            if device["hostapi"] == hostapi and device["max_output_channels"] > 0:
                device_name = device["name"]
                device_str = f"{device_name}, {HOST_API}"
                self.available_noisespeakers_dropdown.addItem(device_str)
        if devices:
            self.available_noisespeakers_dropdown.setCurrentIndex(0)
        else:
            self.show_error_popup("No audio devices found.")

    def refresh_available_speakers(self):
        """
        Populate the audio stimulation device selection menu with currently
        available speakers.
        seealso: refresh_available_noisespeakers
        """
        self.available_speakers_dropdown.clear()
        devices = QtMultimedia.QAudioDeviceInfo.availableDevices(
            QtMultimedia.QAudio.AudioOutput
        )
        devices = [d for d in devices if d.realm() != "default"]
        for device in devices:
            device_name = device.deviceName()
            device_realm = (
                device.realm()
            )  # This differentiates the duplicate of default output
            device_str = f"{device_name} [{device_realm}]"
            self.available_speakers_dropdown.addItem(device_str)
        if devices:
            self.available_speakers_dropdown.setCurrentIndex(0)
        else:
            self.show_error_popup("No audio devices found.")

    def refresh_available_microphones(self):
        """
        Populate the microphone dropdown menu with all available audio input devices.
        """
        self.available_microphones_dropdown.clear()
        devices = QtMultimedia.QAudioDeviceInfo.availableDevices(
            QtMultimedia.QAudio.AudioInput
        )
        # devices = self.microphone.audioInputs()
        # # don't know y each device shows up twice
        # devices = list(set(devices))
        for device in devices:
            device_name = device.deviceName()
            device_realm = device.realm()
            device_str = f"{device_name} [{device_realm}]"
            self.available_microphones_dropdown.addItem(device_str)
        if devices:
            self.available_microphones_dropdown.setCurrentIndex(0)
        else:
            self.show_error_popup("No microphones found.")

    def set_new_blinkstick(self, text):
        """
        Set new BlinkStick for visual stimulation.
        Method that takes input from dropdown selection menu.
        Only activated upon a change/new selection.

        text : str
            Text of the menu item from the dropdown.
        See also: refresh_available_blinksticks
        """
        serial_number = text.split(". ")[1].split(")")[0]
        self.bstick = blinkstick.find_by_serial(serial_number)

    def refresh_available_blinksticks(self):
        """
        Searches for all available BlinkSticks and populates the dropdown menu with them.
        Refresh the dropdown menu with currently available BlinkSticks.
        Clears all existing, searches again, and populates the menu.
        Note this will clear currently selected.
        Requires installation of `blinkstick` package (as does rest of vis stim).

        Automatically selects the first found BlinkStick by default.

        See also: set_new_blinkstick
        """
        # Clear existing devices from the dropdown menu
        self.available_blinksticks_dropdown.clear()
        if blinkstick is None:
            devices = []
            self.show_error_popup(
                "Use of visual stimulation requires `blinkstick` Python package. Unable to search for devices."
            )
        else:
            devices = blinkstick.find_all()
        # Add each device to the dropdown menu
        for d in devices:
            product_name = d.device.product_name
            serial_number = d.device.serial_number
            version_number = d.device.version_number
            device_str = (
                f"{product_name} v{version_number} (Serial No. {serial_number})"
            )
            self.available_blinksticks_dropdown.addItem(device_str)
        if devices:
            self.available_blinksticks_dropdown.setCurrentIndex(0)
        else:
            self.show_error_popup("No BlinkSticks found.")

    def update_input_device(self):
        # if the current input is re-selected it still "changes" here
        # update the menu checkmarks
        # the only checkmark that gets AUTOMATICALLY updated is the one
        # that was clicked, so change all the others, and change BACK
        # the one that was undone if it was already the audio input (has to be something)
        checked = self.sender().isChecked()
        if checked:
            new_device_name = self.sender().text()
            for menu_item in self.input_menu_items:
                device_name = menu_item.text()
                if device_name == new_device_name:
                    self.microphone.setAudioInput(new_device_name)
                    # menu_item.setChecked(True) # happens by default
                else:  # need to uncheck the one that WAS checked, so just hit all of them
                    menu_item.setChecked(False)
            # if new_device_name == self.microphone.audioInput():
            #     action.setChecked(True)
            # self.log_info_msg(f"INPUT DEVICE UPDATE {new_device_name}")
            # self.show_error_popup("Not implemented yet")
        elif not checked:
            # this is when someone tries to "unselect" an input.
            # can't be allowed, but pyqt will uncheck it, so recheck it
            self.sender().setChecked(True)  # recheck it
            # for menu_item in self.input_menu_items:
            #     if menu_item.iconText() == self.sender().text():
            #         menu_item.setChecked(True)

    def init_blinkstick(self):
        self.bstick_blink_freq = 1.0
        self.set_blink_color(0, 0, 0)  # default color: black/off
        # Draw button/icon/pixmap to show default color

    def set_blink_color(self, r: int, g: int, b: int) -> None:
        """Set the BlinkStick color from 0-255 RGB components.

        Stores the hex code (for study save/load) and precomputes the LED data.
        blinkstick.set_led_data expects G/R swapped: 3 values per LED, 32 LEDs.
        """
        self.bstick_rgb = (r, g, b, 255)
        self.bstick_hexcode = f"#{r:02x}{g:02x}{b:02x}"
        self.bstick_led_data = [g, r, b] * 32

    def init_audio_stimulation_setup(self):
        """Create media player for cue files."""
        player = QtMultimedia.QSoundEffect()
        # Default settings
        # player.setVolume(0)  # 0 to 1 -- Gets set already when parameter selector is made
        player.setLoopCount(1)
        player.playingChanged.connect(self.on_cue_playing_change)
        self.wavplayer = player

    def init_noise_player(self):
        """Create media player for noise files."""
        # player = QtMultimedia.QSoundEffect()
        # # player.setVolume(0)  # 0 to 1 -- Gets set already when parameter selector is made
        # player.setLoopCount(QtMultimedia.QSoundEffect.Infinite)
        # # player.playingChanged.connect(self.on_cuePlayingChange)
        # self.noiseplayer = player
        self.noise_stream = None

    @staticmethod
    def noise_color_funcs(color: str) -> Callable:
        """Return the noise-generation function for the given color name."""
        noise_functions = {
            "pink": utils.pink_noise,
            "blue": utils.blue_noise,
            "white": utils.white_noise,
            "brown": utils.brownian_noise,
            "violet": utils.violet_noise,
        }
        return noise_functions[color]

    def play_noise(self) -> None:
        """Start streaming the selected noise color to the selected device."""
        # self.noiseplayer.play()
        # device = self.noise_stream_device  # could also just set default sd device :/
        ## DO NOT actually need to connect dropdown to update device in this case.
        ## because need to use the device here at play, instead of setting it earlier
        device = self.available_noisespeakers_dropdown.currentText()
        color = self.available_noisecolors_dropdown.currentText()
        rate = 44100

        # global white_noise
        # if color == "white":
        #     noise_data = white_noise(44100).reshape(-1, 1)
        def callback(outdata, frames, time, status):
            """frames is the number of frames (rate)"""
            if status:
                print(status)
            outdata[:] = (
                self.noise_color_funcs(color)(rate).reshape(-1, 1)
                * self.noise_stream_volume
            )

        # add end_callback
        if self.noise_stream is None:
            self.noise_stream = sd.OutputStream(
                channels=1, blocksize=rate, callback=callback, device=device
            )
            self.noise_stream.start()
        # could use with statement and threading

    def stop_noise(self) -> None:
        """Stop and tear down the active noise stream, if any."""
        # self.noiseplayer.stop()
        if self.noise_stream is not None:
            self.noise_stream.abort()
            self.noise_stream = None

    def init_microphone(self):
        """initialize the microphone/recorder to collect dream reports
        Do this early so that a list of devices can be generated
        to build the menubar options for changing the input device.
        Not allowing options to change settings for now.

        The output location is updated whenever a new recording is started.
        The default device is selected here but can be updated from menubar.
        """
        # audio recorder stuff
        # https://stackoverflow.com/a/64300056
        # https://doc.qt.io/qt-5/qtmultimedia-multimedia-audiorecorder-example.html
        # https://flothesof.github.io/pyqt-microphone-fft-application.html
        settings = QtMultimedia.QAudioEncoderSettings()
        settings.setEncodingMode(QtMultimedia.QMultimedia.ConstantQualityEncoding)
        settings.setQuality(QtMultimedia.QMultimedia.NormalQuality)
        microphone = QtMultimedia.QAudioRecorder()
        microphone.setEncodingSettings(settings)
        # Connect stateChange to adjust color of button to indicate status
        microphone.stateChanged.connect(self.update_microphone_status)
        self.microphone = microphone

    def record(self):
        state = self.microphone.state()  # recording / paused / stopped
        if state == QtMultimedia.QMediaRecorder.StoppedState:
            ### start a new recording
            # generate filename
            self.n_report_counter += 1
            basename = f"sub-{self.subject:03d}_ses-{self.session:03d}_report-{self.n_report_counter:02d}.wav"
            export_fname = os.path.join(dreams_directory, basename)
            self.microphone.setOutputLocation(QtCore.QUrl.fromLocalFile(export_fname))
            self.microphone.record()
            # # filename = 'https://www.pachd.com/sfx/camera_click.wav'
            # # fullpath = QtCore.QDir.current().absoluteFilePath(filename)
        elif state == QtMultimedia.QMediaRecorder.RecordingState:
            self.microphone.stop()

    def update_microphone_status(self, state):
        if state == QtMultimedia.QMediaRecorder.StoppedState:
            self.logviewList.setStyleSheet("border: 0px solid red;")
        elif state == QtMultimedia.QMediaRecorder.RecordingState:
            self.logviewList.setStyleSheet("border: 3px solid red;")

    ############################################################################
    # Study config save/resume (study.json bundles)
    ############################################################################

    def gather_study_state(self) -> dict:
        """Collect the current GUI parameters into a serializable dict.

        Single source of truth for study save/load. Audio devices are excluded
        on purpose (only the noise device routes today).
        """
        survey_options = {
            self.surveyComboBox.itemText(i): self.surveyComboBox.itemData(i)
            for i in range(self.surveyComboBox.count())
            if self.surveyComboBox.itemData(i)
        }
        return {
            "cue_file": self.wavselectorEdit.text(),
            "cue_volume": self.volumeSpinBox.value(),
            "cue_loop": self.loopCheckBox.isChecked(),
            "noise_volume": self.noisevolumeSpinBox.value(),
            "noise_color": self.available_noisecolors_dropdown.currentText(),
            "blink_color": self.bstick_hexcode,
            "blink_length": self.bstick_blink_freq,
            "survey_url": self.current_survey_url(),
            "survey_options": survey_options,
        }

    def apply_study_state(self, state: dict) -> None:
        """Apply a study ``state`` dict to the GUI widgets.

        Setting widget values fires their existing signals, so volume/source/
        color/length all propagate without extra wiring.
        """
        if cue := state.get("cue_file"):
            self.wavselectorEdit.setText(cue)
        if (v := state.get("cue_volume")) is not None:
            self.volumeSpinBox.setValue(float(v))
        self.loopCheckBox.setChecked(bool(state.get("cue_loop", False)))
        if (v := state.get("noise_volume")) is not None:
            self.noisevolumeSpinBox.setValue(float(v))
        if color := state.get("noise_color"):
            idx = self.available_noisecolors_dropdown.findText(color)
            if idx >= 0:
                self.available_noisecolors_dropdown.setCurrentIndex(idx)
        if hexcode := state.get("blink_color"):
            qcolor = QtGui.QColor(hexcode)
            if qcolor.isValid():
                self.set_blink_color(qcolor.red(), qcolor.green(), qcolor.blue())
        if (length := state.get("blink_length")) is not None:
            self.freqSpinBox.setValue(float(length))
        self._apply_survey_state(state)

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

    def save_study(self) -> None:
        """Prompt for a study folder, copy the cue into it, and write study.json."""
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select a study folder", str(data_directory)
        )
        if not folder:
            return
        study_dir = Path(folder)
        state = self.gather_study_state()
        # Copy the cue WAV into the study folder so the bundle is self-contained.
        cue_file = state.get("cue_file")
        if cue_file and Path(cue_file).is_file():
            dest = study_dir / Path(cue_file).name
            if Path(cue_file).resolve() != dest.resolve():
                shutil.copy2(cue_file, dest)
            state["cue_file"] = Path(cue_file).name  # store basename, resolve on load
        try:
            study.save_study(study_dir / "study.json", state)
        except OSError as exc:
            self.show_error_popup("Could not save study.", str(exc))
            return
        self.log_info_msg(f"Saved study to {study_dir}")

    def load_study(self) -> None:
        """Prompt for a study.json and apply it, resolving the bundled cue file."""
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load study", str(data_directory), "Study (study.json)"
        )
        if not path:
            return
        study_path = Path(path)
        try:
            state = study.load_study(study_path)
        except (OSError, ValueError) as exc:
            self.show_error_popup("Could not load study.", str(exc))
            return
        # Resolve a bundled (basename) cue relative to the study folder.
        cue_file = state.get("cue_file")
        if cue_file and not Path(cue_file).is_absolute():
            candidate = study_path.parent / cue_file
            if candidate.is_file():
                state["cue_file"] = str(candidate)
        self.apply_study_state(state)
        self.log_info_msg(f"Loaded study from {study_path}")

    def export_events_bids(self) -> None:
        """Convert the session log to a BIDS events.tsv (+ JSON sidecar)."""
        if not self.log_path.is_file():
            self.show_error_popup("No log file to export yet.")
            return
        # Flush handlers so the on-disk log includes the latest events.
        for handler in self.logger.handlers:
            handler.flush()
        default = self.log_path.with_name(
            f"sub-{self.subject:03d}_ses-{self.session:03d}_events.tsv"
        )
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export events (BIDS)", str(default), "BIDS events (*.tsv)"
        )
        if not path:
            return
        try:
            log_text = self.log_path.read_text(encoding="utf-8")
            events = bids.log_to_events(log_text)
            bids.write_events_tsv(events, path)
            bids.write_events_json(Path(path).with_suffix(".json"))
        except OSError as exc:
            self.show_error_popup("Could not export events.", str(exc))
            return
        self.log_info_msg(f"Exported {len(events)} events to {path}")

    def current_survey_url(self) -> str:
        """Resolve the survey URL from the dropdown.

        A selected preset stores its URL as item data; a typed-in entry has no
        data, so fall back to the raw text. Empty == no survey.
        """
        data = self.surveyComboBox.currentData()
        if data:
            return str(data)
        return self.surveyComboBox.currentText().strip()

    def start_or_stop_recording(self):
        self.record()  # This will start OR stop recording, whichever is not currently happening
        if self.sender().isChecked():
            if survey_url := self.current_survey_url():
                webbrowser.open(survey_url, new=1, autoraise=False)
            port_msg = "DreamReportStarted"
        else:
            port_msg = "DreamReportStopped"
        # button_label = self.sender().text()
        portcode = self.portcodes[port_msg]
        self.send_event_marker(portcode, port_msg)

    @QtCore.pyqtSlot()
    def pick_color(self):
        color = QtWidgets.QColorDialog.getColor()
        if color.isValid():
            r, g, b, _ = color.getRgb()
            self.set_blink_color(r, g, b)
            # pixmap = QtGui.QPixmap(16, 16)
            # pixmap.fill(color)
            # self.colorpickerAction.setIcon(QtGui.QIcon(pixmap))

    # @QtCore.pyqtSlot()
    def handle_freq_change(self, freq: float) -> None:
        """Takes frequency as a float, coming from user selection. In Hz."""
        self.bstick_blink_freq = freq
        # portcode = self.portcodes["blink"]
        # port_msg = f"Set color: [{color}]"
        # self.send_event_marker(portcode, port_msg)

    @QtCore.pyqtSlot()
    def stimulate_audio(self):
        self.wavplayer.play()

    @QtCore.pyqtSlot()
    def stop_audio(self):
        """Stop the currently playing/looping cue."""
        self.wavplayer.stop()

    def update_audio_loop(self, enabled: bool) -> None:
        """Set the cue loop count from the loop checkbox."""
        loop_count = QtMultimedia.QSoundEffect.Infinite if enabled else 1
        self.wavplayer.setLoopCount(loop_count)

    def on_cue_playing_change(self) -> None:
        """Update the cue status indicator when playback starts/stops."""
        if self.wavplayer.isPlaying():
            looping = self.loopCheckBox.isChecked()
            self.cueStatusLabel.setText(
                "\U0001f501 looping" if looping else "▶ playing"
            )
            self.cueStatusLabel.setStyleSheet("color: red; font-weight: bold;")
        else:
            self.cueStatusLabel.setText("■ stopped")
            self.cueStatusLabel.setStyleSheet("")

    @QtCore.pyqtSlot()
    def stimulate_visual(self):
        from time import sleep

        black = [0, 0, 0] * 32
        freq = self.bstick_blink_freq
        self.bstick.set_led_data(channel=0, data=self.bstick_led_data)
        sleep(freq)
        self.bstick.set_led_data(channel=0, data=black)
        # portcode = self.portcodes["blink"]
        # port_msg = f"Set color: [{color}]"
        # self.send_event_marker(portcode, port_msg)

    def open_note_marker_dialogue(self):
        text, ok = QtWidgets.QInputDialog.getText(
            self, "Text Input Dialog", "Custom note (no commas):"
        )
        # self.subject_id.setValidator(QtGui.QIntValidator(0, 999)) # must be a 3-digit number
        if ok:  # True of OK button was hit, False otherwise (cancel button)
            portcode = self.portcodes["Note"]
            port_msg = f"Note [{text}]"
            self.send_event_marker(portcode, port_msg)

    @QtCore.pyqtSlot()
    def handle_left2right_button(self):
        self.rightList.addItem(self.leftList.takeItem(self.leftList.currentRow()))
        self.rightList.sortItems()

    @QtCore.pyqtSlot()
    def handle_right2left_button(self):
        self.leftList.addItem(self.rightList.takeItem(self.rightList.currentRow()))
        self.leftList.sortItems()

    def update_audio_source(self):
        """Catches signal from audio file lineedit/browser."""
        lineEdit = self.sender()
        filepath = lineEdit.text()
        # assert Path(filepath).exists() and Path(filepath).suffix == ".wav"
        content = QtCore.QUrl.fromLocalFile(filepath)
        # can do the assrtions here with content.exists()
        self.wavplayer.setSource(content)

    def update_audio_volume(self, value: float) -> None:
        """Method catching signals from audio stimulation volume spinbox
        NOT noise, audio cues.

        value should be a float from the spinbox
        """
        self.wavplayer.setVolume(value)  # 0 - 1
        # self.log_info_msg(f"VolumeSet - Cue {float_volume}")

    def update_noise_volume(self, value: float) -> None:
        """Method catching signals from audio stimulation volume spinbox
        NOT noise, audio cues.

        value should be a float from the spinbox
        """
        # self.noiseplayer.setVolume(value)  # 0 - 1
        # self.log_info_msg(f"VolumeSet - Noise {float_volume}")
        self.noise_stream_volume = value

    def change_input_gain(self, value):
        self.show_error_popup(
            "Not implemented yet",
            "This should eventually allow for increasing mic input volume.",
        )

    def closeEvent(self, event):
        """customize exit.
        closeEvent is a default method used in pyqt to close, so this overrides it
        """
        response = QtWidgets.QMessageBox.question(
            self, "Quit", "Do you want to quit/close SMACC?"
        )
        if response == QtWidgets.QMessageBox.Yes:
            if self.noise_stream:
                self.noise_stream.close()
            self.log_info_msg("Program closed")
            event.accept()
            # self.closed.emit()
            # sys.exit()
        else:
            event.ignore()
