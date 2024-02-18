"""
Initialize a new session
and open the main interface.
"""
import os
from pathlib import Path
import sys
import time
import random
import logging
import warnings
import webbrowser

from pylsl import StreamInfo, StreamOutlet, local_clock
from PyQt5 import QtWidgets, QtGui, QtCore, QtMultimedia

from smacc import utils
from .config import *


try:
    from blinkstick import blinkstick
except:
    blinkstick = None


# Define directories.
data_directory = utils.get_data_directory()
logs_directory = data_directory / "logs"
cues_directory = data_directory / "cues"
noise_directory = data_directory / "noise"
dreams_directory = data_directory / "dreams"
logs_directory.mkdir(exist_ok=True)
cues_directory.mkdir(exist_ok=True)
noise_directory.mkdir(exist_ok=True)
dreams_directory.mkdir(exist_ok=True)


#########################################################
#########    Create some custom PyQt classes    #########
#########################################################

class BorderWidget(QtWidgets.QFrame):
    """thing to make a border https://stackoverflow.com/a/7351943"""
    def __init__(self, *args):
        super(BorderWidget, self).__init__(*args)
        self.setStyleSheet("background-color: rgb(0,0,0,0); margin:0px; border:4px solid rgb(0, 0, 0); border-radius: 25px; ")

class SubjectSessionRequest(QtWidgets.QDialog):
    """A popup window that pops up once during initialization
    to get subject and session IDs from the user.
    """
    def __init__(self, parent=None):
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
        self.subject_id.setValidator(QtGui.QIntValidator(0, 999))  # Require a 3-digit number
        self.session_id.setValidator(QtGui.QIntValidator(0, 999))  # Require a 3-digit number
        # Create buttons to accept values or cancel.
        buttonBox = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            self
        )
        buttonBox.accepted.connect(self.accept)
        buttonBox.rejected.connect(self.reject)
        # Put everything in a layout.
        layout = QtWidgets.QFormLayout(self)
        layout.addRow("Subject ID", self.subject_id)
        layout.addRow("Session ID", self.session_id)
        layout.addWidget(buttonBox)

    def getInputs(self):
        """Return user-specified subject and session IDs as integers."""
        subject_int = int(self.subject_id.text())
        session_int = int(self.session_id.text())
        return subject_int, session_int


def showAboutPopup():
    """'About SMACC' popup window."""
    text = (
        f"Sleep Manipulation and Communication Clickything\n"
        f"version: v{VERSION}"
        f"https://github.com/remrama/smacc\n"
    )
    win = QtWidgets.QMessageBox()
    win.setWindowTitle("About SMACC")
    win.setIcon(QtWidgets.QMessageBox.Information)
    win.setStandardButtons(QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Close)
    win.setDefaultButton(QtWidgets.QMessageBox.Close)
    win.setInformativeText(text)
    # win.setDetailedText("detailshere")
    # win.setStyleSheet("QLabel{min-width:500 px; font-size: 24px;} QPushButton{ width:250px; font-size: 18px; }");
    # win.setGeometry(200, 150, 100, 40)
    win.exec_()



#####################################
#########    Main window    #########
#####################################

class SmaccWindow(QtWidgets.QMainWindow):
    """Main interface"""
    def __init__(self, subject_id, session_id):
        super().__init__()

        self.n_report_counter = 0 # cumulative counter for determining filenames

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
        self.noise_directory = noise_directory

        self.extract_cue_names()
        self.preload_cues()

        self.init_blinkstick()
        self.init_audio_stimulation_setup()
        self.init_noise_player()
        self.init_recorder()

        self.init_main_window()

        init_msg = "Opened SMACC v" + VERSION
        self.log_info_msg(init_msg)

        self.init_lsl_stream()

    def showErrorPopup(self, short_msg, long_msg=None):
        self.log_info_msg("ERROR")
        win = QtWidgets.QMessageBox()
        win.setIcon(QtWidgets.QMessageBox.Warning)
        # win.setIconPixmap(QtGui.QPixmap("./img/fish.ico"))
        win.setText(short_msg)
        if long_msg is not None:
            win.setInformativeText(long_msg)
        win.setWindowTitle("Error")
        win.exec_()
    # def showErrorPopup(self, short_msg):
    #     em = QtWidgets.QErrorMessage()
    #     em.showMessage(short_msg)
    #     em.exec_()

    def log_info_msg(self, msg):
        """wrapper just to make sure msg goes to viewer too
        (should probably split up)
        """
        # log the message
        self.logger.info(msg)
        
        # print message to the GUI viewer box thing
        item = self.logviewList.addItem(time.strftime("%H:%M:%S") + " - " + msg)
        self.logviewList.repaint()
        self.logviewList.scrollToBottom()
        # item = pg.QtGui.QListWidgetItem(msg)
        # if warning: # change txt color
        #     item.setForeground(pg.QtCore.Qt.red)
        # self.eventList.addItem(item)
        # self.eventList.update()

    def init_lsl_stream(self, stream_id="myuidw43536"):
        self.info = StreamInfo("MyMarkerStream", "Markers", 1, 0, "string", stream_id)
        self.outlet = StreamOutlet(self.info)

    def send_event_marker(self, portcode, port_msg):
        """Wrapper to avoid rewriting if not None a bunch
        to make sure the msg also gets logged to output file and gui
        """
        self.outlet.push_sample([str(portcode)])
        log_msg = f"{port_msg} - portcode {portcode}"
        self.log_info_msg(log_msg)

    def init_logger(self):
        """initialize logger that writes to a log file"""
        path_name = f"sub-{self.subject:03d}_ses-{self.session:03d}_smacc-{VERSION}.log"
        log_path = logs_directory / path_name
        self.logger = logging.getLogger("smacc")
        self.logger.setLevel(logging.DEBUG)
        # open file handler to save external file
        write_mode = "w" if self.subject == DEVELOPMENT_ID else "x"
        fh = logging.FileHandler(log_path, mode=write_mode, encoding="utf-8")
        fh.setLevel(logging.DEBUG)  # this determines what gets written to file
        # create formatter and add it to the handlers
        formatter = logging.Formatter(
            fmt="%(asctime)s.%(msecs)03d, %(levelname)s, %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S")
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

        aboutAction = QtWidgets.QAction(self.style().standardIcon(getattr(QtWidgets.QStyle, "SP_MessageBoxInformation")), "&About", self)
        aboutAction.setStatusTip("About SMACC")
        aboutAction.triggered.connect(showAboutPopup)

        quitAction = QtWidgets.QAction(self.style().standardIcon(getattr(QtWidgets.QStyle, "SP_BrowserStop")), "&Quit", self)
        quitAction.setShortcut("Ctrl+Q")
        quitAction.setStatusTip("Quit/close interface")
        quitAction.triggered.connect(self.close)  # close goes to closeEvent

        menuBar = self.menuBar()
        # menuBar.setNativeMenuBar(False)  # needed for pyqt5 on Mac
        helpMenu = menuBar.addMenu("&Help")
        helpMenu.addAction(aboutAction)
        helpMenu.addAction(quitAction)

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

        # Visual device picker: QComboBox signal --> update device slot
        available_blinksticks_dropdown = QtWidgets.QComboBox()
        available_blinksticks_dropdown.setStatusTip("Select visual stimulation device")
        available_blinksticks_dropdown.currentTextChanged.connect(self.set_new_blinkstick)
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
        freqSpinBox.setStatusTip("Pick BlinkStick blink frequency (how long the light will stay on in seconds).")
        # freqSpinBox.setRange(0, 100)
        freqSpinBox.setMinimum(0)
        freqSpinBox.setMaximum(100)
        freqSpinBox.setPrefix("Blink length: ")
        freqSpinBox.setSuffix(" seconds")
        freqSpinBox.setSingleStep(1)
        freqSpinBox.valueChanged.connect(self.handleFreqChange)
        # freqSpinBox.textChanged.connect(self.value_changed_str)
        freqSpinBox.setValue(self.bstick_blink_freq)

        # Compile them into a vertical layout
        visualstimLayout = QtWidgets.QFormLayout()
        visualstimLayout.addRow("Select visual stimulation device: ", available_blinksticks_dropdown)
        visualstimLayout.addRow("Select visual stimulation color: ", colorpickerButton)
        visualstimLayout.addRow(blinkButton)

        ########################################################################
        # AUDIO STIMULATION WIDGET
        ########################################################################

        # Audio stimulation device picker: QComboBox signal --> update device slot
        available_speakers_dropdown = QtWidgets.QComboBox()
        available_speakers_dropdown.setStatusTip("Select audio stimulation device")
        available_speakers_dropdown.setPlaceholderText("No speaker devices were found.")
        # inputIcon = self.style().standardIcon(getattr(QtWidgets.QStyle, "SP_DialogNoButton"))
        available_speakers_dropdown.currentTextChanged.connect(self.set_new_speakers)
        self.available_speakers_dropdown = available_speakers_dropdown
        self.refresh_available_speakers()

        wavselectorLayout = QtWidgets.QHBoxLayout()
        wavselectorLabel = QtWidgets.QLabel("File:", self)
        wavselectorEdit = QtWidgets.QLineEdit(self)
        wavselectorButton = QtWidgets.QPushButton("Browse", self)
        wavselectorButton.clicked.connect(self.open_wav_selector)
        wavselectorLayout.addWidget(wavselectorLabel)
        wavselectorLayout.addWidget(wavselectorEdit)
        wavselectorLayout.addWidget(wavselectorButton)
        wavselectorEdit.textChanged.connect(self.update_audio_source)  # For programmatic changes
        # wavselectorEdit.textEdited.connect(self.update_audio_source)  # For user changes
        wavselectorEdit.editingFinished.connect(self.update_audio_source)  # For user changes
        self.wavselectorEdit = wavselectorEdit

        # Audio volume selector: QDoubleSpinBox signal --> update audio volume slot
        volumeSpinBox = QtWidgets.QDoubleSpinBox(self)
        volumeSpinBox.setStatusTip("Select volume of audio stimulation.")
        # volumeSpinBox.setRange(0, 1)
        volumeSpinBox.setMinimum(0)
        volumeSpinBox.setMaximum(1)  # Currently using QSoundEffect which only allows 0-1
        # volumeSpinBox.setPrefix("Volume: ")
        volumeSpinBox.setSuffix(" dB")
        volumeSpinBox.setSingleStep(0.01)
        volumeSpinBox.valueChanged.connect(self.update_audio_volume)
        volumeSpinBox.setValue(0.2)

        # Play button: QPushButton signal --> play function
        playButton = QtWidgets.QPushButton("Play soundfile", self)
        playButton.setStatusTip("Play the selected sound file.")
        # playButton.setIcon(QtGui.QIcon("./color.png"))
        playButton.clicked.connect(self.stimulate_audio)

        # Compile them into a vertical layout
        audiostimLayout = QtWidgets.QFormLayout()
        audiostimLayout.addRow("Select audio stimulation device: ", available_speakers_dropdown)
        audiostimLayout.addRow("Select audio stimulation volume: ", volumeSpinBox)
        audiostimLayout.addRow(wavselectorLayout)
        audiostimLayout.addRow(playButton)

        # #### audio device list menu
        # audioMenu = menuBar.addMenu("&Audio")
        # inputMenu = audioMenu.addMenu(inputIcon, "&Input device")
        # # outputMenu = audioMenu.addMenu(QtGui.QIcon("./img/output.png"), "&Output device")

        ########################################################################
        # AUDIO RECORDING WIDGET
        ########################################################################

        # Microphone device picker: QComboBox signal --> update device slot
        available_microphones_dropdown = QtWidgets.QComboBox()
        available_microphones_dropdown.setStatusTip("Select microphone")
        available_microphones_dropdown.setPlaceholderText("No microphones were found.")
        available_microphones_dropdown.currentTextChanged.connect(self.set_new_microphone)
        self.available_microphones_dropdown = available_microphones_dropdown
        self.refresh_available_microphones()

        microphoneLayout = QtWidgets.QFormLayout()
        microphoneLayout.addRow("Select microphone: ", available_microphones_dropdown)

        ########################################################################
        # NOISE PLAYER WIDGET
        ########################################################################

        # Noise device picker: QComboBox signal --> update device slot
        available_noisespeakers_dropdown = QtWidgets.QComboBox()
        available_noisespeakers_dropdown.setStatusTip("Select speakers for noise")
        available_noisespeakers_dropdown.currentTextChanged.connect(self.set_new_noisespeakers)
        self.available_noisespeakers_dropdown = available_noisespeakers_dropdown
        self.refresh_available_noisespeakers()

        # Noise color picker: QComboBox signal --> update noise color parameter
        available_noisecolors = ["white", "pink", "brown"]
        available_noisecolors_dropdown = QtWidgets.QComboBox()
        available_noisecolors_dropdown.setStatusTip("Select speakers for noise")
        available_noisecolors_dropdown.currentTextChanged.connect(self.set_new_noisecolor)
        # available_noisecolors_dropdown.addItems(available_noisecolors)
        for color in available_noisecolors:
            pixmap = QtGui.QPixmap(16, 16)
            pixmap.fill(QtGui.QColor(color))
            icon = QtGui.QIcon(pixmap)
            available_noisecolors_dropdown.addItem(icon, color)
        self.available_noisecolors_dropdown = available_noisecolors_dropdown

        # Noise volume selector: QDoubleSpinBox signal --> update audio volume slot
        noisevolumeSpinBox = QtWidgets.QDoubleSpinBox(self)
        noisevolumeSpinBox.setStatusTip("Select volume of noise.")
        # noisevolumeSpinBox.setRange(0, 1)
        noisevolumeSpinBox.setMinimum(0)
        noisevolumeSpinBox.setMaximum(1)  # Currently using QSoundEffect which only allows 0-1
        # noisevolumeSpinBox.setPrefix("Volume: ")
        noisevolumeSpinBox.setSuffix(" dB")
        noisevolumeSpinBox.setSingleStep(0.01)
        noisevolumeSpinBox.valueChanged.connect(self.update_noise_volume)
        noisevolumeSpinBox.setValue(0.2)

        # Play button: QPushButton signal --> play function
        playnoiseButton = QtWidgets.QPushButton("Play noise", self)
        playnoiseButton.setStatusTip("Play the selected noise color.")
        # playButton.setIcon(QtGui.QIcon("./color.png"))
        playnoiseButton.clicked.connect(self.play_noise)
        # Stop button: QPushButton signal --> stop function
        stopnoiseButton = QtWidgets.QPushButton("Stop noise", self)
        stopnoiseButton.setStatusTip("Stop the selected noise color.")
        stopnoiseButton.clicked.connect(self.stop_noise)

        playstopLayout = QtWidgets.QHBoxLayout()
        playstopLayout.addWidget(playnoiseButton)
        playstopLayout.addWidget(stopnoiseButton)

        noiseLayout = QtWidgets.QFormLayout()
        noiseLayout.addRow("Select speakers: ", available_noisespeakers_dropdown)
        noiseLayout.addRow("Select noise color: ", available_noisecolors_dropdown)
        noiseLayout.addWidget(noisevolumeSpinBox)
        noiseLayout.addRow(playstopLayout)

        ########################################################################
        # COMMON EVENT MARKERS WIDGET
        ########################################################################

        common_events = {
            "Awakening": "Mark an awakening (shortcut 1)",
            "LRLR": "Mark a left-right-left-right lucid signal",
            "Sleep onset": "Mark observed sleep onset",
            "Lighs off": "Mark the beginning of sleep session",
            "Lights on": "Mark the end of sleep session",
            "Note": "Open a text box and timestamp a note.",
        }

        eventsLayout = QtWidgets.QFormLayout()
        for i, (event, tip) in enumerate(common_events.items()):
            shortcut = str(i + 1)
            label = f"{event} ({shortcut})"
            button = QtWidgets.QPushButton(label, self)
            button.setStatusTip(tip)
            button.setShortcut(shortcut)
            # button.setCheckable(False)
            button.clicked.connect(self.handle_event_button)
            eventsLayout.addRow(button)

        ########################################################################
        # LOG VIEWER WIDGET
        ########################################################################

        # Events log viewer --> gets updated when events are logged
        logviewLabel = QtWidgets.QLabel("Event log", self)
        logviewLabel.setAlignment(QtCore.Qt.AlignCenter)
        logviewList = QtWidgets.QListWidget()
        logviewList.setAutoScroll(True)
        # logviewList.setGeometry(20,20,100,700)
        self.logviewList = logviewList

        logviewLayout = QtWidgets.QGridLayout()
        logviewLayout.addWidget(logviewLabel, 0, 0, 1, 1)
        logviewLayout.addWidget(logviewList, 2, 0, 2, 1)

        ########################################################################
        # COMPILE ALL WIDGETS INTO CENTRAL WIDGET
        ########################################################################

        # Central widget and layout
        central_layout = QtWidgets.QHBoxLayout()
        central_layout.addLayout(visualstimLayout)
        central_layout.addLayout(audiostimLayout)
        central_layout.addLayout(microphoneLayout)
        central_layout.addLayout(noiseLayout)
        central_layout.addLayout(eventsLayout)
        central_layout.addLayout(logviewLayout)
        central_widget = QtWidgets.QWidget()
        central_widget.setContentsMargins(5, 5, 5, 5)
        central_widget.move(100, 100)  # Change initial startup position
        central_widget.setLayout(central_layout)
        self.setCentralWidget(central_widget)
        # self.main_layout = main_layout

        # # Add the LightSwitchWidget to the main window
        # self.lightSwitch = LightSwitchWidget(self)
        # self.lightSwitch.switchToggled.connect(self.handleLightSwitch)

        # # Add VisualStimController as a popup
        # self.visual_stim_controller = VisualStimController(self)
        # # Connect switch events (signals) to functions in smacc main window (slots)
        # # self.visual_stim_controller.flicker_checkbox.toggled.connect(self.onClicked)
        # # self.freq_scroller.connect()
        # # self.brightness_scroller.connect()

        # create central widget for holding grid layout
        self.init_CentralWidget()

        # # main window stuff
        # xywh = (50, 100, self.winWidth, self.winHeight) # xloc, yloc, width, height
        # self.setGeometry(*xywh)
        # self.setMinimumSize(300, 200)    
        self.setWindowTitle("SMACC")
        windowIcon = self.style().standardIcon(getattr(QtWidgets.QStyle, "SP_ToolBarHorizontalExtensionButton"))
        self.setWindowIcon(windowIcon)
        # self.openAction = QAction(QIcon(":file-open.svg"), "&Open...", self)
        # self.setGeometry(100, 100, 600, 400)
        self.resize(1200, 500)
        self.show()

    def handle_event_button(self):
        sender = self.sender()
        text = sender.text()
        port_codes = {
            "Awakening": 123,
            "LRLR": 234,
            "LR": 345,
        }
        code = port_codes[text]
        self.send_event_marker(code, text)

    def open_wav_selector(self):
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select a File", 
            "C:\\Users\\malle\\Desktop\\", 
            "Audio (*.wav)"
        )
        if filename:
            path = Path(filename)
            self.wavselectorEdit.setText(str(path))

    def set_new_noisecolor(self, text):
        """text is the noise color"""
        filepath = Path(".") / text
        # content = QtCore.QUrl.fromLocalFile(str(filepath))
        # self.noiseplayer.setSource(content)

        print(f"New noise color {text} selected!")

    def set_new_speakers(self, text):
        print(f"New speakers {text} selected!")

    def set_new_noisespeakers(self, text):
        print(f"New noise speakers {text} selected!")

    def set_new_microphone(self, text):
        print(f"New microphone {text} selected!")

    ############################################################################
    # Functions for refreshing/searching for connected devices (inputs and outputs)
    ############################################################################

    def refresh_available_noisespeakers(self):
        """
        Populate the audio stimulation device selection menu with currently
        available speakers.

        Code is identical to refresh_available_speakers
        except updates/populates the noise device list instead of audio stim

        seealso: refresh_available_speakers
        """
        self.available_noisespeakers_dropdown.clear()
        devices = QtMultimedia.QAudioDeviceInfo.availableDevices(QtMultimedia.QAudio.AudioOutput)
        devices = [d for d in devices if d.realm() != "default"]
        for device in devices:
            device_name = device.deviceName()
            device_realm = device.realm()  # This differentiates the duplicate of default output
            device_str = f"{device_name} [{device_realm}]"
            self.available_noisespeakers_dropdown.addItem(device_str)
        if devices:
            self.available_noisespeakers_dropdown.setCurrentIndex(0)
        else:
            self.show_popup_warning("No audio devices found.")

    def refresh_available_speakers(self):
        """
        Populate the audio stimulation device selection menu with currently
        available speakers.
        seealso: refresh_available_noisespeakers
        """
        self.available_speakers_dropdown.clear()
        devices = QtMultimedia.QAudioDeviceInfo.availableDevices(QtMultimedia.QAudio.AudioOutput)
        devices = [d for d in devices if d.realm() != "default"]
        for device in devices:
            device_name = device.deviceName()
            device_realm = device.realm()  # This differentiates the duplicate of default output
            device_str = f"{device_name} [{device_realm}]"
            self.available_speakers_dropdown.addItem(device_str)
        if devices:
            self.available_speakers_dropdown.setCurrentIndex(0)
        else:
            self.show_popup_warning("No audio devices found.")

    def refresh_available_microphones(self):
        """
        Populate the microphone dropdown menu with all available audio input devices.
        """
        self.available_microphones_dropdown.clear()
        devices = QtMultimedia.QAudioDeviceInfo.availableDevices(QtMultimedia.QAudio.AudioInput)
        # devices = self.recorder.audioInputs()
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
            self.show_popup_warning("No microphones found.")
        # # devices = sd.query_devices()
        # # input_devices  = { d["name"]: i for i, d in enumerate(devices) if d["max_input_channels"]>0 }
        # # output_devices = { d["name"]: i for i, d in enumerate(devices) if d["max_output_channels"]>0 }
        # # for k, v in input_devices.values():
        # for i, dev in enumerate(devices):
        #     if dev["max_input_channels"] > 0:
        #         action = QtWidgets.QAction(QtGui.QIcon("./img/1F399_color.png"), dev["name"], self)
        #         action.setStatusTip("Set "+dev["name"]+" as input device")
        #         action.triggered.connect(self.set_audio_device)
        #         inputMenu.addAction(action)
        #     if dev["max_output_channels"] > 0:
        #         action = QtWidgets.QAction(QtGui.QIcon("./img/1F4FB_color.png"), dev["name"], self)
        #         action.setStatusTip("Set "+dev["name"]+" as output device")
        #         action.triggered.connect(self.set_audio_device)
        #         outputMenu.addAction(action)

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
            self.show_popup_warning("Use of visual stimulation requires `blinkstick` Python package. Unable to search for devices.")
        else:
            devices = blinkstick.find_all()
        # Add each device to the dropdown menu
        for i, d in enumerate(devices):
            product_name = d.device.product_name
            serial_number = d.device.serial_number
            version_number = d.device.version_number
            device_str = f"{product_name} v{version_number} (Serial No. {serial_number})"
            self.available_blinksticks_dropdown.addItem(device_str)
        if devices:
            self.available_blinksticks_dropdown.setCurrentIndex(0)
        else:
            self.show_popup_warning("No BlinkSticks found.")

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
                    self.recorder.setAudioInput(new_device_name)
                    # menu_item.setChecked(True) # happens by default
                else: # need to uncheck the one that WAS checked, so just hit all of them
                    menu_item.setChecked(False)
            # if new_device_name == self.recorder.audioInput():
            #     action.setChecked(True)
            # self.log_info_msg(f"INPUT DEVICE UPDATE {new_device_name}")
            # self.showErrorPopup("Not implemented yet")
        elif not checked:
            # this is when someone tries to "unselect" an input.
            # can't be allowed, but pyqt will uncheck it, so recheck it
            self.sender().setChecked(True) # recheck it
            # for menu_item in self.input_menu_items:
            #     if menu_item.iconText() == self.sender().text():
            #         menu_item.setChecked(True)

    def init_blinkstick(self):
        default_freq = 1.0
        default_rgb = (0, 0, 0)
        r, g, b = default_rgb
        led_data = [g, r, b] * 32
        self.bstick_led_data = led_data
        self.bstick_blink_freq = default_freq
        # Draw button/icon/pixmap to show default color

    def init_audio_stimulation_setup(self):
        """Create media player for cue files."""
        player = QtMultimedia.QSoundEffect()
        # Default settings
        # player.setVolume(0)  # 0 to 1 -- Gets set already when parameter selector is made
        player.setLoopCount(1)
        # player.playingChanged.connect(self.on_cuePlayingChange)
        self.wavplayer = player

    def init_noise_player(self):
        """Create media player for noise files."""
        player = QtMultimedia.QSoundEffect()
        # player.setVolume(0)  # 0 to 1 -- Gets set already when parameter selector is made
        player.setLoopCount(QtMultimedia.QSoundEffect.Infinite)
        # player.playingChanged.connect(self.on_cuePlayingChange)
        self.noiseplayer = player

    def play_noise(self):
        self.noiseplayer.play()

    def stop_noise(self):
        self.noiseplayer.stop()

    def init_recorder(self):
        """initialize the recorder
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
        self.recorder = QtMultimedia.QAudioRecorder()
        self.recorder.setEncodingSettings(settings)
        # Connect stateChange to adjust color of button to indicate status
        self.recorder.stateChanged.connect(self.recorder_update_status)

    def record(self):
        state = self.recorder.state() # recording / paused / stopped
        status = self.recorder.status() # this has more options, like unavailable vs inactive
        # if status == QtMultimedia.QMediaRecorder.RecordingStatus:
        if state == QtMultimedia.QMediaRecorder.StoppedState:
            ### start a new recording
            # generate filename
            self.n_report_counter += 1
            basename = f"sub-{self.subject:03d}_ses-{self.session:03d}_report-{self.n_report_counter:02d}.wav"
            export_fname = os.path.join(dreams_directory, basename)
            self.recorder.setOutputLocation(QtCore.QUrl.fromLocalFile(export_fname))
            self.recorder.record()
            # # filename = 'https://www.pachd.com/sfx/camera_click.wav'
            # # fullpath = QtCore.QDir.current().absoluteFilePath(filename) 
        elif state == QtMultimedia.QMediaRecorder.RecordingState:
            self.recorder.stop()

    @QtCore.pyqtSlot()
    def on_cuePlayingChange(self):
        """To uncheck the cue button if something stops on its own.
        and send port message of start/stop"""
        current_volume = self.sender().volume()
        filepath = self.sender().source().toString()
        cue_name = os.path.basename(filepath).split(".")[0]
        if self.sender().isPlaying():
            portcode = self.portcodes[cue_name]
            action = "Started"
        else:
            self.cueButton.setChecked(False) # so it unchecks if player stops naturally
            portcode = self.portcodes["CueStopped"]
            action = "Stopped"
        port_msg = f"Cue{action}-{cue_name} - Volume {current_volume}" 
        self.send_event_marker(portcode, port_msg)

    def recorder_update_status(self, state):
        if state == QtMultimedia.QMediaRecorder.StoppedState:
            self.logviewList.setStyleSheet("border: 0px solid red;")
        elif state == QtMultimedia.QMediaRecorder.RecordingState:
            self.logviewList.setStyleSheet("border: 3px solid red;")

    def handleDreamReportButton(self):
        self.record()  # This will start OR stop recording, whichever is not currently happening
        if self.sender().isChecked():
            if SURVEY_URL is not None:
                webbrowser.open(SURVEY_URL, new=0, autoraise=True)
            port_msg = "DreamReportStarted"
        else:
            port_msg = "DreamReportStopped"
        # button_label = self.sender().text()
        portcode = self.portcodes[port_msg]
        self.send_event_marker(portcode, port_msg)

    # def preload_biocals(self):
    #     self.biocals_player = QtMultimedia.QMediaPlayer()
    #     self.playlist = QtMultimedia.QMediaPlaylist(self.biocals_player)
    #     self.playlist.setPlaybackMode(QtMultimedia.QMediaPlaylist.Sequential) #Sequential/CurrentItemOnce
    #     for biocal_str in self.biocals_order:
    #         biocal_path = os.path.join(self.biocals_directory, f"{biocal_str}.mp3")
    #         url = QtCore.QUrl.fromLocalFile(biocal_path)
    #         content = QtMultimedia.QMediaContent(url)
    #         self.playlist.addMedia(content)
    #     self.biocals_player.setPlaylist(self.playlist)
    #     self.playlist.currentIndexChanged.connect(self.on_biocalsPlaylistIndexChange)
    # def play_biocals(self):
    #     self.biocals_player.setVolume(50) # 0-100 # 0 to 1
    #     self.biocals_player.play()
    # @QtCore.pyqtSlot()
    # def on_biocalsPlaylistIndexChange(self):
    #     current_index = self.sender().currentIndex()
    #     if 0 < current_index < len(self.biocals_order)-1:
    #         biocal_str = self.biocals_order[current_index]
    #         portcode = self.portcodes[f"biocals-{biocal_str}"]
    #         msg = f"BiocalStarted-{biocal_str}"
    #         self.send_event_marker(portcode, msg)
    #     else:
    #         self.biocalsButton.setChecked(False)

    def extract_cue_names(self):
        self.cue_name_list = []
        for cue_basename in os.listdir(self.cues_directory):
            if cue_basename.endswith(".wav"):
                assert cue_basename.count(".") == 1
                cue_name = cue_basename.split(".")[0]
                assert cue_name not in self.portcodes, "No duplicate cue names"
                existing_portcodes = list(self.portcodes.values())
                portcode = max(existing_portcodes) + 1
                assert portcode < 245
                self.portcodes[cue_name] = int(portcode)
                self.cue_name_list.append(cue_name)

    def preload_cues(self):
        self.playables = {}
        for cue_name in self.cue_name_list:
            cue_basename = f"{cue_name}.wav"
            cue_fullpath = os.path.join(self.cues_directory, cue_basename)
            content = QtCore.QUrl.fromLocalFile(cue_fullpath)
            player = QtMultimedia.QSoundEffect()
            player.setSource(content)
            player.setVolume(DEFAULT_VOLUME) # 0 to 1
            ### these might be easier to handle in a Qmediaplaylist and then indexing like track numbers
            # player.setLoopCount(1) # QtMultimedia.QSoundEffect.Infinite
            # Connect to a function that gets called when it starts or stops playing.
            # Only need it for the "stop" so it unchecks the cue button when not manually stopped.
            player.playingChanged.connect(self.on_cuePlayingChange)
            self.playables[cue_name] = player

        # noise player
        noise_basename = "pink.wav"
        noise_fullpath = os.path.join(self.noise_directory, noise_basename)
        noise_content = QtCore.QUrl.fromLocalFile(noise_fullpath)
        ## this should prob be a mediaplayer/playlist which uses less resources
        self.noisePlayer = QtMultimedia.QSoundEffect()
        self.noisePlayer.setSource(noise_content)
        self.noisePlayer.setVolume(DEFAULT_VOLUME) # 0 to 1
        self.noisePlayer.setLoopCount(QtMultimedia.QSoundEffect.Infinite)
        # Connect to a function that gets called when it starts or stops playing.
        # Only need it for the "stop" so it unchecks the cue button when not manually stopped.
        # self.noisePlayer.playingChanged.connect(self.on_cuePlayingChange)

    @QtCore.pyqtSlot()
    def handleNoiseButton(self):
        if self.noiseButton.isChecked():
            # self.noisePlayer.setLoopCount(QtMultimedia.QSoundEffect.Infinite)
            self.noisePlayer.play()
            msg = "NoiseStarted"
        else: # not checked
            self.noisePlayer.stop()
            msg = "NoiseStopped"
        self.send_event_marker(self.portcodes[msg], msg)

    @QtCore.pyqtSlot()
    def handleCueButton(self):
        if self.cueButton.isChecked():
            # #### play selected item
            # selected_item = self.rightList.currentItem()
            # if selected_item is not None:
            #     cue_basename = selected_item.text()
            #     portcode = self.portcodes[cue_basename]
            #     port_msg = "CUE+" + cue_basename
            #     self.send_event_marker(portcode, port_msg)
            #     self.playables[cue_basename].play()
            #### play random
            n_list_items = self.rightList.count()
            if n_list_items > 0:
                selected_item = random.choice(range(n_list_items))
                cue_name = self.rightList.item(selected_item).text()
                self.playables[cue_name].play()
        else: # stop
            for k, v in self.playables.items():
                if v.isPlaying():
                    v.stop()

    @QtCore.pyqtSlot()
    def pick_color(self):
        color = QtWidgets.QColorDialog.getColor()
        if color.isValid():
            self.bstick_hexcode = color.name()
            self.bstick_rgb = color.getRgb()
            ## Not sure why, but the blinkstick.set_led_data expects R and G reversed
            # Create a sequence 96 values
            # sequences of GRB values (RGB with R/G reversed), 3 for each of 32 LEDs
            r, g, b, a = self.bstick_rgb
            led_data = [g, r, b] * 32
            self.bstick_led_data = led_data
            # pixmap = QtGui.QPixmap(16, 16)
            # pixmap.fill(color)
            # self.colorpickerAction.setIcon(QtGui.QIcon(pixmap))

    # @QtCore.pyqtSlot()
    def handleFreqChange(self, freq):
        """Takes frequency as a float, coming from user selection. In Hz"""
        self.bstick_blink_freq = freq
        # portcode = self.portcodes["blink"]
        # port_msg = f"Set color: [{color}]"
        # self.send_event_marker(portcode, port_msg)

    @QtCore.pyqtSlot()
    def stimulate_audio(self):
        self.wavplayer.play()

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
        text, ok = QtWidgets.QInputDialog.getText(self, "Text Input Dialog", "Custom note (no commas):")
        # self.subject_id.setValidator(QtGui.QIntValidator(0, 999)) # must be a 3-digit number
        if ok: # True of OK button was hit, False otherwise (cancel button)
            portcode = self.portcodes["Note"]
            port_msg = f"Note [{text}]"
            self.send_event_marker(portcode, port_msg)

    @QtCore.pyqtSlot()
    def handleLeft2RightButton(self):
        self.rightList.addItem(self.leftList.takeItem(self.leftList.currentRow()))
        self.rightList.sortItems()

    @QtCore.pyqtSlot()
    def handleRight2LeftButton(self):
        self.leftList.addItem(self.rightList.takeItem(self.rightList.currentRow()))
        self.leftList.sortItems()

    # def generate_cue_button(self, button_label):
    #     """run this separate outside of overall button
    #     creation because otherwise there is some persistent
    #     with the variables??
    #     """
    #     b = QtWidgets.QPushButton(button_label, self)
    #     help_string = self.legend[button_label]["help"]
    #     b.setStatusTip(help_string)
    #     # b.setShortcut("Ctrl+R")
    #     b.clicked.connect(lambda: self.handleCueButton(button_label))
    #     return b

    def init_CentralWidget(self):
        """The central widget holds the *non-toolbar*
        contents of the main window."""

        # basic layout/customization stuff

        #### to change color
        # self.setAutoFillBackground(True)
        # palette = self.palette()
        # palette.setColor(QtGui.QPalette.Window, QtGui.QColor("blue"))
        # self.setPalette(palette)

        # manage the location/size of widgets
        # grid = QtWidgets.QGridLayout()
        # i = 0
        # for label, lineedit in zip(self.setupLabels,self.setupLEdits):
        #     grid.addWidget(label,i,0)
        #     grid.addWidget(lineedit,i,1)
        #     i += 1
        # grid.addWidget(initSessButton,i,0,1,2)

        # # intialize the central widget
        # centralWidget = QtWidgets.QWidget()
        # # centralWidget.setLayout(grid)
        # self.setCentralWidget(centralWidget)

        # self.winWidth = centralWidget.sizeHint().width()
        # self.winHeight = centralWidget.sizeHint().height()

        ############ create buttons ################

        # leftListHeader = QtWidgets.QLabel("Cue Bank", self)
        # leftListHeader.setAlignment(QtCore.Qt.AlignCenter)
        # # leftListHeader.setStyleSheet("border: 1px solid red;") #changed

        # self.leftList = QtWidgets.QListWidget()
        # self.rightList = QtWidgets.QListWidget()
        # self.leftList.setAutoScroll(True) # scrollable
        # self.leftList.setAutoScroll(True)
        # self.leftList.setSortingEnabled(True) # allow alphabetical sorting
        # self.rightList.setSortingEnabled(True)

        # self.cueButton = QtWidgets.QPushButton("Cue", self)
        # self.cueButton.setStatusTip("Play a random cue from the right side.")
        # self.cueButton.setShortcut("Ctrl+R")
        # self.cueButton.setCheckable(True)
        # self.cueButton.clicked.connect(self.handleCueButton)

        # self.noiseButton = QtWidgets.QPushButton("Noise", self)
        # self.noiseButton.setStatusTip("Play pink noise.")
        # self.noiseButton.setShortcut("Ctrl+P")
        # self.noiseButton.setCheckable(True)
        # self.noiseButton.clicked.connect(self.handleNoiseButton)

        # self.left2rightButton = QtWidgets.QPushButton(">", self)
        # self.right2leftButton = QtWidgets.QPushButton("<", self)
        # self.left2rightButton.setStatusTip("Move selected item from left to right.")
        # self.right2leftButton.setStatusTip("Move selected item from right to left.")
        # self.left2rightButton.clicked.connect(self.handleLeft2RightButton)
        # self.right2leftButton.clicked.connect(self.handleRight2LeftButton)
        cueSelectionLayout = QtWidgets.QGridLayout()
        # cueSelectionLayout.addWidget(logViewer_header, 0, 0, 1, 1)
        # cueSelectionLayout.addWidget(leftListHeader, 0, 0, 1, 2)
        # # cueSelectionLayout.addWidget(self.cueButton, 0, 3, 1, 2)
        # cueSelectionLayout.addWidget(self.leftList, 1, 0, 4, 2)
        # cueSelectionLayout.addWidget(self.rightList, 1, 3, 4, 2)
        # cueSelectionLayout.addWidget(self.left2rightButton, 2, 2, 1, 1)
        # cueSelectionLayout.addWidget(self.right2leftButton, 3, 2, 1, 1)
        # # cueSelectionLayout.addWidget(self.cueButton, 5, 3, 1, 2)
        # for c in self.cue_name_list:
        #     self.leftList.addItem(c)

        # # all cue buttons are similar so can be created simultaneously
        # self.buttons = {}
        # for k in self.legend.keys():
        #     if k not in ["Dream report", "Note"]:
        #         self.buttons[k] = self.generate_cue_button(k)

        dreamReportButton = QtWidgets.QPushButton("Record dream report", self)
        dreamReportButton.setStatusTip("Ask for a dream report and start recording.")
        dreamReportButton.setCheckable(True)
        dreamReportButton.clicked.connect(self.handleDreamReportButton)

        # buttonsLayout = QtWidgets.QVBoxLayout()
        # # buttonsLayout.setMargin(20)
        # buttonsLayout.setAlignment(QtCore.Qt.AlignCenter)
        # # buttonsLayout.setFixedSize(12, 12)
        # buttonsLayout.addWidget(self.noiseButton)
        # buttonsLayout.addWidget(dreamReportButton)
        # buttonsLayout.addWidget(blinkButton)
        # buttonsLayout.addWidget(colorpickerButton)
        # buttonsLayout.addWidget(freqSpinBox)
        # buttonsLayout.addWidget(self.visual_stim_controller)

        # cue_header = QtWidgets.QLabel("Audio cue buttons", self)
        # cue_header.setAlignment(QtCore.Qt.AlignCenter)
        # # cue_header.setStyleSheet("border: 1px solid red;") #changed

        # # make a subset of buttons in a vertical layout
        # left_button_layout = QtWidgets.QVBoxLayout()
        # left_button_header = QtWidgets.QLabel("Waking", self)
        # # left_button_header.setText("Waking")
        # # left_button_header.setMargin(1)
        # left_button_header.setAlignment(QtCore.Qt.AlignCenter)
        # # left_button_header.setFixedSize(12, 12)
        # left_button_layout.addWidget(left_button_header)
        # left_button_layout.addWidget(self.buttons["Biocals"])
        # left_button_layout.addWidget(self.buttons["LRLR"])
        # left_button_layout.addWidget(self.buttons["TLR Training 1"])
        # left_button_layout.addWidget(self.buttons["TLR Training 2"])

        # right_button_layout = QtWidgets.QVBoxLayout()
        # right_button_header = QtWidgets.QLabel("Sleeping", self)
        # # left_button_header.setText("Waking")
        # # right_button_header.setMargin(20)
        # right_button_header.setAlignment(QtCore.Qt.AlignCenter)
        # # left_button_header.setFixedSize(12, 12)
        # right_button_layout.addWidget(right_button_header)
        # right_button_layout.addWidget(self.buttons["TLR cue"])
        # right_button_layout.addWidget(self.buttons["TMR cue"])


        border_widget = BorderWidget()

        # ## sublayout for audio cue section
        # audiocue_layout = QtWidgets.QGridLayout()
        # audiocue_layout.addWidget(cue_header, 0, 0, 1, 2) # widget, row, col, rowspan, colspan
        # audiocue_layout.addLayout(left_button_layout, 1, 0, 2, 1)
        # audiocue_layout.addLayout(right_button_layout, 1, 1, 2, 1)

        ## sublayout for extra buttons
        # extra_layout = QtWidgets.QGridLayout()
        # extra_layout.addLayout(buttonsLayout, 0, 0, 1, 1)

        # ## layout for the audio i/o monitoring
        # # io_layout = QtWidgets.QGridLayout()
        # io_layout = QtWidgets.QVBoxLayout()
        # io_header = QtWidgets.QLabel("Audio I/O", self)
        # io_header.setAlignment(QtCore.Qt.AlignCenter)
        # # io_layout.addWidget(io_header, 0, 0, 1, 2)
        # io_layout.addWidget(io_header)

        # # add row of headers
        # header_layout = QtWidgets.QHBoxLayout()
        # for label in ["Output Cue\nVolume", "Output Noise\nVolume", "Input\nGain", "Input\nVisualization"]:
        #     header_layout.addWidget(QtWidgets.QLabel(label, self))
        # io_layout.addLayout(header_layout)

        # create 2 sliders, 1 for output volume another for input gain
        # create volume slider and add to this i/o layout
        # volume slider stuff
        # cueVolumeSlider = QtWidgets.QSlider(QtCore.Qt.Vertical)
        buttonsLayout = QtWidgets.QVBoxLayout()

        ## sliders can only have integer values
        ## so have to use 0-100 and then divide when setting it later
        default_vol_upscaled = int(100 * DEFAULT_VOLUME)

        # # Cue Volume Knob Layout
        # cueVolumeKnob = QtWidgets.QDial()
        # cueVolumeKnob.setMinimum(0)
        # cueVolumeKnob.setMaximum(100)
        # cueVolumeKnob.setSingleStep(1)
        # cueVolumeKnob.setValue(default_vol_upscaled)
        # cueVolumeKnob.setNotchesVisible(True)
        # cueVolumeKnob.setWrapping(False)
        # cueVolumeKnob.valueChanged.connect(self.changeOutputCueVolume)
        # cueVolumeLabel = QtWidgets.QLabel("Cue Volume", self)
        # cueVolumeLabel.setAlignment(QtCore.Qt.AlignCenter)
        # cueVolumeLayout = QtWidgets.QVBoxLayout()
        # cueVolumeLayout.addWidget(cueVolumeLabel)
        # cueVolumeLayout.addWidget(cueVolumeKnob)

        # # Noise Volume Knob Layout
        # noiseVolumeKnob = QtWidgets.QDial()
        # noiseVolumeKnob.setMinimum(0)
        # noiseVolumeKnob.setMaximum(100)
        # noiseVolumeKnob.setSingleStep(1)
        # noiseVolumeKnob.setValue(default_vol_upscaled)
        # noiseVolumeKnob.setNotchesVisible(True)
        # noiseVolumeKnob.setWrapping(False)
        # noiseVolumeKnob.valueChanged.connect(self.changeOutputNoiseVolume)
        # noiseVolumeLabel = QtWidgets.QLabel("Noise Volume", self)
        # noiseVolumeLabel.setAlignment(QtCore.Qt.AlignCenter)
        # noiseVolumeLayout = QtWidgets.QVBoxLayout()
        # noiseVolumeLayout.addWidget(noiseVolumeLabel)
        # noiseVolumeLayout.addWidget(noiseVolumeKnob)

        # volumeKnobsLayout = QtWidgets.QHBoxLayout()
        # volumeKnobsLayout.addLayout(cueVolumeLayout)
        # volumeKnobsLayout.addLayout(noiseVolumeLayout)
        # volumeKnobsLayout.addWidget(self.lightSwitch)
        # formLayout = QtWidgets.QFormLayout()
        # formLayout.addRow(self.tr("&Volume:"), volumeSlider)
        # io_layout.addLayout(formLayout, 1, 0, 1, 2)
        # horizontalLayout = QtWidgets.QHBoxLayout(self)
        # horizontalLayout.addLayout(formLayout)
        # horizontalLayout.addLayout(buttonLayout)

        # gainSlider = QtWidgets.QSlider(QtCore.Qt.Vertical)
        # gainSlider.valueChanged.connect(self.changeInputGain)
        # volumeKnobsLayout.addWidget(gainSlider)

        # ## add a blank widget placeholder for the visualization for now
        # input_vis_widget = QtWidgets.QWidget()
        # volumeKnobsLayout.addWidget(input_vis_widget)


        # this main/larger layout holds all the subwidgets and in some cases other layouts
        # main_layout = QtWidgets.QGridLayout()
        # main_layout.addLayout(audiocue_layout, 0, 0, 3, 2)
        # main_layout.addLayout(cueSelectionLayout, 0, 0, 2, 2)
        # main_layout.addLayout(extra_layout, 3, 0, 1, 2)
        # main_layout.addLayout(viewer_layout, 0, 2, 2, 1)
        # main_layout.addLayout(volumeKnobsLayout, 2, 2, 2, 1)
        # main_layout.setContentsMargins(20, 20, 20, 20)
        # main_layout.setSpacing(20)
        # main_layout.addWidget(border_widget, 0, 0, 3, 2)
        # main_layout.setColumnStretch(0, 2)
        # main_layout.setColumnStretch(1, 1)

        # central_widget = QtWidgets.QWidget()
        # # central_widget.setStyleSheet("background-color:salmon;")
        # central_widget.setContentsMargins(5, 5, 5, 5)
        # central_widget.move(100, 100)  # Change initial startup position
        # # central_widget.setFixedSize(300, 300) # using self.resize makes it resizable
        # central_widget.setLayout(main_layout)

        # self.setCentralWidget(central_widget)
        # self.main_layout = main_layout
        # self.resize(300, 300)

    # def onClicked(self):
    #     cbutton = self.sender()
    #     print("Animal " + (cbutton.animal) + " is " + str(cbutton.isChecked()))


    def update_audio_source(self):
        """Catches signal from audio file lineedit/browser."""
        lineEdit = self.sender()
        filepath = lineEdit.text()
        # assert Path(filepath).exists() and Path(filepath).suffix == ".wav"
        content = QtCore.QUrl.fromLocalFile(filepath)
        # can do the assrtions here with content.exists()
        self.wavplayer.setSource(content)

    def update_audio_volume(self, value):
        """Method catching signals from audio stimulation volume spinbox
        NOT noise, audio cues.

        value should be a float from the spinbox
        """
        self.wavplayer.setVolume(value)  # 0 - 1
        # self.log_info_msg(f"VolumeSet - Cue {float_volume}")

    def update_noise_volume(self, value):
        """Method catching signals from audio stimulation volume spinbox
        NOT noise, audio cues.

        value should be a float from the spinbox
        """
        self.noiseplayer.setVolume(value)  # 0 - 1
        # self.log_info_msg(f"VolumeSet - Noise {float_volume}")

    def changeInputGain(self, value):
        self.showErrorPopup("Not implemented yet", "This should eventually allow for increasing mic input volume.")

    def closeEvent(self, event):
        """customize exit.
        closeEvent is a default method used in pyqt to close, so this overrides it
        """
        response = QtWidgets.QMessageBox.question(self, "Quit", "Do you want to quit/close SMACC?")
        if response == QtWidgets.QMessageBox.Yes:
            self.log_info_msg("Program closed")
            event.accept()
            # self.closed.emit()
            # sys.exit()
        else:
            event.ignore()
