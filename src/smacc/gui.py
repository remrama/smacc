"""Initialize a new session and open the main interface."""

from __future__ import annotations

import logging
from functools import partial
from pathlib import Path
from typing import cast

from PyQt5 import QtCore, QtGui, QtWidgets

from smacc import bids, preferences, settings, winassoc

from .config import (
    COMMON_EVENT_CODES,
    COMMON_EVENT_TIPS,
    VERSION,
)
from .dialogs import SessionInfoDialog
from .panels.audio import AudioCueWindow
from .panels.base import ModalityWindow
from .panels.intercom import IntercomWindow
from .panels.noise import NoiseWindow
from .panels.recording import RecordingWindow
from .panels.visual import VisualWindow
from .paths import LOGO_PATH, data_directory, preferences_path, sessions_directory
from .qtlog import QtLogHandler
from .session import SmaccSession

#####################################
#########    Main window    #########
#####################################


class SmaccWindow(QtWidgets.QMainWindow):
    """Main interface."""

    def __init__(self, session: SmaccSession, settings_path: str | None = None) -> None:
        super().__init__()
        self.session = session
        # Operator/machine preferences (window/theme/log-preview); never raises.
        self._prefs = preferences.load_preferences(preferences_path)

        # Lights state drives the dark theme; sessions start with lights on.
        self.lights_on = True
        self._default_palette = cast(
            QtWidgets.QApplication, QtWidgets.QApplication.instance()
        ).palette()

        # Modality windows, constructed up front (hidden) and opened on demand
        # from the launcher buttons. Each holds its own state for settings save/load.
        self.panels: dict[str, ModalityWindow] = {
            "visual": VisualWindow(self.session),
            "audio": AudioCueWindow(self.session),
            "noise": NoiseWindow(self.session),
            "recording": RecordingWindow(self.session),
            "intercom": IntercomWindow(self.session),
        }

        self.init_main_window()  # builds the menu + log handler (does not show yet)
        self._apply_preferences(self._prefs)
        # A study file passed on launch becomes this session's initial setup.
        if settings_path:
            self._load_initial_settings(settings_path)
        self.show()  # single show, after window flags + geometry are applied

        # Panels (and any launch-file overrides) are in place, so capture the
        # initial state into the log header (also emits the "Opened SMACC" line).
        self.session.begin_log(self.gather_settings())
        self._maybe_prompt_association()

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
        self.statusBar().showMessage("Ready")

        # 3x2 grid of panels; menu must be built first (the log-viewer panel
        # syncs the preview handler to the Log preview menu checkboxes).
        central_layout = QtWidgets.QGridLayout()
        central_layout.addLayout(self._build_launcher_buttons(), 0, 0)
        central_layout.addLayout(self._build_log_viewer_section(), 0, 1)
        central_layout.addLayout(self._build_events_section(), 1, 0, 1, 2)
        central_widget = QtWidgets.QWidget()
        central_widget.setContentsMargins(5, 5, 5, 5)
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
        # Window size/position, theme, always-on-top, and log-preview levels come
        # from saved preferences (applied by _apply_preferences); __init__ shows
        # the window afterwards.

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

        # File -> Export/Load settings: persist the current setup to a portable
        # settings.yaml (and reload it from a .yaml or from a .log's header block).
        exportSettingsAction = QtWidgets.QAction("&Export study (.smacc)…", self)
        exportSettingsAction.setStatusTip(
            "Save the current setup to a portable .smacc study file."
        )
        exportSettingsAction.triggered.connect(self.export_settings)
        loadSettingsAction = QtWidgets.QAction("&Load study (.smacc)…", self)
        loadSettingsAction.setStatusTip("Load a setup from a .smacc study file.")
        loadSettingsAction.triggered.connect(self.load_settings)
        loadSettingsFromLogAction = QtWidgets.QAction("Load study from &log…", self)
        loadSettingsFromLogAction.setStatusTip(
            "Load the initial or final setup recorded in a SMACC .log file."
        )
        loadSettingsFromLogAction.triggered.connect(self.load_settings_from_log)

        sessionInfoAction = QtWidgets.QAction("Session &info…", self)
        sessionInfoAction.setStatusTip(
            "Edit optional subject/session/notes metadata for this session."
        )
        sessionInfoAction.triggered.connect(self.session_info)

        exportEventsAction = QtWidgets.QAction("&Export events (BIDS)…", self)
        exportEventsAction.setStatusTip(
            "Export this session's events log as a BIDS events.tsv."
        )
        exportEventsAction.triggered.connect(self.export_events_bids)
        exportEventsFromLogAction = QtWidgets.QAction("Export events from lo&g…", self)
        exportEventsFromLogAction.setStatusTip(
            "Convert any SMACC .log file into a BIDS events.tsv."
        )
        exportEventsFromLogAction.triggered.connect(self.export_events_from_log)

        # View -> Always on top: keep the control window above other apps. Off by
        # default; app dialogs are parented to the window so they still stack above it.
        alwaysOnTopAction = QtWidgets.QAction("Always on &top", self)
        alwaysOnTopAction.setStatusTip(
            "Keep the SMACC window above other applications."
        )
        alwaysOnTopAction.setCheckable(True)
        alwaysOnTopAction.setChecked(False)
        alwaysOnTopAction.toggled.connect(self.toggle_always_on_top)
        self._always_on_top_action = alwaysOnTopAction

        associateAction = QtWidgets.QAction("&Associate .smacc files (Windows)", self)
        associateAction.setStatusTip(
            "Register SMACC as the handler for .smacc files (double-click to open)."
        )
        associateAction.triggered.connect(self.associate_files)

        menuBar = self.menuBar()
        # menuBar.setNativeMenuBar(False)  # needed for pyqt5 on Mac
        # Single consolidated File menu holding all app actions.
        fileMenu = menuBar.addMenu("&File")
        fileMenu.addAction(exportSettingsAction)
        fileMenu.addAction(loadSettingsAction)
        fileMenu.addAction(loadSettingsFromLogAction)
        fileMenu.addSeparator()
        fileMenu.addAction(sessionInfoAction)
        # File -> Surveys: open any saved survey standalone (not tied to a dream
        # report). Rebuilt each time it opens, since the saved list changes as
        # surveys are added/edited/removed.
        surveysMenu = fileMenu.addMenu("Sur&veys")
        surveysMenu.aboutToShow.connect(lambda: self._rebuild_surveys_menu(surveysMenu))
        fileMenu.addSeparator()
        fileMenu.addAction(exportEventsAction)
        fileMenu.addAction(exportEventsFromLogAction)
        fileMenu.addSeparator()
        fileMenu.addAction(alwaysOnTopAction)
        fileMenu.addAction(associateAction)
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

    def _rebuild_surveys_menu(self, menu: QtWidgets.QMenu) -> None:
        """Fill File → Surveys with each saved survey (open standalone) + Manage."""
        menu.clear()
        recording = cast(RecordingWindow, self.panels["recording"])
        surveys = recording.saved_surveys()
        if surveys:
            for name, url in surveys.items():
                action = menu.addAction(name)
                action.setStatusTip(url)
                action.triggered.connect(partial(recording.open_survey_url, url, name))
        else:
            empty = menu.addAction("(no surveys saved)")
            empty.setEnabled(False)
        menu.addSeparator()
        manageAction = menu.addAction("Manage surveys…")
        manageAction.triggered.connect(recording.manage_surveys)

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

    ############################################################################
    # Settings export/import (settings.yaml) and event export
    ############################################################################

    def gather_settings(self) -> dict:
        """Collect each panel's parameters into one serializable settings dict.

        Audio devices are excluded on purpose (only the noise device routes today).
        """
        state: dict = {}
        for panel in self.panels.values():
            state.update(panel.gather_state())
        return state

    def apply_settings(self, state: dict) -> None:
        """Apply a settings ``state`` dict to every panel (each reads its own keys)."""
        for panel in self.panels.values():
            panel.apply_state(state)

    # ----- preferences / launch-file / file association ----------------------

    def _apply_preferences(self, prefs: dict) -> None:
        """Apply saved operator/UI preferences to the freshly built window.

        Runs after the menu + log handler exist and before the window is shown.
        Signals are blocked while setting checked states so the handlers don't
        fire during setup (which would log spurious lines or re-show the window).
        """
        # Always-on-top: set the flag directly (the toggled handler re-shows + logs).
        self._always_on_top_action.blockSignals(True)
        self._always_on_top_action.setChecked(bool(prefs["always_on_top"]))
        self._always_on_top_action.blockSignals(False)
        if prefs["always_on_top"]:
            self.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, True)

        # Log-preview levels (preview_handler exists now, built in init_main_window).
        wanted = preferences.names_to_levels(prefs.get("preview_levels", []))
        for level, action in self._preview_level_actions.items():
            action.blockSignals(True)
            action.setChecked(level in wanted)
            action.blockSignals(False)
        self._update_preview_levels()

        # Lights/theme startup state (no event marker; keep the switch in sync).
        lights_on = bool(prefs["lights_on"])
        self.lightswitchButton.blockSignals(True)
        self.lightswitchButton.setChecked(lights_on)
        self.lightswitchButton.blockSignals(False)
        self.set_lights(lights_on, send_marker=False)

        self._restore_geometry(prefs.get("window") or {})

    def _restore_geometry(self, window: dict) -> None:
        """Restore saved window size/position, ignoring fully off-screen positions."""
        width = int(window.get("w") or 640)
        height = int(window.get("h") or 560)
        self.resize(width, height)
        x, y = window.get("x"), window.get("y")
        if x is None or y is None:
            return
        rect = QtCore.QRect(int(x), int(y), width, height)
        screens = QtWidgets.QApplication.screens()
        if any(screen.availableGeometry().intersects(rect) for screen in screens):
            self.move(int(x), int(y))

    def _current_preferences(self) -> dict:
        """Snapshot the current operator/UI state for saving to preferences.yaml."""
        checked = {
            level
            for level, action in self._preview_level_actions.items()
            if action.isChecked()
        }
        # Start from the loaded prefs so flags we don't surface here (e.g. the
        # association first-run marker) are carried forward.
        prefs = dict(self._prefs)
        prefs.update(
            {
                "always_on_top": self._always_on_top_action.isChecked(),
                "lights_on": self.lights_on,
                "preview_levels": preferences.levels_to_names(checked),
                "window": {
                    "x": self.x(),
                    "y": self.y(),
                    "w": self.width(),
                    "h": self.height(),
                },
            }
        )
        return prefs

    def _load_initial_settings(self, settings_path: str) -> None:
        """Load a study file given on launch and apply it as the initial setup."""
        try:
            state, metadata = settings.load_settings(settings_path)
            state = settings.resolve_paths(state, Path(settings_path).parent)
        except (OSError, ValueError) as exc:
            self.show_error_popup("Could not open study file.", str(exc))
            return
        self._apply_loaded_settings(state, metadata)
        self.session.log_info_msg(f"Loaded study from {settings_path}")

    def associate_files(self) -> None:
        """Register SMACC as the Windows handler for .smacc files (packaged build)."""
        if not winassoc.is_associatable():
            QtWidgets.QMessageBox.information(
                self,
                "File association",
                "Associating .smacc files is only available in the installed "
                "Windows build of SMACC.",
            )
            return
        try:
            winassoc.register_smacc()
        except OSError as exc:
            self.show_error_popup("Could not associate .smacc files.", str(exc))
            return
        self.session.log_info_msg("Associated .smacc files with SMACC")
        QtWidgets.QMessageBox.information(
            self,
            "File association",
            "SMACC now handles .smacc files — double-click a study to open it.",
        )

    def _maybe_prompt_association(self) -> None:
        """Once, on the first packaged-build launch, offer to associate .smacc files."""
        if not winassoc.is_associatable() or self._prefs.get("association_prompted"):
            return
        self._prefs["association_prompted"] = True  # one-time, whatever they choose
        reply = QtWidgets.QMessageBox.question(
            self,
            "Associate .smacc files?",
            "Associate .smacc study files with SMACC so double-clicking one opens "
            "the app already configured?",
        )
        if reply == QtWidgets.QMessageBox.Yes:
            try:
                winassoc.register_smacc()
                self.session.log_info_msg("Associated .smacc files with SMACC")
            except OSError as exc:
                self.show_error_popup("Could not associate .smacc files.", str(exc))

    def export_settings(self) -> None:
        """Prompt for a path and write the current setup to a .smacc study file."""
        default = self.session.session_dir / "study.smacc"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export study (.smacc)", str(default), "SMACC study (*.smacc)"
        )
        if not path:
            return
        # Make referenced cue/noise paths relative to the chosen file when possible.
        portable = settings.relativize_paths(self.gather_settings(), Path(path).parent)
        try:
            settings.save_settings(path, portable, self.session.metadata)
        except (OSError, ValueError) as exc:
            self.show_error_popup("Could not export study.", str(exc))
            return
        self.session.log_info_msg(f"Exported study to {path}")

    def load_settings(self) -> None:
        """Prompt for a .smacc (or .yaml) study file and apply it."""
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Load study (.smacc)",
            str(data_directory),
            "SMACC study (*.smacc *.yaml *.yml)",
        )
        if not path:
            return
        try:
            state, metadata = settings.load_settings(path)
            state = settings.resolve_paths(state, Path(path).parent)
        except (OSError, ValueError) as exc:
            self.show_error_popup("Could not load study.", str(exc))
            return
        self._apply_loaded_settings(state, metadata)
        self.session.log_info_msg(f"Loaded study from {path}")

    def load_settings_from_log(self) -> None:
        """Load the initial or final settings recorded in a SMACC .log file."""
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load settings from log", str(sessions_directory), "SMACC log (*.log)"
        )
        if not path:
            return
        which = self._ask_initial_or_final()
        if which is None:
            return
        try:
            log_text = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            self.show_error_popup("Could not read log.", str(exc))
            return
        payload = bids.extract_settings_from_log(log_text, which)
        if payload is None:
            self.show_error_popup(
                f"No {which} settings found in that log.",
                "The log may predate settings recording, or the session may have "
                "ended before its final settings were written.",
            )
            return
        try:
            state, metadata = settings.parse_settings_mapping(payload)
        except ValueError as exc:
            self.show_error_popup("Could not load settings from log.", str(exc))
            return
        self._apply_loaded_settings(state, metadata)
        self.session.log_info_msg(f"Loaded {which} settings from {path}")

    def _ask_initial_or_final(self) -> str | None:
        """Ask whether to load the initial or final settings block (None on cancel)."""
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Load settings from log")
        box.setText("Load which settings snapshot from the log?")
        initial_btn = box.addButton("Initial", QtWidgets.QMessageBox.AcceptRole)
        final_btn = box.addButton("Final", QtWidgets.QMessageBox.AcceptRole)
        box.addButton(QtWidgets.QMessageBox.Cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked is initial_btn:
            return "initial"
        if clicked is final_btn:
            return "final"
        return None

    def _apply_loaded_settings(self, state: dict, metadata: dict) -> None:
        """Apply panel state and merge any non-empty loaded metadata into the session."""
        self.apply_settings(state)
        for key in ("subject", "session", "notes"):
            value = metadata.get(key)
            if value:
                self.session.metadata[key] = value

    def session_info(self) -> None:
        """Edit the session's optional subject/session/notes metadata."""
        meta = self.session.metadata
        dialog = SessionInfoDialog(
            meta.get("subject", ""),
            meta.get("session", ""),
            meta.get("notes", ""),
            parent=self,
        )
        if dialog.exec():
            subject, session, notes = dialog.get_inputs()
            # Updates the final log block and future exports; the initial block,
            # already written at startup, is intentionally left as-is.
            meta["subject"] = subject
            meta["session"] = session
            meta["notes"] = notes
            self.session.log_info_msg("Updated session metadata")

    def export_events_bids(self) -> None:
        """Convert this session's log to a BIDS events.tsv (+ JSON sidecar)."""
        if not self.session.log_path.is_file():
            self.show_error_popup("No log file to export yet.")
            return
        # Flush handlers so the on-disk log includes the latest events.
        for handler in self.session.logger.handlers:
            handler.flush()
        default = self.session.session_dir / self._events_basename()
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export events (BIDS)", str(default), "BIDS events (*.tsv)"
        )
        if not path:
            return
        self._write_events(self.session.log_path, Path(path))

    def export_events_from_log(self) -> None:
        """Convert any chosen SMACC .log file into a BIDS events.tsv (+ sidecar)."""
        log_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Choose a log file", str(sessions_directory), "SMACC log (*.log)"
        )
        if not log_path:
            return
        default = Path(log_path).with_suffix(".tsv")
        out_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export events (BIDS)", str(default), "BIDS events (*.tsv)"
        )
        if not out_path:
            return
        self._write_events(Path(log_path), Path(out_path))

    def _events_basename(self) -> str:
        """BIDS-style events name when subject+session are set, else a plain one."""
        subject = self.session.metadata.get("subject")
        session = self.session.metadata.get("session")
        if subject and session:
            return f"sub-{subject}_ses-{session}_events.tsv"
        return "events.tsv"

    def _write_events(self, log_path: Path, out_path: Path) -> None:
        """Parse ``log_path`` into BIDS events and write ``out_path`` (+ sidecar)."""
        try:
            log_text = log_path.read_text(encoding="utf-8")
            events = bids.log_to_events(log_text)
            bids.write_events_tsv(events, out_path)
            bids.write_events_json(out_path.with_suffix(".json"))
        except OSError as exc:
            self.show_error_popup("Could not export events.", str(exc))
            return
        self.session.log_info_msg(f"Exported {len(events)} events to {out_path}")

    @QtCore.pyqtSlot()
    def open_note_marker_dialogue(self):
        text, ok = QtWidgets.QInputDialog.getText(
            self, "Text Input Dialog", "Custom note (no commas):"
        )
        # self.subject_id.setValidator(QtGui.QIntValidator(0, 999)) # must be a 3-digit number
        if ok:  # True of OK button was hit, False otherwise (cancel button)
            portcode = self.session.portcodes["Note"]
            port_msg = f"Note [{text}]"
            self.session.send_event_marker(portcode, port_msg)

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
            # Persist operator/UI preferences for next launch (best-effort).
            preferences.save_preferences(preferences_path, self._current_preferences())
            self.session.log_info_msg("Program closed")
            # Record the final settings (incl. any mid-session edits) as the tail.
            self.session.end_log(self.gather_settings())
            event.accept()
        else:
            event.ignore()
