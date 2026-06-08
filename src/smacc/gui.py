"""Initialize a new session and open the main interface."""

from __future__ import annotations

import logging
from functools import partial
from pathlib import Path
from typing import cast

from PyQt5 import QtCore, QtGui, QtWidgets

from smacc import bids, preferences, settings, winassoc

from .config import VERSION
from .dialogs import EventCodesDialog, SessionInfoDialog
from .panels.audio import AudioCueWindow
from .panels.base import ModalityWindow
from .panels.events import EventsWindow
from .panels.intercom import IntercomWindow
from .panels.noise import NoiseWindow
from .panels.recording import RecordingWindow
from .panels.visual import VisualWindow
from .paths import LOGO_PATH, preferences_path, studies_directory
from .qtlog import QtLogHandler
from .session import SmaccSession

#####################################
#########    Main window    #########
#####################################


class SmaccWindow(QtWidgets.QMainWindow):
    """Main interface."""

    # Emitted after a session is ended and the window closed, so the launcher can
    # bring itself back (the launcher is the app's persistent root window).
    closed = QtCore.pyqtSignal()

    def __init__(self, session: SmaccSession, settings_path: str | None = None) -> None:
        super().__init__()
        self.session = session
        # Design mode reuses this window to configure a study (no live run): the
        # log viewer, lights, and recording are hidden/disabled, and the right
        # column becomes a study-designer panel. Derived from the session.
        self.design = session.design
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
            "events": EventsWindow(self.session),
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

        # The designer records no run, so it skips the log header, the file
        # association prompt, and interaction logging — it only edits config.
        if not self.design:
            # Panels (and any launch-file overrides) are in place, so capture the
            # initial state into the log header (also emits the "Opened SMACC" line).
            self.session.begin_log(self.gather_settings())
            self._maybe_prompt_association()
            # Startup widget setup is done; from here on, log soft interactions.
            self.session.log_interactions = True

    def show_error_popup(self, short_msg, long_msg=None):
        """Show an error dialog parented to this window (logs via the session)."""
        self.session.show_error_popup(short_msg, long_msg, parent=self)

    def _update_preview_levels(self) -> None:
        """Sync the preview handler's visible levels to the menu checkboxes."""
        # The designer has no log viewer (and no preview handler) to sync.
        if self.design:
            return
        self.preview_handler.enabled_levels = {
            level
            for level, action in self._preview_level_actions.items()
            if action.isChecked()
        }

    def init_main_window(self):
        """Initialize SMACC's main window: menu/status bars and the widget grid."""
        self._build_menu_bar()
        self.statusBar().showMessage("Ready")

        # Two columns: the tools column (with the lights toggle filling the bottom)
        # and a right column — the live log viewer in a session, or the save/open
        # study panel in the designer. The menu is built first so the log-viewer
        # panel can sync the preview handler to the Log preview menu checkboxes.
        central_layout = QtWidgets.QGridLayout()
        central_layout.addLayout(self._build_launcher_buttons(), 0, 0)
        right_column = (
            self._build_designer_section()
            if self.design
            else self._build_log_viewer_section()
        )
        central_layout.addLayout(right_column, 0, 1)
        central_layout.setColumnStretch(1, 1)  # the right column takes the extra width
        central_widget = QtWidgets.QWidget()
        central_widget.setContentsMargins(5, 5, 5, 5)
        central_widget.setLayout(central_layout)
        self.setCentralWidget(central_widget)

        self.setWindowTitle("SMACC — Study designer" if self.design else "SMACC")
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
        "events": "Event logging",
        "visual": "Visual stimulation",
        "audio": "Audio cue",
        "noise": "Noise machine",
        "recording": "Dream recording",
        "intercom": "Intercom",
    }

    def _build_launcher_buttons(self) -> QtWidgets.QLayout:
        """Build the 'Open tools' column: panel launchers + the lights toggle.

        The lights toggle sits at the bottom and expands to fill the column's
        leftover height (so it lines up with the log viewer); it sends the lights
        event marker and flips the dark theme.
        """
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self._make_section_title("Open tools"))
        for key, label in self.PANEL_LABELS.items():
            if key not in self.panels:
                continue
            button = QtWidgets.QPushButton(label, self)
            button.clicked.connect(partial(self._open_panel, key))
            layout.addWidget(button)
        layout.addSpacing(8)

        # Connect the toggled signal only after setChecked so construction fires
        # no marker. Expanding vertical policy + stretch fills the empty space.
        self.lightswitchButton = QtWidgets.QPushButton(self)
        self.lightswitchButton.setCheckable(True)
        self.lightswitchButton.setShortcut("L")  # still toggles with L
        self.lightswitchButton.setSizePolicy(
            QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding
        )
        self.lightswitchButton.setMinimumHeight(64)
        self.lightswitchButton.setStatusTip(
            "Toggle lights off/on (sends the lights event marker and switches theme)"
        )
        self.lightswitchButton.setChecked(True)
        self._refresh_lightswitch_label()
        self.lightswitchButton.toggled.connect(self.on_lightswitch_toggled)
        # Lights are a live-session concept; the designer hides the toggle (it's
        # still built so preference application stays uniform across both modes).
        self.lightswitchButton.setVisible(not self.design)
        layout.addWidget(self.lightswitchButton, 1)
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
            self.style().standardIcon(QtWidgets.QStyle.SP_BrowserStop),
            "Close &designer" if self.design else "End sessio&n",
            self,
        )
        quitAction.setShortcut("Ctrl+Q")
        quitAction.setStatusTip(
            "Close the study designer and return to the SMACC menu"
            if self.design
            else "End this session and return to the SMACC menu"
        )
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

        eventCodesAction = QtWidgets.QAction("&Event codes…", self)
        eventCodesAction.setStatusTip(
            "View/edit event-marker port codes and what's logged vs. triggered."
        )
        eventCodesAction.triggered.connect(self.edit_event_codes)
        self._event_codes_action = eventCodesAction

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
        fileMenu.addAction(eventCodesAction)
        # File -> Surveys: open any saved survey standalone (not tied to a dream
        # report). Rebuilt each time it opens, since the saved list changes as
        # surveys are added/edited/removed.
        surveysMenu = fileMenu.addMenu("Sur&veys")
        surveysMenu.aboutToShow.connect(lambda: self._rebuild_surveys_menu(surveysMenu))
        # Exporting events needs a recorded run, so it's session-only; the designer
        # omits it (events can still be exported later from the Analyze menu).
        self._preview_level_actions: dict[int, QtWidgets.QAction] = {}
        if not self.design:
            fileMenu.addSeparator()
            fileMenu.addAction(exportEventsAction)
            fileMenu.addAction(exportEventsFromLogAction)
        fileMenu.addSeparator()
        fileMenu.addAction(alwaysOnTopAction)
        fileMenu.addAction(associateAction)
        # File -> Log preview: pick which log levels show in the preview pane.
        # Everything is always written to the log file regardless of these. The
        # designer has no log viewer, so it omits this menu (and keeps the actions
        # map empty, which _apply_preferences tolerates).
        if not self.design:
            fileMenu.addSeparator()
            previewMenu = fileMenu.addMenu("Log preview")
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

    def _build_designer_section(self) -> QtWidgets.QLayout:
        """Build the study-designer right column: guidance plus save/open actions.

        Replaces the live log viewer when this window is a study designer. The
        tools column at the left configures the study; these buttons persist it to
        the study's ``study.smacc`` (or load an existing config to start from).
        """
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self._make_section_title("Study designer"))
        info = QtWidgets.QLabel(
            "Configure each tool on the left (cues, noise, visual, events, …), "
            "then save the setup to this study's <b>study.smacc</b>. Start a "
            "session from the menu to record with it."
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        layout.addSpacing(8)
        saveButton = QtWidgets.QPushButton("Save study (.smacc)", self)
        saveButton.setStatusTip("Save the current setup to this study's study.smacc.")
        saveButton.clicked.connect(self.export_settings)
        openButton = QtWidgets.QPushButton("Open study (.smacc)…", self)
        openButton.setStatusTip("Load an existing study config into the designer.")
        openButton.clicked.connect(self.load_settings)
        layout.addWidget(saveButton)
        layout.addWidget(openButton)
        layout.addStretch(1)
        return layout

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
            self.session.emit_event("LightsOn" if lights_on else "LightsOff")

    def _refresh_lightswitch_label(self) -> None:
        """Sync the lightswitch text/style to the current state.

        Three centered lines — state, a sun/moon glyph, and the action — to suit
        the narrow single-column button.
        """
        if self.lights_on:
            self.lightswitchButton.setText("Lights are ON\n☀️\nclick to turn OFF")
            self.lightswitchButton.setStyleSheet(
                "font: bold 13pt; padding: 8px; background-color: #f0d000; color: black;"
            )
        else:
            self.lightswitchButton.setText(
                "Lights are OFF\n\U0001f319\nclick to turn ON"
            )
            self.lightswitchButton.setStyleSheet(
                "font: bold 13pt; padding: 8px; background-color: #303030; color: #dddddd;"
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
        # The event-code registry isn't a panel; persist it at the window level.
        state["event_codes"] = self.session.event_codes_as_list()
        state["event_code_safe_max"] = self.session.event_code_safe_max
        return state

    def apply_settings(self, state: dict) -> None:
        """Apply a settings ``state`` dict to every panel (each reads its own keys).

        Soft interaction logging is suppressed while panels reload their widgets,
        so a study load doesn't spam the log with volume/color/device lines.
        """
        was_logging = self.session.log_interactions
        self.session.log_interactions = False
        try:
            for panel in self.panels.values():
                panel.apply_state(state)
            # Apply the study's event-code registry (or defaults for a pre-v4
            # study with no event_codes) to the live session.
            self.session.set_event_codes(
                state.get("event_codes"), state.get("event_code_safe_max")
            )
            self._rebuild_events_panel()  # a loaded study may add/remove buttons
        finally:
            self.session.log_interactions = was_logging

    def _rebuild_events_panel(self) -> None:
        """Rebuild the Event logging panel's buttons after the registry changes."""
        panel = self.panels.get("events")
        if isinstance(panel, EventsWindow):
            panel.rebuild()

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

        # Lights always start ON each launch — the dark theme is per-session
        # state, not a saved preference. Keep the switch in sync, fire no marker.
        self.lightswitchButton.blockSignals(True)
        self.lightswitchButton.setChecked(True)
        self.lightswitchButton.blockSignals(False)
        self.set_lights(True, send_marker=False)

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

    def _preference_changes(self) -> dict:
        """The operator/UI keys this window owns, for a non-clobbering prefs update.

        Only the keys the session window manages are returned; merging them with
        :func:`preferences.update_preferences` leaves other writers' keys (e.g. the
        launcher's recent-studies list) untouched.
        """
        checked = {
            level
            for level, action in self._preview_level_actions.items()
            if action.isChecked()
        }
        return {
            "always_on_top": self._always_on_top_action.isChecked(),
            "preview_levels": preferences.levels_to_names(checked),
            "window": {
                "x": self.x(),
                "y": self.y(),
                "w": self.width(),
                "h": self.height(),
            },
        }

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
        # Persist the one-time flag immediately so it survives even if multiple
        # windows write preferences this run (the launcher also writes recents).
        preferences.update_preferences(preferences_path, {"association_prompted": True})
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
        # Default to this study's own study.smacc at its root, where it auto-loads
        # next launch and its relative cue paths resolve against the study folder.
        default = self.session.study.config_path
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
        # Status-bar confirmation: the designer has no log viewer to show the line.
        self.statusBar().showMessage(f"Saved study to {Path(path).name}", 5000)

    def load_settings(self) -> None:
        """Prompt for a .smacc (or .yaml) study file and apply it."""
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Load study (.smacc)",
            str(studies_directory),
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
            self,
            "Load settings from log",
            str(self.session.study.sessions_dir),
            "SMACC log (*.log)",
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

    def edit_event_codes(self) -> None:
        """Open the event-code editor; apply edits live and log every change.

        The editor stays available throughout a session (there's no reliable
        lock point yet), so each change is logged loudly (WARNING) to keep the
        code map traceable for the session even if it changes mid-study.
        """
        before = {e.key: e for e in self.session.events.values()}
        dialog = EventCodesDialog(
            list(self.session.events.values()),
            self.session.event_code_safe_max,
            parent=self,
        )
        if not dialog.exec():
            return
        new_events = dialog.get_events()
        safe_max = dialog.get_safe_max()
        new_by_key = {e.key: e for e in new_events}
        for event in new_events:
            old = before.get(event.key)
            if old is None:
                self.session.logger.warning(
                    f"Event added: {event.label} (code {event.code})"
                )
                continue
            changes = []
            if old.code != event.code:
                changes.append(f"code {old.code}->{event.code}")
            if old.trigger != event.trigger:
                changes.append(f"trigger {'on' if event.trigger else 'off'}")
            if old.preview != event.preview:
                changes.append(f"preview {'on' if event.preview else 'off'}")
            if old.increment != event.increment:
                changes.append(f"increment {'on' if event.increment else 'off'}")
            if changes:
                self.session.logger.warning(
                    f"Port code changed: {event.label} ({', '.join(changes)})"
                )
        for key, old in before.items():
            if key not in new_by_key:
                self.session.logger.warning(f"Event removed: {old.label}")
        if safe_max != self.session.event_code_safe_max:
            self.session.logger.warning(
                f"Event-code safe max changed: "
                f"{self.session.event_code_safe_max} -> {safe_max}"
            )
        self.session.events = new_by_key
        self.session.event_code_safe_max = safe_max
        self._rebuild_events_panel()

    def export_events_bids(self) -> None:
        """Convert this session's log to a BIDS events.tsv (+ JSON sidecar)."""
        # log_path/session_dir are None only in design mode, where this action is
        # not offered; guard anyway so the types stay honest.
        log_path = self.session.log_path
        session_dir = self.session.session_dir
        if log_path is None or session_dir is None or not log_path.is_file():
            self.show_error_popup("No log file to export yet.")
            return
        # Flush handlers so the on-disk log includes the latest events.
        for handler in self.session.logger.handlers:
            handler.flush()
        default = session_dir / self._events_basename()
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export events (BIDS)", str(default), "BIDS events (*.tsv)"
        )
        if not path:
            return
        self._write_events(log_path, Path(path))

    def export_events_from_log(self) -> None:
        """Convert any chosen SMACC .log file into a BIDS events.tsv (+ sidecar)."""
        log_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Choose a log file",
            str(self.session.study.sessions_dir),
            "SMACC log (*.log)",
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
            count = bids.convert_log_file(log_path, out_path)
        except OSError as exc:
            self.show_error_popup("Could not export events.", str(exc))
            return
        self.session.log_info_msg(f"Exported {count} events to {out_path}")

    def _teardown_panels(self) -> None:
        """Stop and close every modality window (called when this window closes)."""
        for panel in self.panels.values():
            panel._quitting = True
            panel.cleanup()
            panel.close()

    def closeEvent(self, event):
        """End the session (or close the designer) and return control to the launcher.

        closeEvent is a default method used in pyqt to close, so this overrides it.
        Closing no longer quits the app — it ends this window and emits ``closed`` so
        the launcher (the persistent root window) can reappear.
        """
        if self.design:
            confirmed = (
                QtWidgets.QMessageBox.question(
                    self,
                    "Close designer",
                    "Close the study designer and return to the menu?\n\n"
                    "Save the study first if you have unsaved changes.",
                )
                == QtWidgets.QMessageBox.Yes
            )
            if not confirmed:
                event.ignore()
                return
            # No run to finalize and no operator prefs to write from the designer.
            self._teardown_panels()
            self.session.close()
            event.accept()
            self.closed.emit()
            return

        response = QtWidgets.QMessageBox.question(
            self, "End session", "End this session and return to the SMACC menu?"
        )
        if response == QtWidgets.QMessageBox.Yes:
            self._teardown_panels()
            # Persist this window's operator/UI preferences for next launch, merging
            # so we don't clobber keys other windows own (best-effort, never raises).
            preferences.update_preferences(preferences_path, self._preference_changes())
            self.session.log_info_msg("Session ended")
            # Record the final settings (incl. any mid-session edits) as the tail.
            self.session.end_log(self.gather_settings())
            # Detach this window's preview handler and release the session's log
            # handler + outlet so the next session in this process starts clean.
            self.session.logger.removeHandler(self.preview_handler)
            self.session.close()
            event.accept()
            self.closed.emit()
        else:
            event.ignore()
