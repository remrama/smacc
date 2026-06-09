"""Initialize a new session and open the main interface."""

from __future__ import annotations

import logging
from functools import partial
from pathlib import Path
from typing import cast

import sounddevice as sd
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtMultimedia import QMediaDevices

from smacc import bids, devices, preferences, settings, winassoc

from .dialogs import EventCodesDialog, SessionInfoDialog, ask_initial_or_final
from .panels.audio import AudioCueWindow
from .panels.base import ModalityWindow
from .panels.devices import DevicesWindow
from .panels.events import EventsWindow
from .panels.intercom import IntercomWindow
from .panels.noise import NoiseWindow
from .panels.recording import RecordingWindow
from .panels.visual import VisualWindow
from .panels.volume import VolumeWindow
from .paths import LOGO_PATH, preferences_path
from .qtlog import QtLogHandler
from .session import SmaccSession
from .toolwindow import ToolWindow

#####################################
#########    Main window    #########
#####################################


class SmaccWindow(ToolWindow):
    """Main interface (a launcher-managed tool window; emits ``closed`` on close)."""

    def __init__(self, session: SmaccSession, settings_path: str | None = None) -> None:
        super().__init__()
        self.session = session
        # Design mode reuses this window to edit a settings file (no live run): the
        # log preview, lights, and recording are hidden/disabled, and the right
        # column becomes the settings-editor panel. Derived from the session.
        self.design = session.design
        # The .smacc this window loaded/edits (None until saved), so saving can
        # write back to it rather than prompting every time.
        self.settings_path = settings_path
        # The data directory recorded in the settings (the editor can change it).
        self.data_dir = session.data_dir
        # Operator/machine preferences (window/theme/log-preview); never raises.
        self._prefs = preferences.load_preferences(preferences_path)

        # Lights state drives the dark theme; sessions start with lights on.
        self.lights_on = True
        # Tool windows are positioned (cascading, right of this window) the first
        # time each is opened; reopening leaves them where the operator put them.
        self._positioned_panels: set[str] = set()

        # Modality windows, constructed up front (hidden) and opened on demand from
        # the launcher buttons. The Devices window owns all device selection; the
        # others show a read-only indicator and resolve their device from
        # session.devices, refreshed whenever the Devices window emits ``changed``.
        self.devices_window = DevicesWindow(self.session)
        self.panels: dict[str, ModalityWindow] = {
            "events": EventsWindow(self.session),
            "visual": VisualWindow(self.session),
            "audio": AudioCueWindow(self.session),
            "noise": NoiseWindow(self.session),
            "recording": RecordingWindow(self.session),
            "intercom": IntercomWindow(self.session),
            "devices": self.devices_window,
            "volume": VolumeWindow(self.session),
        }
        self.devices_window.changed.connect(self._refresh_device_indicators)
        # Hot-plug doorbell: Qt6's QMediaDevices fires when an audio device is added
        # or removed; that triggers an automatic rescan. Audio I/O stays on
        # sounddevice — QMediaDevices is used only as the "something changed" signal.
        self._media_devices = QMediaDevices(self)
        self._media_devices.audioOutputsChanged.connect(self._on_devices_hotplug)
        self._media_devices.audioInputsChanged.connect(self._on_devices_hotplug)

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
        """Sync the preview handler's visible levels to the level checkboxes."""
        # The designer has no log viewer (and no preview handler) to sync.
        if self.design:
            return
        self.preview_handler.enabled_levels = {
            level for level, box in self._preview_level_boxes.items() if box.isChecked()
        }

    def init_main_window(self):
        """Initialize SMACC's main window: menu/status bars and the widget grid."""
        self._build_menu_bar()
        self.statusBar().showMessage("Ready")

        # Two columns: the tools column (with the lights toggle pinned to the
        # bottom) and a right column — the live log preview in a session, or the
        # save panel in the editor. The editor also gets a banner spanning the top
        # so it's obvious nothing is being recorded. The menu is built first so the
        # preview-level checkbox dict it seeds is ready when the preview is built.
        central_layout = QtWidgets.QGridLayout()
        content_row = 0
        if self.design:
            central_layout.addWidget(self._build_editor_banner(), 0, 0, 1, 2)
            content_row = 1
        central_layout.addLayout(self._build_launcher_buttons(), content_row, 0)
        right_column = (
            self._build_editor_section()
            if self.design
            else self._build_log_viewer_section()
        )
        central_layout.addLayout(right_column, content_row, 1)
        central_layout.setColumnStretch(1, 1)  # the right column takes the extra width
        central_layout.setRowStretch(content_row, 1)  # content fills height, not banner
        central_widget = QtWidgets.QWidget()
        central_widget.setContentsMargins(5, 5, 5, 5)
        central_widget.setLayout(central_layout)
        self.setCentralWidget(central_widget)

        self.setWindowTitle("SMACC — Settings editor" if self.design else "SMACC")
        if LOGO_PATH.is_file():
            windowIcon = QtGui.QIcon(str(LOGO_PATH))
        else:
            windowIcon = self.style().standardIcon(
                QtWidgets.QStyle.StandardPixmap.SP_ToolBarHorizontalExtensionButton
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
        label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
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
        "devices": "Devices",
        "volume": "Volume",
    }

    # Hover/status-bar hints for each tool button (key -> tooltip).
    PANEL_TOOLTIPS = {
        "events": "Log experiment events and send their EEG trigger codes.",
        "visual": "Flash a BlinkStick LED as a visual cue.",
        "audio": "Play audio cues from a multi-slot cue board.",
        "noise": "Stream continuous background noise (colored noise or a file).",
        "recording": "Record a spoken dream report, monitor input level, open surveys.",
        "intercom": "Talk to and listen to the participant over the intercom.",
        "devices": "Bind devices to roles and route each modality to a role.",
        "volume": "Set a master output volume safety cap.",
    }

    def _build_launcher_buttons(self) -> QtWidgets.QLayout:
        """Build the 'Tools' column: panel launchers + the lights toggle.

        The lights toggle is pinned to the bottom of the column at a fixed,
        reasonable size (the stretch above absorbs extra height), so enlarging
        the window for a bigger log preview no longer stretches the toggle; it
        sends the lights event marker and flips the dark theme.
        """
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self._make_section_title("Tools"))
        for key, label in self.PANEL_LABELS.items():
            if key not in self.panels:
                continue
            button = QtWidgets.QPushButton(label, self)
            tip = self.PANEL_TOOLTIPS.get(key)
            if tip:
                button.setToolTip(tip)
                button.setStatusTip(tip)
            button.clicked.connect(partial(self._open_panel, key))
            layout.addWidget(button)
        # Extra height collects here, above the lightswitch, so the switch keeps
        # its fixed size (like the buttons) instead of growing with the window.
        layout.addStretch(1)

        # Connect the toggled signal only after setChecked so construction fires
        # no marker. Fixed height keeps the switch a steady size on resize.
        self.lightswitchButton = QtWidgets.QPushButton(self)
        self.lightswitchButton.setCheckable(True)
        self.lightswitchButton.setShortcut("L")  # still toggles with L
        self.lightswitchButton.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self.lightswitchButton.setFixedHeight(96)
        self.lightswitchButton.setStatusTip(
            "Toggle lights off/on (sends the lights event marker and switches theme)"
        )
        self.lightswitchButton.setChecked(True)
        self._refresh_lightswitch_label()
        self.lightswitchButton.toggled.connect(self.on_lightswitch_toggled)
        # Lights are a live-session concept. The editor hides the toggle (still
        # built, so preference application stays uniform); the stretch above
        # already pushes the tool buttons to the top in that mode.
        self.lightswitchButton.setVisible(not self.design)
        if not self.design:
            layout.addWidget(self.lightswitchButton)
        return layout

    def _open_panel(self, key: str) -> None:
        """Show and focus the modality window for ``key`` (placing it on first open)."""
        window = self.panels[key]
        if key not in self._positioned_panels:
            self._position_panel(window, key)
            self._positioned_panels.add(key)
        window.show()
        window.raise_()
        window.activateWindow()

    def _position_panel(self, window: QtWidgets.QWidget, key: str) -> None:
        """Cascade a tool window down-and-right of this window, in button order.

        Tools open to the right of the session window so they don't cover it,
        each stepped down-and-right from the last in the order the buttons
        appear. With more tools than fit vertically they overlap by design; the
        result is clamped to stay on-screen.
        """
        order = list(self.PANEL_LABELS)
        index = order.index(key) if key in order else 0
        frame = self.frameGeometry()
        x = frame.right() + 12 + index * 28
        y = frame.top() + index * 40
        screen = self.screen() or QtWidgets.QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            hint = window.sizeHint()
            w = max(window.width(), hint.width())
            h = max(window.height(), hint.height())
            x = max(avail.left(), min(x, avail.right() - w))
            y = max(avail.top(), min(y, avail.bottom() - h))
        window.move(x, y)

    def _build_menu_bar(self) -> None:
        """Build the consolidated File menu (About lives in the launcher's menu)."""
        style = self.style()
        assert style is not None
        quitAction = QtGui.QAction(
            style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_BrowserStop),
            "Close &editor" if self.design else "End sessio&n",
            self,
        )
        quitAction.setShortcut("Ctrl+Q")
        quitAction.setStatusTip(
            "Close the settings editor and return to the SMACC menu"
            if self.design
            else "End this session and return to the SMACC menu"
        )
        quitAction.triggered.connect(self.close)  # close goes to closeEvent

        sessionInfoAction = QtGui.QAction("Session &info…", self)
        sessionInfoAction.setStatusTip(
            "Edit optional subject/session/notes metadata recorded with the session."
        )
        sessionInfoAction.triggered.connect(self.session_info)

        eventCodesAction = QtGui.QAction("&Event codes…", self)
        eventCodesAction.setStatusTip(
            "View/edit event-marker port codes and what's logged vs. triggered."
        )
        eventCodesAction.triggered.connect(self.edit_event_codes)
        self._event_codes_action = eventCodesAction

        exportEventsAction = QtGui.QAction("&Export events (BIDS)…", self)
        exportEventsAction.setStatusTip(
            "Export this session's events log as a BIDS events.tsv."
        )
        exportEventsAction.triggered.connect(self.export_events_bids)

        # Always-on-top is an interface preference (also in the launcher's
        # Preferences). Built in both modes so _apply_preferences can set its state,
        # but only surfaced in a session's menu.
        alwaysOnTopAction = QtGui.QAction("Always on &top", self)
        alwaysOnTopAction.setStatusTip(
            "Keep the SMACC window above other applications."
        )
        alwaysOnTopAction.setCheckable(True)
        alwaysOnTopAction.setChecked(False)
        alwaysOnTopAction.toggled.connect(self.toggle_always_on_top)
        self._always_on_top_action = alwaysOnTopAction

        associateAction = QtGui.QAction("&Associate .smacc files (Windows)", self)
        associateAction.setStatusTip(
            "Register SMACC as the handler for .smacc files (double-click to open)."
        )
        associateAction.triggered.connect(self.associate_files)

        # Available in both modes (devices are configured in the editor and a session).
        refreshDevicesAction = QtGui.QAction("&Refresh devices", self)
        refreshDevicesAction.setShortcut("F5")
        refreshDevicesAction.setStatusTip(
            "Rescan for audio devices and BlinkSticks (e.g. after plugging one in)."
        )
        refreshDevicesAction.triggered.connect(self.refresh_all_devices)

        menu_bar = self.menuBar()
        assert menu_bar is not None
        fileMenu = menu_bar.addMenu("&File")
        assert fileMenu is not None
        # Log-preview level toggles live beside the preview now (built in
        # _build_log_viewer_section), not in this menu. Initialized empty here so
        # _apply_preferences can iterate it uniformly in both modes.
        self._preview_level_boxes: dict[int, QtWidgets.QCheckBox] = {}
        if self.design:
            self._build_editor_file_menu(fileMenu, sessionInfoAction, eventCodesAction)
        else:
            self._build_session_file_menu(
                fileMenu,
                sessionInfoAction,
                eventCodesAction,
                exportEventsAction,
                alwaysOnTopAction,
                associateAction,
            )
        fileMenu.addSeparator()
        fileMenu.addAction(refreshDevicesAction)
        fileMenu.addSeparator()
        fileMenu.addAction(quitAction)

    def _add_surveys_menu(self, fileMenu: QtWidgets.QMenu) -> None:
        """Add File → Surveys (rebuilt on show, since the saved list changes)."""
        surveysMenu = fileMenu.addMenu("Sur&veys")
        assert surveysMenu is not None
        surveysMenu.aboutToShow.connect(lambda: self._rebuild_surveys_menu(surveysMenu))

    def _build_editor_file_menu(self, fileMenu, sessionInfoAction, eventCodesAction):
        """Editor File menu: save/import settings + the config editors (no live run)."""
        saveAction = QtGui.QAction("&Save settings", self)
        saveAction.setShortcut("Ctrl+S")
        saveAction.setStatusTip("Save to the current .smacc (or choose a name if new).")
        saveAction.triggered.connect(self.save_settings_in_place)
        saveAsAction = QtGui.QAction("Save &as…", self)
        saveAsAction.setStatusTip("Save these settings to a new .smacc file.")
        saveAsAction.triggered.connect(self.export_settings)
        importAction = QtGui.QAction("&Import settings (.smacc)…", self)
        importAction.setStatusTip(
            "Load another .smacc's settings into the editor as a starting point."
        )
        importAction.triggered.connect(self.load_settings)
        importLogAction = QtGui.QAction("Import settings from &log…", self)
        importLogAction.setStatusTip(
            "Load the settings recorded in a SMACC .log into the editor."
        )
        importLogAction.triggered.connect(self.load_settings_from_log)
        for action in (saveAction, saveAsAction, importAction, importLogAction):
            fileMenu.addAction(action)
        fileMenu.addSeparator()
        fileMenu.addAction(sessionInfoAction)
        fileMenu.addAction(eventCodesAction)
        self._add_surveys_menu(fileMenu)

    def _build_session_file_menu(
        self,
        fileMenu,
        sessionInfoAction,
        eventCodesAction,
        exportEventsAction,
        alwaysOnTopAction,
        associateAction,
    ):
        """Session File menu: run-only. Author settings in the editor; analyze past
        runs from the launcher. Here you record events and export this run."""
        fileMenu.addAction(sessionInfoAction)
        fileMenu.addAction(eventCodesAction)
        self._add_surveys_menu(fileMenu)
        fileMenu.addSeparator()
        fileMenu.addAction(exportEventsAction)
        fileMenu.addSeparator()
        fileMenu.addAction(alwaysOnTopAction)
        fileMenu.addAction(associateAction)

    def _rebuild_surveys_menu(self, menu: QtWidgets.QMenu) -> None:
        """Fill File → Surveys with each saved survey (open standalone) + Manage."""
        menu.clear()
        recording = cast(RecordingWindow, self.panels["recording"])
        surveys = recording.saved_surveys()
        if surveys:
            for name, url in surveys.items():
                action = menu.addAction(name)
                assert action is not None
                action.setStatusTip(url)
                action.triggered.connect(partial(recording.open_survey_url, url, name))
        else:
            empty = menu.addAction("(no surveys saved)")
            assert empty is not None
            empty.setEnabled(False)
        menu.addSeparator()
        manageAction = menu.addAction("Manage surveys…")
        assert manageAction is not None
        manageAction.triggered.connect(recording.manage_surveys)

    def _build_log_viewer_section(self) -> QtWidgets.QLayout:
        """Build the log-preview panel: header, level toggles, and the live list."""
        titleLabel = self._make_section_title("Log preview")

        # Live preview list --> gets updated when events/messages are logged.
        logviewList = QtWidgets.QListWidget()
        logviewList.setAutoScroll(True)
        self.logviewList = logviewList

        # Route log records to the preview pane, filtered by the level toggles.
        self.preview_handler = QtLogHandler(logviewList)
        self.preview_handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s  %(levelname)s  %(message)s", datefmt="%H:%M:%S"
            )
        )
        self.session.logger.addHandler(self.preview_handler)

        # Level toggles in a single row between the header and the list, so a
        # level (e.g. DEBUG) can be flipped on the fly without a menu. The log
        # file always records every level regardless of these.
        levelRow = QtWidgets.QHBoxLayout()
        levelRow.setContentsMargins(0, 0, 0, 0)
        for levelname, levelno in (
            ("Debug", logging.DEBUG),
            ("Info", logging.INFO),
            ("Warning", logging.WARNING),
            ("Error", logging.ERROR),
            ("Critical", logging.CRITICAL),
        ):
            box = QtWidgets.QCheckBox(levelname, self)
            box.setChecked(levelno != logging.DEBUG)  # all but Debug, by default
            box.setStatusTip(
                "Show this level in the live preview (the log file records all levels)."
            )
            box.toggled.connect(self._update_preview_levels)
            levelRow.addWidget(box)
            self._preview_level_boxes[levelno] = box
        levelRow.addStretch(1)
        self._update_preview_levels()  # sync the handler to the boxes

        logviewLayout = QtWidgets.QVBoxLayout()
        logviewLayout.addWidget(titleLabel)
        logviewLayout.addLayout(levelRow)
        logviewLayout.addWidget(logviewList, 1)
        return logviewLayout

    def _build_editor_banner(self) -> QtWidgets.QLabel:
        """A prominent bar making clear the editor is configuring, not recording."""
        banner = QtWidgets.QLabel(
            "✎  Editing settings — no session is being recorded.", self
        )
        banner.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        banner.setStyleSheet(
            "background-color: #f0d000; color: black; font: bold 11pt;"
            " padding: 6px; border-radius: 4px;"
        )
        return banner

    def _build_editor_section(self) -> QtWidgets.QLayout:
        """Build the settings-editor right column: data directory + save actions.

        Replaces the live log viewer when this window is the settings editor. The
        tools column at the left configures the settings; here you pick the data
        directory (where runs go) and save it all to a ``.smacc`` file.
        """
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self._make_section_title("Settings editor"))
        info = QtWidgets.QLabel(
            "Configure each tool on the left (cues, noise, visual, events, …), set "
            "the data directory, then save to a <b>.smacc</b> settings file. Open it "
            "from the launcher to run a session with it."
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        layout.addSpacing(8)

        # Data directory: where sessions started from these settings are written.
        layout.addWidget(QtWidgets.QLabel("Data directory:", self))
        self.dataDirLabel = QtWidgets.QLabel(str(self.data_dir), self)
        self.dataDirLabel.setWordWrap(True)
        self.dataDirLabel.setStyleSheet("font-style: italic;")
        layout.addWidget(self.dataDirLabel)
        changeDirButton = QtWidgets.QPushButton("Change data directory…", self)
        changeDirButton.setStatusTip("Choose where sessions using these settings save.")
        changeDirButton.clicked.connect(self.change_data_dir)
        layout.addWidget(changeDirButton)
        layout.addSpacing(8)

        saveButton = QtWidgets.QPushButton("Save settings", self)
        saveButton.setStatusTip("Save to the current .smacc (or choose a name if new).")
        saveButton.clicked.connect(self.save_settings_in_place)
        saveAsButton = QtWidgets.QPushButton("Save as…", self)
        saveAsButton.setStatusTip("Save these settings to a new .smacc file.")
        saveAsButton.clicked.connect(self.export_settings)
        layout.addWidget(saveButton)
        layout.addWidget(saveAsButton)
        layout.addStretch(1)
        return layout

    def change_data_dir(self) -> None:
        """Pick the data directory recorded in these settings (editor only)."""
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Choose data directory", str(self.data_dir)
        )
        if path:
            self.data_dir = Path(path)
            self.dataDirLabel.setText(str(self.data_dir))

    def toggle_always_on_top(self, enabled: bool) -> None:
        """Toggle the window's always-on-top hint (from the View menu)."""
        self.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint, enabled)
        # Re-applying window flags hides the window on some platforms; re-show it.
        self.show()
        self.session.log_info_msg(
            f"Always-on-top {'enabled' if enabled else 'disabled'}"
        )

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
        """Switch the whole app between Qt's light and dark color schemes.

        Qt 6's Fusion style renders a polished palette for either scheme, so the
        lightswitch just asks for one — no hand-rolled palette needed. The app is
        forced to Light at startup (see ``__main__``); this only diverges from
        that when the operator turns the lights off.
        """
        QtGui.QGuiApplication.styleHints().setColorScheme(
            QtCore.Qt.ColorScheme.Dark if dark else QtCore.Qt.ColorScheme.Light
        )

    ############################################################################
    # Settings export/import (settings.yaml) and event export
    ############################################################################

    def gather_settings(self) -> dict:
        """Collect each panel's parameters into one serializable settings dict.

        Device roles + routing travel with the settings in a ``devices`` block (see
        :mod:`smacc.devices`), so a rig's whole device setup is restored on the next
        load; an unplugged bound device is flagged rather than silently dropped.
        """
        state: dict = {}
        for panel in self.panels.values():
            state.update(panel.gather_state())
        # Device roles/routing live on the session, not a panel; persist the block.
        state["devices"] = self.session.devices.to_dict()
        # The event-code registry isn't a panel; persist it at the window level.
        state["event_codes"] = self.session.event_codes_as_list()
        state["event_code_safe_max"] = self.session.event_code_safe_max
        # The data directory (where runs are written) travels with the settings;
        # the editor can repoint it, so read the window's copy, not the session's.
        state["data_directory"] = str(self.data_dir)
        return state

    def apply_settings(self, state: dict) -> None:
        """Apply a settings ``state`` dict to every panel (each reads its own keys).

        Soft interaction logging is suppressed while panels reload their widgets,
        so a study load doesn't spam the log with volume/color/device lines.
        """
        was_logging = self.session.log_interactions
        self.session.log_interactions = False
        self.session.missing_devices = []  # filled by the Devices reload below
        # Device roles/routing first, so panels resolve correctly (migrates old files).
        self.session.devices = devices.load(state)
        try:
            for panel in self.panels.values():
                panel.apply_state(state)
            # Apply the study's event-code registry (or defaults for a pre-v4
            # study with no event_codes) to the live session.
            self.session.set_event_codes(
                state.get("event_codes"), state.get("event_code_safe_max")
            )
            self._rebuild_events_panel()  # a loaded study may add/remove buttons
            self.devices_window.reload_from_config()  # sync widgets + flag missing
            self._refresh_device_indicators()
        finally:
            self.session.log_interactions = was_logging
        self._notify_missing_devices()

    def _rebuild_events_panel(self) -> None:
        """Rebuild the Event logging panel's buttons after the registry changes."""
        panel = self.panels.get("events")
        if isinstance(panel, EventsWindow):
            panel.rebuild()

    def _refresh_device_indicators(self) -> None:
        """Re-render every panel's device indicator from session.devices."""
        for panel in self.panels.values():
            panel.refresh_device_indicator()

    def _on_devices_hotplug(self) -> None:
        """A device was added/removed: quietly rescan when nothing is streaming.

        Skipped while audio is live (a PortAudio re-init would cut it); the operator
        can use File ▸ Refresh devices once idle.
        """
        if any(panel.is_streaming() for panel in self.panels.values()):
            return
        was_logging = self.session.log_interactions
        self.session.log_interactions = False
        try:
            sd._terminate()
            sd._initialize()  # rebuild PortAudio's cached device list
            self.devices_window.refresh_device_lists()
            self._refresh_device_indicators()
        except Exception:
            return
        finally:
            self.session.log_interactions = was_logging
        self.session.log_info_msg("Devices changed; lists rescanned")

    def _notify_missing_devices(self) -> None:
        """Surface, once, any saved devices that weren't connected when settings loaded.

        Skipped in the designer, where a study is often built on a different machine
        than the rig, so missing devices there are expected and not worth a popup.
        """
        missing = self.session.missing_devices
        if not missing or self.design:
            return
        items = "\n".join(f"  • {entry}" for entry in missing)
        self.session.show_info_popup(
            "Some saved devices aren’t connected.",
            "These devices from the settings file weren’t found:\n"
            f"{items}\n\n"
            "Plug them in and choose File ▸ Refresh devices, or pick another device.",
            parent=self,
        )

    def refresh_all_devices(self) -> None:
        """Rescan for devices plugged in after launch (File ▸ Refresh devices, F5).

        BlinkSticks are a live USB scan, so they are always rescanned. PortAudio
        caches its device list at initialization, so audio devices are only picked
        up by re-initializing it — which invalidates open streams, so that is done
        only while nothing is playing, recording, or monitoring.
        """
        was_logging = self.session.log_interactions
        self.session.log_interactions = False  # don't spam logs as lists repopulate
        audio_active = any(panel.is_streaming() for panel in self.panels.values())
        try:
            if not audio_active:
                sd._terminate()
                sd._initialize()  # rebuild PortAudio's cached device list
            self.devices_window.refresh_device_lists()
            self._refresh_device_indicators()
        except Exception as exc:  # PortAudio re-init can fail on odd configs
            self.session.show_error_popup(
                "Could not rescan devices.", str(exc), parent=self
            )
        finally:
            self.session.log_interactions = was_logging
        if audio_active:
            self.session.show_info_popup(
                "Audio devices not fully rescanned.",
                "BlinkSticks were rescanned. To rescan audio devices too, stop "
                "playback, recording, and the level meter, then choose Refresh "
                "devices again.",
                parent=self,
            )
        else:
            self.session.log_info_msg("Refreshed devices")

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
            self.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint, True)

        # Log-preview levels (the level checkboxes exist now, built in
        # init_main_window). Empty in the editor, which has no preview.
        wanted = preferences.names_to_levels(prefs.get("preview_levels", []))
        for level, box in self._preview_level_boxes.items():
            box.blockSignals(True)
            box.setChecked(level in wanted)
            box.blockSignals(False)
        self._update_preview_levels()

        # Lights always start ON each launch — the dark theme is per-session
        # state, not a saved preference. Keep the switch in sync, fire no marker.
        self.lightswitchButton.blockSignals(True)
        self.lightswitchButton.setChecked(True)
        self.lightswitchButton.blockSignals(False)
        self.set_lights(True, send_marker=False)

        # The editor doesn't persist its own geometry; give it a compact default
        # rather than inheriting the (larger) saved session window size.
        if self.design:
            self.resize(640, 460)
        else:
            self._restore_geometry(prefs.get("window") or {})

    def _restore_geometry(self, window: dict) -> None:
        """Restore saved window size/position, ignoring fully off-screen positions."""
        width = int(window.get("w") or 640)
        height = int(window.get("h") or 560)
        self.resize(width, height)
        x, y = window.get("x"), window.get("y")
        if x is None or y is None:
            self._move_to_default_position()  # first run: sit by the launcher
            return
        rect = QtCore.QRect(int(x), int(y), width, height)
        screens = QtWidgets.QApplication.screens()
        if any(screen.availableGeometry().intersects(rect) for screen in screens):
            self.move(int(x), int(y))

    def _move_to_default_position(self) -> None:
        """Place a first-run session window just down-right of the launcher.

        The launcher opens near the upper-left of the screen (see ``launcher``);
        with no saved geometry the session window opens slightly inside that, so
        the two read as a stack and there's room to the right for tool windows.
        """
        screen = self.screen() or QtWidgets.QApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        self.move(avail.left() + 88, avail.top() + 88)

    def _preference_changes(self) -> dict:
        """The operator/UI keys this window owns, for a non-clobbering prefs update.

        Only the keys the session window manages are returned; merging them with
        :func:`preferences.update_preferences` leaves other writers' keys (e.g. the
        launcher's recent-settings list) untouched.
        """
        checked = {
            level for level, box in self._preview_level_boxes.items() if box.isChecked()
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
        """Load a settings file given on launch and apply it as the initial setup."""
        try:
            state, metadata = settings.load_settings(settings_path)
            state = settings.resolve_paths(state, Path(settings_path).parent)
        except (OSError, ValueError) as exc:
            self.show_error_popup("Could not open settings file.", str(exc))
            return
        self._apply_loaded_settings(state, metadata)
        self.session.log_info_msg(f"Loaded settings from {settings_path}")

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
            "SMACC now handles .smacc files — double-click a settings file to open it.",
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
            "Associate .smacc settings files with SMACC so double-clicking one opens "
            "the app already configured?",
        )
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            try:
                winassoc.register_smacc()
                self.session.log_info_msg("Associated .smacc files with SMACC")
            except OSError as exc:
                self.show_error_popup("Could not associate .smacc files.", str(exc))

    def save_settings_in_place(self) -> bool:
        """Save to the current .smacc without prompting; fall back to Save-As if new.

        Returns True if the settings were written, False if cancelled.
        """
        if self.settings_path:
            return self._write_settings(self.settings_path)
        return self.export_settings()

    def export_settings(self) -> bool:
        """Prompt for a path (Save-As) and write the settings there. Returns success."""
        # Default to the file we loaded, else a settings.smacc beside the data dir.
        default = self.settings_path or str(self.data_dir / "settings.smacc")
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save settings (.smacc)", str(default), "SMACC settings (*.smacc)"
        )
        if not path:
            return False
        return self._write_settings(path)

    def _write_settings(self, path: str) -> bool:
        """Write the current settings to ``path`` (relativizing paths). Returns success."""
        # Make referenced cue/noise/data paths relative to the file when possible.
        portable = settings.relativize_paths(self.gather_settings(), Path(path).parent)
        try:
            settings.save_settings(path, portable, self.session.metadata)
        except (OSError, ValueError) as exc:
            self.show_error_popup("Could not save settings.", str(exc))
            return False
        self.settings_path = path  # subsequent saves update this file
        self.session.log_info_msg(f"Saved settings to {path}")
        # Status-bar confirmation: the editor has no log viewer to show the line.
        status_bar = self.statusBar()
        assert status_bar is not None
        status_bar.showMessage(f"Saved settings to {Path(path).name}", 5000)
        return True

    def load_settings(self) -> None:
        """Prompt for a .smacc (or .yaml) settings file and apply it."""
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Open settings (.smacc)",
            str(self.session.data_dir),
            "SMACC settings (*.smacc *.yaml *.yml)",
        )
        if not path:
            return
        try:
            state, metadata = settings.load_settings(path)
            state = settings.resolve_paths(state, Path(path).parent)
        except (OSError, ValueError) as exc:
            self.show_error_popup("Could not open settings.", str(exc))
            return
        self._apply_loaded_settings(state, metadata)
        self.session.log_info_msg(f"Loaded settings from {path}")

    def load_settings_from_log(self) -> None:
        """Load the initial or final settings recorded in a SMACC .log file."""
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Load settings from log",
            str(self.session.data_dir),
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
        return ask_initial_or_final(self, title="Load settings from log")

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
            box = QtWidgets.QMessageBox(self)
            box.setWindowTitle("Close editor")
            box.setText("Save changes to the settings before closing?")
            box.setStandardButtons(
                QtWidgets.QMessageBox.StandardButton.Save
                | QtWidgets.QMessageBox.StandardButton.Discard
                | QtWidgets.QMessageBox.StandardButton.Cancel
            )
            box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Save)
            choice = box.exec()
            if choice == QtWidgets.QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            if (
                choice == QtWidgets.QMessageBox.StandardButton.Save
                and not self.save_settings_in_place()
            ):
                event.ignore()  # save was cancelled/failed → keep the editor open
                return
            # No run to finalize and no operator prefs to write from the editor.
            self._teardown_panels()
            self.session.close()
            event.accept()
            self.closed.emit()
            return

        response = QtWidgets.QMessageBox.question(
            self, "End session", "End this session and return to the SMACC menu?"
        )
        if response == QtWidgets.QMessageBox.StandardButton.Yes:
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
