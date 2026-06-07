"""Initialize a new session and open the main interface."""

from __future__ import annotations

import logging
import os
import queue
import shutil
import webbrowser
from functools import partial
from pathlib import Path
from typing import cast

import sounddevice as sd
from PyQt5 import QtCore, QtGui, QtMultimedia, QtWidgets

from smacc import audio, bids, study

from .config import (
    COMMON_EVENT_CODES,
    COMMON_EVENT_TIPS,
    SURVEY_OPTIONS,
    VERSION,
)
from .panels.base import ModalityWindow
from .panels.noise import NoiseWindow
from .paths import (
    LOGO_PATH,
    cues_directory,
    data_directory,
    dreams_directory,
)
from .qtlog import QtLogHandler
from .session import SmaccSession

try:
    from blinkstick import blinkstick
except ImportError:
    blinkstick = None


#####################################
#########    Main window    #########
#####################################


class SmaccWindow(QtWidgets.QMainWindow):
    """Main interface."""

    def __init__(self, session: SmaccSession) -> None:
        super().__init__()
        self.session = session

        self.n_report_counter = 0  # cumulative counter for determining filenames

        self.cues_directory = cues_directory
        # self.noise_directory = noise_directory

        # Lights state drives the dark theme; sessions start with lights on.
        self.lights_on = True
        self._default_palette = cast(
            QtWidgets.QApplication, QtWidgets.QApplication.instance()
        ).palette()

        self.init_blinkstick()
        self.init_audio_stimulation_setup()
        self.init_microphone()
        self.init_level_meter()
        self.init_intercom()

        # Modality windows, constructed up front (hidden) and opened on demand
        # from the launcher buttons. Each holds its own state for study save/load.
        self.panels: dict[str, ModalityWindow] = {
            "noise": NoiseWindow(self.session),
        }

        self.init_main_window()

        # Catch the spacebar app-wide (any focus) for intercom push-to-talk.
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

        self.session.log_info_msg("Opened SMACC v" + VERSION)

    def show_error_popup(self, short_msg, long_msg=None):
        """Show an error dialog parented to this window (logs via the session)."""
        self.session.show_error_popup(short_msg, long_msg, parent=self)

    def _update_preview_levels(self) -> None:
        """Sync the preview handler's visible levels to the menu checkboxes."""
        self.preview_handler.enabled_levels = {
            level
            for level, action in self._preview_level_actions.items()
            if action.isChecked()
        }

    def init_main_window(self):
        """Initialize SMACC's main window: menu/status bars and the widget grid."""
        self._build_menu_bar()
        toolBar = QtWidgets.QToolBar("Visual parameters", self)
        self.addToolBar(QtCore.Qt.LeftToolBarArea, toolBar)
        self.statusBar().showMessage("Ready")

        # 3x2 grid of panels; menu must be built first (the log-viewer panel
        # syncs the preview handler to the Log preview menu checkboxes).
        central_layout = QtWidgets.QGridLayout()
        central_layout.addLayout(self._build_visual_section(), 0, 0)
        central_layout.addLayout(self._build_audio_section(), 1, 0)
        central_layout.addLayout(self._build_launcher_buttons(), 2, 0)
        central_layout.addLayout(self._build_log_viewer_section(), 0, 1)
        central_layout.addLayout(self._build_recording_section(), 1, 1)
        central_layout.addLayout(self._build_events_section(), 2, 1)
        central_widget = QtWidgets.QWidget()
        central_widget.setContentsMargins(5, 5, 5, 5)
        central_widget.move(100, 100)
        central_widget.setLayout(central_layout)
        self.setCentralWidget(central_widget)

        self.setWindowTitle("SMACC")
        if LOGO_PATH.is_file():
            windowIcon = QtGui.QIcon(str(LOGO_PATH))
        else:
            windowIcon = self.style().standardIcon(
                QtWidgets.QStyle.SP_ToolBarHorizontalExtensionButton
            )
        self.setWindowIcon(windowIcon)
        self.resize(1200, 500)
        # Always-on-top is off by default (toggle via File -> Always on top).
        self.show()

    @staticmethod
    def _make_section_title(text: str) -> QtWidgets.QLabel:
        """Build a centered 18pt section header.

        Uses a QFont (not a stylesheet) so the text color follows the palette
        and stays legible when the dark theme toggles.
        """
        label = QtWidgets.QLabel(text)
        label.setAlignment(QtCore.Qt.AlignCenter)
        font = QtGui.QFont()
        font.setPointSize(18)
        label.setFont(font)
        return label

    # Modality windows openable from the launcher (key -> button label).
    PANEL_LABELS = {
        "visual": "Visual stimulation",
        "audio": "Audio cue",
        "noise": "Noise machine",
        "recording": "Dream recording",
        "intercom": "Intercom",
    }

    def _build_launcher_buttons(self) -> QtWidgets.QLayout:
        """Build the 'Open tools' column with a button per extracted panel."""
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self._make_section_title("Open tools"))
        for key, label in self.PANEL_LABELS.items():
            if key not in self.panels:
                continue
            button = QtWidgets.QPushButton(label, self)
            button.clicked.connect(partial(self._open_panel, key))
            layout.addWidget(button)
        layout.addStretch(1)
        return layout

    def _open_panel(self, key: str) -> None:
        """Show and focus the modality window for ``key``."""
        window = self.panels[key]
        window.show()
        window.raise_()
        window.activateWindow()

    def _build_menu_bar(self) -> None:
        """Build the consolidated File menu (actions + log-preview levels)."""
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

        # View -> Always on top: keep the control window above other apps. Off by
        # default; app dialogs are parented to the window so they still stack above it.
        alwaysOnTopAction = QtWidgets.QAction("Always on &top", self)
        alwaysOnTopAction.setStatusTip(
            "Keep the SMACC window above other applications."
        )
        alwaysOnTopAction.setCheckable(True)
        alwaysOnTopAction.setChecked(False)
        alwaysOnTopAction.toggled.connect(self.toggle_always_on_top)

        menuBar = self.menuBar()
        # menuBar.setNativeMenuBar(False)  # needed for pyqt5 on Mac
        # Single consolidated File menu holding all app actions.
        fileMenu = menuBar.addMenu("&File")
        fileMenu.addAction(saveStudyAction)
        fileMenu.addAction(loadStudyAction)
        fileMenu.addSeparator()
        fileMenu.addAction(exportEventsAction)
        fileMenu.addSeparator()
        fileMenu.addAction(alwaysOnTopAction)
        fileMenu.addSeparator()
        # File -> Log preview: pick which log levels show in the preview pane.
        # Everything is always written to the log file regardless of these.
        previewMenu = fileMenu.addMenu("Log preview")
        self._preview_level_actions: dict[int, QtWidgets.QAction] = {}
        for levelname, levelno in (
            ("Debug", logging.DEBUG),
            ("Info", logging.INFO),
            ("Warning", logging.WARNING),
            ("Error", logging.ERROR),
            ("Critical", logging.CRITICAL),
        ):
            levelAction = QtWidgets.QAction(levelname, self)
            levelAction.setCheckable(True)
            levelAction.setChecked(levelno != logging.DEBUG)  # all but Debug
            levelAction.toggled.connect(self._update_preview_levels)
            previewMenu.addAction(levelAction)
            self._preview_level_actions[levelno] = levelAction
        fileMenu.addSeparator()
        fileMenu.addAction(aboutAction)
        fileMenu.addAction(quitAction)

    def _build_visual_section(self) -> QtWidgets.QLayout:
        """Build the visual-stimulation (BlinkStick) panel."""
        visualtitleLabel = self._make_section_title("Visual stimulation")

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
        colorpickerButton.clicked.connect(self.pick_color)
        self.colorpickerButton = colorpickerButton
        self._update_color_swatch()  # show the current color from the start

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
        return visualstimLayout

    def _build_audio_section(self) -> QtWidgets.QLayout:
        """Build the audio-stimulation (cue player) panel."""
        audiotitleLabel = self._make_section_title("Audio stimulation")

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

        # Fade-in (attack) and fade-out (release) ramps, in seconds. Ramping the
        # cue volume avoids an abrupt onset that could wake the participant (#22).
        attackSpinBox = QtWidgets.QDoubleSpinBox(self)
        attackSpinBox.setStatusTip(
            "Fade-in time for the cue, in seconds (0 = instant)."
        )
        attackSpinBox.setRange(0, 60)
        attackSpinBox.setSingleStep(0.1)
        attackSpinBox.setSuffix(" seconds")
        attackSpinBox.valueChanged.connect(self.update_cue_attack)
        attackSpinBox.setValue(0.0)
        self.attackSpinBox = attackSpinBox

        releaseSpinBox = QtWidgets.QDoubleSpinBox(self)
        releaseSpinBox.setStatusTip(
            "Fade-out time when stopping the cue, in seconds (0 = instant)."
        )
        releaseSpinBox.setRange(0, 60)
        releaseSpinBox.setSingleStep(0.1)
        releaseSpinBox.setSuffix(" seconds")
        releaseSpinBox.valueChanged.connect(self.update_cue_release)
        releaseSpinBox.setValue(0.0)
        self.releaseSpinBox = releaseSpinBox

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
        audiostimLayout.addRow("Fade in:", attackSpinBox)
        audiostimLayout.addRow("Fade out:", releaseSpinBox)
        audiostimLayout.addRow(wavselectorLayout)
        audiostimLayout.addRow(loopCheckBox)
        audiostimLayout.addRow(playstopcueLayout)
        audiostimLayout.addRow(cueStatusLabel)
        return audiostimLayout

    def _build_recording_section(self) -> QtWidgets.QLayout:
        """Build the dream-recording panel (mic, level meter, intercom, survey)."""
        recordingtitleLabel = self._make_section_title("Dream recording")

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

        # Live input level meter (#25): monitor microphone/room level in dBFS.
        # Checkbox + bar share one row (label provided by the form layout).
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

        # Intercom (#20): live experimenter-mic -> participant-output so the
        # experimenter can talk to the participant. Toggle/spacebar; LSL markers.
        # Output device the participant hears on (their speakers/headphones).
        intercom_output_dropdown = QtWidgets.QComboBox()
        intercom_output_dropdown.setStatusTip(
            "Output device the participant hears the intercom on "
            "(their speakers/headphones)."
        )
        self.intercom_output_dropdown = intercom_output_dropdown
        self.refresh_intercom_outputs()

        intercomButton = QtWidgets.QPushButton("Intercom (talk)", self)
        intercomButton.setStatusTip(
            "Click to latch the intercom on/off, or press and hold the spacebar to "
            "talk (push-to-talk). Warning: risks feedback near open speakers."
        )
        intercomButton.setCheckable(True)
        intercomButton.toggled.connect(self.toggle_intercom)
        self.intercomButton = intercomButton

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
        microphoneLayout.addRow("Show input level:", levelLayout)
        microphoneLayout.addRow("To participant:", intercom_output_dropdown)
        microphoneLayout.addRow("Intercom:", intercomButton)
        return microphoneLayout

    def _build_events_section(self) -> QtWidgets.QLayout:
        """Build the event-marker grid (lightswitch + common event buttons)."""
        eventmarkertitleLabel = self._make_section_title("Event logging")

        # Lights toggle: a single switch replacing the two lights event buttons.
        # It sends the lights marker and flips the dark theme. Connect the
        # toggled signal only after setChecked so construction fires no marker.
        self.lightswitchButton = QtWidgets.QPushButton(self)
        self.lightswitchButton.setCheckable(True)
        self.lightswitchButton.setShortcut("L")
        self.lightswitchButton.setMinimumHeight(48)
        self.lightswitchButton.setStatusTip(
            "Toggle lights off/on (sends the lights event marker and switches theme)"
        )
        self.lightswitchButton.setChecked(True)
        self._refresh_lightswitch_label()
        self.lightswitchButton.toggled.connect(self.on_lightswitch_toggled)

        eventsLayout = QtWidgets.QGridLayout()
        eventsLayout.addWidget(eventmarkertitleLabel, 0, 0, 1, 2)
        eventsLayout.addWidget(self.lightswitchButton, 1, 0, 1, 2)
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
            row = 2 + i
            if i >= (halfsize := int(n_events / 2)):
                row -= halfsize
            col = 1 if i >= halfsize else 0
            eventsLayout.addWidget(button, row, col)
        return eventsLayout

    def _build_log_viewer_section(self) -> QtWidgets.QLayout:
        """Build the log-viewer panel and attach the preview log handler."""
        logviewertitleLabel = self._make_section_title("Log viewer")

        # Events log viewer --> gets updated when events are logged
        logviewList = QtWidgets.QListWidget()
        logviewList.setAutoScroll(True)
        # logviewList.setGeometry(20,20,100,700)
        self.logviewList = logviewList

        # Route log records to the preview pane, filtered by the Log preview menu.
        self.preview_handler = QtLogHandler(logviewList)
        self.preview_handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s  %(levelname)s  %(message)s", datefmt="%H:%M:%S"
            )
        )
        self.session.logger.addHandler(self.preview_handler)
        self._update_preview_levels()  # sync to the menu checkboxes

        logviewLayout = QtWidgets.QFormLayout()
        logviewLayout.addRow(logviewertitleLabel)
        logviewLayout.addRow(logviewList)
        return logviewLayout

    def toggle_always_on_top(self, enabled: bool) -> None:
        """Toggle the window's always-on-top hint (from the View menu)."""
        self.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, enabled)
        # Re-applying window flags hides the window on some platforms; re-show it.
        self.show()
        self.session.log_info_msg(
            f"Always-on-top {'enabled' if enabled else 'disabled'}"
        )

    def show_about_popup(self):
        win = QtWidgets.QMessageBox(self)  # parent to self so it stacks above
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
        self.session.send_event_marker(code, text)

    def on_lightswitch_toggled(self, checked: bool) -> None:
        """Handle a user toggle of the lightswitch (``checked`` == lights on)."""
        self.set_lights(checked, send_marker=True)

    def set_lights(self, lights_on: bool, send_marker: bool = False) -> None:
        """Update lights state, refresh the switch, and apply the theme.

        ``send_marker`` stays False during setup so the event marker only fires
        on real user interaction.
        """
        self.lights_on = lights_on
        self._refresh_lightswitch_label()
        self.apply_theme(dark=not lights_on)
        if send_marker:
            name = "Lights on" if lights_on else "Lights off"
            self.session.send_event_marker(COMMON_EVENT_CODES[name], name)

    def _refresh_lightswitch_label(self) -> None:
        """Sync the lightswitch text/style to the current state."""
        if self.lights_on:
            self.lightswitchButton.setText(
                "\U0001f4a1 Lights ON  (L) — click to turn OFF"
            )
            self.lightswitchButton.setStyleSheet(
                "font: bold 14pt; padding: 8px; background-color: #f0d000; color: black;"
            )
        else:
            self.lightswitchButton.setText(
                "\U0001f319 Lights OFF  (L) — click to turn ON"
            )
            self.lightswitchButton.setStyleSheet(
                "font: bold 14pt; padding: 8px; background-color: #303030; color: #dddddd;"
            )

    def apply_theme(self, dark: bool) -> None:
        """Apply the dark or the default light palette to the whole application."""
        app = cast("QtWidgets.QApplication | None", QtWidgets.QApplication.instance())
        if app is None:
            return
        app.setPalette(self._dark_palette() if dark else self._default_palette)

    @staticmethod
    def _dark_palette() -> QtGui.QPalette:
        """Build a dark, Fusion-friendly palette."""
        p = QtGui.QPalette()
        base = QtGui.QColor(53, 53, 53)
        text = QtGui.QColor(220, 220, 220)
        disabled = QtGui.QColor(127, 127, 127)
        highlight = QtGui.QColor(42, 130, 218)
        p.setColor(QtGui.QPalette.Window, base)
        p.setColor(QtGui.QPalette.WindowText, text)
        p.setColor(QtGui.QPalette.Base, QtGui.QColor(35, 35, 35))
        p.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(45, 45, 45))
        p.setColor(QtGui.QPalette.ToolTipBase, base)
        p.setColor(QtGui.QPalette.ToolTipText, text)
        p.setColor(QtGui.QPalette.Text, text)
        p.setColor(QtGui.QPalette.Button, base)
        p.setColor(QtGui.QPalette.ButtonText, text)
        p.setColor(QtGui.QPalette.Highlight, highlight)
        p.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor(0, 0, 0))
        for role in (
            QtGui.QPalette.WindowText,
            QtGui.QPalette.Text,
            QtGui.QPalette.ButtonText,
        ):
            p.setColor(QtGui.QPalette.Disabled, role, disabled)
        return p

    def open_wav_selector(self):
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select a File", str(self.cues_directory), "Audio (*.wav)"
        )
        if filename:
            path = Path(filename)
            self.wavselectorEdit.setText(str(path))

    def set_new_speakers(self, text: str) -> None:
        """Handle a new audio-stimulation speaker selection."""
        self.session.logger.debug(f"New speakers {text} selected!")

    def set_new_microphone(self, text: str) -> None:
        """Handle a new microphone selection."""
        self.session.logger.debug(f"New microphone {text} selected!")

    ############################################################################
    # Functions for refreshing/searching for connected devices (inputs and outputs)
    ############################################################################

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
        if not text:  # dropdown cleared / no device selected
            self.bstick = None
            return
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
        # Clear existing devices from the dropdown menu. When the `blinkstick`
        # package is missing or no device is connected, leave the dropdown empty
        # silently — the error is raised only when visual stimulation is used
        # (see _ensure_blinkstick), so non-BlinkStick users aren't nagged.
        self.available_blinksticks_dropdown.clear()
        devices = [] if blinkstick is None else blinkstick.find_all()
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
            # self.session.log_info_msg(f"INPUT DEVICE UPDATE {new_device_name}")
            # self.show_error_popup("Not implemented yet")
        elif not checked:
            # this is when someone tries to "unselect" an input.
            # can't be allowed, but pyqt will uncheck it, so recheck it
            self.sender().setChecked(True)  # recheck it
            # for menu_item in self.input_menu_items:
            #     if menu_item.iconText() == self.sender().text():
            #         menu_item.setChecked(True)

    def init_blinkstick(self):
        self.bstick = None  # selected device; None until one is found/selected
        self.bstick_blink_freq = 1.0
        self.set_blink_color(0, 0, 0)  # default color: black/off

    def set_blink_color(self, r: int, g: int, b: int) -> None:
        """Set the BlinkStick color from 0-255 RGB components.

        Stores the hex code (for study save/load) and precomputes the LED data.
        blinkstick.set_led_data expects G/R swapped: 3 values per LED, 32 LEDs.
        """
        self.bstick_rgb = (r, g, b, 255)
        self.bstick_hexcode = f"#{r:02x}{g:02x}{b:02x}"
        self.bstick_led_data = [g, r, b] * 32
        # Keep the color picker's swatch in sync (once the button exists).
        if hasattr(self, "colorpickerButton"):
            self._update_color_swatch()

    def _update_color_swatch(self) -> None:
        """Show the currently selected blink color on the color picker button."""
        size = 22
        pixmap = QtGui.QPixmap(size, size)
        pixmap.fill(QtGui.QColor(*self.bstick_rgb))
        painter = QtGui.QPainter(pixmap)
        painter.setPen(QtGui.QColor("#808080"))  # border so black/white read
        painter.drawRect(0, 0, size - 1, size - 1)
        painter.end()
        self.colorpickerButton.setIcon(QtGui.QIcon(pixmap))
        self.colorpickerButton.setIconSize(QtCore.QSize(size, size))

    def _ensure_blinkstick(self) -> bool:
        """Return True if a BlinkStick is usable, else show one error popup."""
        if blinkstick is not None and self.bstick is not None:
            return True
        self.show_error_popup(
            "Visual stimulation unavailable.",
            "No BlinkStick device was found and/or the `blinkstick` Python "
            "package is not installed.",
        )
        return False

    def init_audio_stimulation_setup(self):
        """Create media player for cue files."""
        player = QtMultimedia.QSoundEffect()
        # Default settings
        # player.setVolume(0)  # 0 to 1 -- Gets set already when parameter selector is made
        player.setLoopCount(1)
        player.playingChanged.connect(self.on_cue_playing_change)
        self.wavplayer = player
        # Fade (attack/release) durations in seconds; 0 == instant on/off.
        self.cue_attack_s = 0.0
        self.cue_release_s = 0.0
        self._cue_fade_anim: QtCore.QPropertyAnimation | None = None

    ############################################################################
    # Input level meter (#25)
    ############################################################################

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
                self.show_error_popup("Could not open input for monitoring.", str(exc))
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

    ############################################################################
    # Intercom: live mic -> speaker routing (#20)
    ############################################################################

    def init_intercom(self) -> None:
        """Set up intercom (live experimenter-mic -> participant-output) state.

        Uses two independent streams (mic in, participant out) bridged by a queue
        and a resampler, so the two devices need not share a sample rate.
        """
        self.intercom_input_stream: sd.InputStream | None = None
        self.intercom_output_stream: sd.OutputStream | None = None
        self._intercom_queue: queue.Queue | None = None
        self._intercom_resampler: audio.LinearResampler | None = None
        self._intercom_push_to_talk = False  # True while held via spacebar

    def refresh_intercom_outputs(self) -> None:
        """Populate the intercom output dropdown with available output devices.

        seealso: refresh_available_noisespeakers
        """
        self.intercom_output_dropdown.clear()
        host_api_name = "Windows WASAPI"
        host_api_names = [api["name"] for api in sd.query_hostapis()]
        hostapi = (
            host_api_names.index(host_api_name)
            if host_api_name in host_api_names
            else None
        )
        for device in sd.query_devices():
            if device["max_output_channels"] <= 0:
                continue
            if hostapi is not None and device["hostapi"] != hostapi:
                continue
            suffix = f", {host_api_name}" if hostapi is not None else ""
            self.intercom_output_dropdown.addItem(f"{device['name']}{suffix}")
        if self.intercom_output_dropdown.count():
            self.intercom_output_dropdown.setCurrentIndex(0)

    def toggle_intercom(self, enabled: bool) -> None:
        """Start/stop routing the experimenter mic to the participant output.

        Two single-direction streams (each at its device's native rate) bridged by
        a queue + resampler, so mismatched sample rates are fine. Logged and marked
        in the EEG record via LSL. Warning: a mic near open speakers risks feedback.
        """
        if enabled:
            # Default input (experimenter mic); selected output (participant hears).
            output_device = self.intercom_output_dropdown.currentText() or None
            try:
                in_rate = int(sd.query_devices(kind="input")["default_samplerate"])
                out_info = (
                    sd.query_devices(output_device, "output")
                    if output_device
                    else sd.query_devices(kind="output")
                )
                out_rate = int(out_info["default_samplerate"])
                self._intercom_queue = queue.Queue(maxsize=32)
                self._intercom_resampler = audio.LinearResampler(in_rate, out_rate)
                self.intercom_input_stream = sd.InputStream(
                    samplerate=in_rate,
                    channels=1,
                    callback=self._intercom_in_callback,
                )
                self.intercom_output_stream = sd.OutputStream(
                    samplerate=out_rate,
                    channels=1,
                    device=output_device,
                    callback=self._intercom_out_callback,
                )
                self.intercom_input_stream.start()
                self.intercom_output_stream.start()
            except Exception as exc:  # PortAudio errors, no device, etc.
                self._stop_intercom_streams()
                self.show_error_popup("Could not start intercom.", str(exc))
                self.intercomButton.setChecked(False)
                return
            self.session.send_event_marker(
                self.session.portcodes["IntercomStarted"], "Intercom unmuted (talking)"
            )
        elif self._stop_intercom_streams():
            self.session.send_event_marker(
                self.session.portcodes["IntercomStopped"], "Intercom remuted"
            )

    def _stop_intercom_streams(self) -> bool:
        """Tear down both intercom streams; return True if any were running."""
        stopped = False
        for attr in ("intercom_input_stream", "intercom_output_stream"):
            stream = getattr(self, attr)
            if stream is not None:
                stream.abort()
                stream.close()
                setattr(self, attr, None)
                stopped = True
        self._intercom_queue = None
        self._intercom_resampler = None
        return stopped

    def _intercom_in_callback(self, indata, frames, time, status) -> None:
        """Mic stream (audio thread): queue captured frames for the output stream."""
        if self._intercom_queue is not None:
            try:
                self._intercom_queue.put_nowait(indata[:, 0].copy())
            except queue.Full:
                pass  # output not keeping up; drop a block rather than block

    def _intercom_out_callback(self, outdata, frames, time, status) -> None:
        """Output stream (audio thread): resample queued mic frames to the device."""
        if self._intercom_queue is not None and self._intercom_resampler is not None:
            while True:
                try:
                    self._intercom_resampler.push(self._intercom_queue.get_nowait())
                except queue.Empty:
                    break
            outdata[:, 0] = self._intercom_resampler.pull(frames)
        else:
            outdata.fill(0)

    @staticmethod
    def _is_text_widget_focused() -> bool:
        """True if a text-entry widget has focus (so space should type, not talk)."""
        widget = QtWidgets.QApplication.focusWidget()
        return isinstance(
            widget,
            (
                QtWidgets.QLineEdit,
                QtWidgets.QAbstractSpinBox,
                QtWidgets.QTextEdit,
                QtWidgets.QPlainTextEdit,
            ),
        )

    def eventFilter(self, obj, event) -> bool:
        """Application-wide spacebar push-to-talk for the intercom.

        Installed on the QApplication so it sees the spacebar regardless of which
        widget has focus (a plain keyPressEvent only fires when the window itself
        is focused). Hold space to talk, release to stop; auto-repeat is swallowed
        so the intercom never rapidly toggles. Space passes through untouched while
        a text-entry widget is focused, so typing (notes, URLs) still works.
        """
        etype = event.type()
        if (
            etype in (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease)
            and event.key() == QtCore.Qt.Key_Space
            and not self._is_text_widget_focused()
        ):
            if etype == QtCore.QEvent.KeyPress:
                if not event.isAutoRepeat() and not self.intercomButton.isChecked():
                    self._intercom_push_to_talk = True
                    self.intercomButton.setChecked(True)  # -> toggle_intercom(True)
            elif not event.isAutoRepeat() and self._intercom_push_to_talk:
                self._intercom_push_to_talk = False
                self.intercomButton.setChecked(False)  # -> toggle_intercom(False)
            return True  # consume so the focused widget doesn't also see space
        return super().eventFilter(obj, event)

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
            basename = f"sub-{self.session.subject}_ses-{self.session.session}_report-{self.n_report_counter:02d}.wav"
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
        state = {
            "cue_file": self.wavselectorEdit.text(),
            "cue_volume": self.volumeSpinBox.value(),
            "cue_loop": self.loopCheckBox.isChecked(),
            "cue_attack": self.attackSpinBox.value(),
            "cue_release": self.releaseSpinBox.value(),
            "blink_color": self.bstick_hexcode,
            "blink_length": self.bstick_blink_freq,
            "survey_url": self.current_survey_url(),
            "survey_options": survey_options,
        }
        for panel in self.panels.values():
            state.update(panel.gather_state())
        return state

    def apply_study_state(self, state: dict) -> None:
        """Apply a study ``state`` dict to the GUI widgets.

        Setting widget values fires their existing signals, so volume/source/
        color/length all propagate without extra wiring.
        """
        if cue := state.get("cue_file"):
            self.wavselectorEdit.setText(cue)
        if (v := state.get("cue_volume")) is not None:
            self.volumeSpinBox.setValue(float(v))
        if (v := state.get("cue_attack")) is not None:
            self.attackSpinBox.setValue(float(v))
        if (v := state.get("cue_release")) is not None:
            self.releaseSpinBox.setValue(float(v))
        self.loopCheckBox.setChecked(bool(state.get("cue_loop", False)))
        for panel in self.panels.values():
            panel.apply_state(state)
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
        self.session.log_info_msg(f"Saved study to {study_dir}")

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
        self.session.log_info_msg(f"Loaded study from {study_path}")

    def export_events_bids(self) -> None:
        """Convert the session log to a BIDS events.tsv (+ JSON sidecar)."""
        if not self.session.log_path.is_file():
            self.show_error_popup("No log file to export yet.")
            return
        # Flush handlers so the on-disk log includes the latest events.
        for handler in self.session.logger.handlers:
            handler.flush()
        default = self.session.log_path.with_name(
            f"sub-{self.session.subject}_ses-{self.session.session}_events.tsv"
        )
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export events (BIDS)", str(default), "BIDS events (*.tsv)"
        )
        if not path:
            return
        try:
            log_text = self.session.log_path.read_text(encoding="utf-8")
            events = bids.log_to_events(log_text)
            bids.write_events_tsv(events, path)
            bids.write_events_json(Path(path).with_suffix(".json"))
        except OSError as exc:
            self.show_error_popup("Could not export events.", str(exc))
            return
        self.session.log_info_msg(f"Exported {len(events)} events to {path}")

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
        portcode = self.session.portcodes[port_msg]
        self.session.send_event_marker(portcode, port_msg)

    @QtCore.pyqtSlot()
    def pick_color(self):
        if not self._ensure_blinkstick():
            return
        # Parent to self and seed with the current color so the dialog stacks
        # above the main window (even when always-on-top is enabled).
        color = QtWidgets.QColorDialog.getColor(QtGui.QColor(self.bstick_hexcode), self)
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
        # portcode = self.session.portcodes["blink"]
        # port_msg = f"Set color: [{color}]"
        # self.session.send_event_marker(portcode, port_msg)

    @QtCore.pyqtSlot()
    def stimulate_audio(self):
        """Play the cue, ramping volume up over the attack time if set."""
        target = self.volumeSpinBox.value()
        if self.cue_attack_s > 0:
            self.wavplayer.setVolume(0.0)
            self.wavplayer.play()
            self._fade_volume(0.0, target, self.cue_attack_s)
        else:
            self.wavplayer.setVolume(target)
            self.wavplayer.play()

    @QtCore.pyqtSlot()
    def stop_audio(self):
        """Stop the cue, ramping volume down over the release time if set."""
        if self.cue_release_s > 0 and self.wavplayer.isPlaying():
            anim = self._fade_volume(self.wavplayer.volume(), 0.0, self.cue_release_s)
            anim.finished.connect(self.wavplayer.stop)
        else:
            self.wavplayer.stop()

    def _fade_volume(
        self, start: float, end: float, seconds: float
    ) -> QtCore.QPropertyAnimation:
        """Animate the cue player's volume from ``start`` to ``end``."""
        anim = QtCore.QPropertyAnimation(self.wavplayer, b"volume", self)
        anim.setDuration(int(seconds * 1000))
        anim.setStartValue(float(start))
        anim.setEndValue(float(end))
        anim.start()
        self._cue_fade_anim = anim  # keep a reference so it isn't garbage-collected
        return anim

    def update_cue_attack(self, value: float) -> None:
        """Set the cue fade-in (attack) time in seconds."""
        self.cue_attack_s = value

    def update_cue_release(self, value: float) -> None:
        """Set the cue fade-out (release) time in seconds."""
        self.cue_release_s = value

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
        if not self._ensure_blinkstick():
            return
        from time import sleep

        black = [0, 0, 0] * 32
        freq = self.bstick_blink_freq
        self.bstick.set_led_data(channel=0, data=self.bstick_led_data)
        sleep(freq)
        self.bstick.set_led_data(channel=0, data=black)
        # portcode = self.session.portcodes["blink"]
        # port_msg = f"Set color: [{color}]"
        # self.session.send_event_marker(portcode, port_msg)

    def open_note_marker_dialogue(self):
        text, ok = QtWidgets.QInputDialog.getText(
            self, "Text Input Dialog", "Custom note (no commas):"
        )
        # self.subject_id.setValidator(QtGui.QIntValidator(0, 999)) # must be a 3-digit number
        if ok:  # True of OK button was hit, False otherwise (cancel button)
            portcode = self.session.portcodes["Note"]
            port_msg = f"Note [{text}]"
            self.session.send_event_marker(portcode, port_msg)

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
        # self.session.log_info_msg(f"VolumeSet - Cue {float_volume}")

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
            for panel in self.panels.values():
                panel._quitting = True
                panel.cleanup()
                panel.close()
            if self.meter_stream is not None:
                self.meter_stream.close()
            self._stop_intercom_streams()
            self.session.log_info_msg("Program closed")
            event.accept()
        else:
            event.ignore()
