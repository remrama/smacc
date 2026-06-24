"""Initialize a new session and open the main interface."""

from __future__ import annotations

import logging
from functools import partial
from pathlib import Path
from typing import cast

import sounddevice as sd
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtMultimedia import QMediaDevices

from smacc import (
    biocals,
    devices,
    hue,
    preferences,
    settings,
    triggers,
    windowstate,
)

from .dialogs import (
    SessionInfoDialog,
)
from .fonts import mono_font
from .panels.audio import AudioCueWindow
from .panels.base import PanelWindow
from .panels.biocals import BiocalsWindow
from .panels.chat import (
    ChatPresets,
    ChatTranscript,
    ChatWindow,
    ParticipantChatWindow,
)
from .panels.devices import DevicesWindow
from .panels.events import EventsWindow
from .panels.markers import MarkersWindow
from .panels.noise import NoiseWindow
from .panels.recording import RecordingWindow
from .panels.visual import VisualWindow
from .panels.volume import VolumeWindow
from .paths import (
    BIOCALS_DIR,
    BUNDLED_BIOCALS_DIR,
    LOGO_PATH,
    is_default_settings,
    preferences_path,
)
from .qtlog import QtLogHandler
from .session import SmaccSession
from .studyconfig import StudyConfig
from .toolwindow import ToolWindow

# The live log preview's record format; the time field's strftime (24h/12h) comes
# from preferences (preferences.CLOCK_FORMATS) and can be flipped at runtime.
_PREVIEW_LOG_FORMAT = "%(asctime)s  %(levelname)s  %(message)s"

#####################################
#########    Main window    #########
#####################################


class SmaccWindow(ToolWindow):
    """Main interface (a launcher-managed tool window; emits ``closed`` on close)."""

    def __init__(self, session: SmaccSession, settings_path: str | None = None) -> None:
        super().__init__()
        self.session = session
        # A window built over a headless session (tests, screenshots) records no run:
        # it skips the log header, geometry/rig persistence, and the close prompt, but
        # is otherwise an ordinary session window. Authoring a study is the Study
        # Editor's job now (smacc.studyeditor), not a mode of this window.
        # The .smacc this window loaded (None until Save-As), so a save can write
        # back to it rather than prompting every time.
        self.settings_path = settings_path
        # The data directory recorded in the settings (where this session's runs go).
        self.data_dir = session.data_dir
        # Machine-local preferences (per-window geometry + launcher state); the
        # interface choices that used to live here now travel with the study. Loading
        # never raises. Read once at construction; each window saves its own geometry.
        self._prefs = preferences.load_preferences(preferences_path)

        # Lights state drives the dark theme; sessions start with lights on.
        self.lights_on = True
        # Tool windows are positioned (cascading, right of this window) the first
        # time each is opened; reopening leaves them where the operator put them.
        self._positioned_panels: set[str] = set()

        # Tool windows, constructed up front (hidden) and opened on demand from
        # the launcher buttons. The Devices window owns all device selection; the
        # others show a read-only indicator and resolve their device from
        # session.devices, refreshed whenever the Devices window emits ``changed``.
        self.devices_window = DevicesWindow(self.session)
        # The text chat's conversation, shared by its two views: the experimenter's
        # section in the Chat window and the participant-facing window (#92). The
        # quick-reply presets (#112) are shared the same way; the Chat window
        # persists them with the study.
        chat_transcript = ChatTranscript(self)
        chat_presets = ChatPresets(self)
        self.panels: dict[str, PanelWindow] = {
            "events": EventsWindow(self.session),
            "biocals": BiocalsWindow(self.session),
            "visual": VisualWindow(self.session),
            "audio": AudioCueWindow(self.session),
            "noise": NoiseWindow(self.session),
            "recording": RecordingWindow(self.session),
            "chat": ChatWindow(self.session, chat_transcript, chat_presets),
            # No launcher button (absent from PANEL_LABELS): opened via the Chat
            # window's "Pass keyboard" button, which also hands it keyboard focus.
            "participant_chat": ParticipantChatWindow(
                self.session, chat_transcript, chat_presets
            ),
            "devices": self.devices_window,
            "markers": MarkersWindow(self.session),
            "volume": VolumeWindow(self.session),
        }
        cast(ChatWindow, self.panels["chat"]).open_participant_chat.connect(
            partial(self._open_panel, "participant_chat")
        )
        # The Markers window owns all marker configuration (registry + transport);
        # applying it re-renders the registry's other consumers (the event grid),
        # and a grid-side Add event… refreshes the Markers staging in turn.
        markers_window = cast(MarkersWindow, self.panels["markers"])
        markers_window.changed.connect(self._refresh_registry_views)
        cast(EventsWindow, self.panels["events"]).registry_changed.connect(
            markers_window.reload_from_session
        )
        self.devices_window.changed.connect(self._refresh_device_indicators)
        # An operator binding edit persists to the rig profile, so binding a device
        # once is reused by every later study on this machine (#300). This uses the
        # dedicated ``binding_edited`` signal (only a manual equipment-binding edit),
        # not ``changed`` — which also fires on autobind and would otherwise clobber
        # the rig's manual bindings with the autobound defaults mid-load.
        self.devices_window.binding_edited.connect(self._persist_rig_bindings)
        # The Devices window's Refresh button (and its F5 shortcut) runs this rescan
        # (PortAudio re-init + BlinkStick scan); it's the only entry point now.
        self.devices_window.refresh_requested.connect(self.refresh_all_devices)
        # Hot-plug doorbell: Qt6's QMediaDevices fires when an audio device is added
        # or removed; that triggers an automatic rescan. Audio I/O stays on
        # sounddevice — QMediaDevices is used only as the "something changed" signal.
        # Debounced through a single-shot timer: Windows fires these in bursts
        # (dozens within a second, e.g. when a Bluetooth device renegotiates or a
        # stream opens/closes), and each rescan tears PortAudio down and back up —
        # doing that dozens of times back-to-back has crashed the app mid-burst.
        # Restarting the timer per signal coalesces a burst into one rescan.
        self._media_devices = QMediaDevices(self)
        self._hotplug_timer = QtCore.QTimer(self)
        self._hotplug_timer.setSingleShot(True)
        self._hotplug_timer.setInterval(1000)  # rescan once a burst has gone quiet
        self._hotplug_timer.timeout.connect(self._on_devices_hotplug)
        self._media_devices.audioOutputsChanged.connect(self._hotplug_timer.start)
        self._media_devices.audioInputsChanged.connect(self._hotplug_timer.start)
        # Pin any unbound required equipment to the current Windows default,
        # by name (#139), so a session always knows which physical device it will
        # use. Skipped for a headless session; a study loaded below re-runs it on
        # its own (freshly loaded) config via apply_settings.
        self.devices_window.autobind_defaults()

        self.init_main_window()  # builds the menu + log handler (does not show yet)
        self._apply_preferences(self._prefs)
        # A study file passed on launch becomes this session's initial setup.
        if settings_path:
            self._load_initial_settings(settings_path)
        self.show()  # single show, after window flags + geometry are applied

        # A headless session records no run, so it skips the log header and
        # interaction logging.
        if not self.session.headless:
            # Panels (and any launch-file overrides) are in place, so capture the
            # initial state into the log header (also emits the "Opened SMACC" line).
            self.session.begin_log(self._window_settings())
            self._notify_missing_biocal_voices()
            # Startup widget setup is done; from here on, log soft interactions.
            self.session.log_interactions = True

    def show_error_popup(self, short_msg, long_msg=None):
        """Show an error dialog parented to this window (logs via the session)."""
        self.session.show_error_popup(short_msg, long_msg, parent=self)

    def _update_preview_levels(self) -> None:
        """Sync the preview handler's visible levels to the level checkboxes."""
        self.preview_handler.enabled_levels = {
            level for level, box in self._preview_level_boxes.items() if box.isChecked()
        }

    def init_main_window(self):
        """Initialize SMACC's main window: menu/status bars and the widget grid."""
        self._build_menu_bar()
        self.statusBar().showMessage("Ready")

        # Two columns: the tools column (with the lights toggle pinned to the bottom)
        # and the live log preview on the right. The menu is built first so the
        # preview-level checkbox dict it seeds is ready when the preview is built.
        central_layout = QtWidgets.QGridLayout()
        central_layout.addLayout(self._build_launcher_buttons(), 0, 0)
        central_layout.addLayout(self._build_log_viewer_section(), 0, 1)
        central_layout.setColumnStretch(1, 1)  # the right column takes the extra width
        central_layout.setRowStretch(0, 1)
        central_widget = QtWidgets.QWidget()
        central_widget.setContentsMargins(5, 5, 5, 5)
        central_widget.setLayout(central_layout)
        self.setCentralWidget(central_widget)

        self.setWindowTitle("SMACC Session")
        if LOGO_PATH.is_file():
            windowIcon = QtGui.QIcon(str(LOGO_PATH))
        else:
            windowIcon = self.style().standardIcon(
                QtWidgets.QStyle.StandardPixmap.SP_ToolBarHorizontalExtensionButton
            )
        self.setWindowIcon(windowIcon)
        # Window size/position comes from saved machine preferences (_apply_preferences);
        # always-on-top and the log-preview levels travel with the study and are applied
        # by apply_settings. __init__ shows the window after both run.

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

    # Tool windows openable from the launcher (key -> button label). Panels
    # absent from this map get no button ("participant_chat" opens from the Chat
    # window) but keep the rest of the machinery: state, geometry, always-on-top,
    # cleanup.
    PANEL_LABELS = {
        "events": "Event logging",
        "biocals": "Biocals",
        "visual": "Visual cue",
        "audio": "Audio cue",
        "noise": "Noise machine",
        "recording": "Dream recording",
        "chat": "Chat",
        "devices": "Devices",
        "markers": "Markers",
        "volume": "Volume",
    }

    # Hover/status-bar hints for each tool button (key -> tooltip).
    PANEL_TOOLTIPS = {
        "events": "Log experiment events and send their EEG trigger codes.",
        "biocals": "Run timed biocalibrations, with optional voice instructions "
        "and a full sequence.",
        "visual": "Light cues on a BlinkStick: steady, pulse, or flash.",
        "audio": "Play audio cues from a multi-slot cue board.",
        "noise": "Stream continuous background noise (colored noise or a file).",
        "recording": "Record a spoken dream report, monitor input level, open surveys.",
        "chat": "Talk, listen, or text-chat with the participant.",
        "devices": "Bind the rig's equipment to devices and route each action.",
        "markers": "Configure every event marker: port codes, LSL/TTL routing, "
        "preview, and the hardware trigger output.",
        "volume": "Set a master output volume safety cap.",
    }

    def _build_launcher_buttons(self) -> QtWidgets.QLayout:
        """Build the 'Panels' column: panel launchers + the lights toggle.

        The lights toggle is pinned to the bottom of the column at a fixed,
        reasonable size (the stretch above absorbs extra height), so enlarging
        the window for a bigger log preview no longer stretches the toggle; it
        sends the lights event marker and flips the dark theme.
        """
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self._make_section_title("Panels"))
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
        layout.addWidget(self.lightswitchButton)
        return layout

    def _open_panel(self, key: str) -> None:
        """Show and focus the tool window for ``key`` (placing it on first open).

        On a tool's first open this session, restore the position/size it was last
        left at (machine-local, per window); with none saved (or off-screen now) it
        cascades to the right of the session window as before. A headless window
        (tests, screenshots) persists no geometry, so it always cascades.
        """
        window = self.panels[key]
        if key not in self._positioned_panels:
            headless = self.session.headless
            if not (not headless and self._restore_panel_geometry(window, key)):
                self._position_panel(window, key)
            self._positioned_panels.add(key)
        window.show()
        window.raise_()
        window.activateWindow()

    def _restore_panel_geometry(self, window: QtWidgets.QWidget, key: str) -> bool:
        """Restore a tool window's saved geometry; return True iff a position was set.

        Size is applied regardless; a missing/off-screen position returns False so the
        caller falls back to the cascade placement. The fallback size is the window's
        content ``sizeHint`` — not ``width()``/``height()``, which on a not-yet-shown
        window is Qt's generic 640×480 default. Using that default would force every
        first-opened tool to the same oversized box (e.g. the slim Volume window),
        which read as window sizes "bleeding" across tools; the sizeHint opens each at
        its own natural size instead.
        """
        geometry = preferences.window_geometry(self._prefs, key)
        hint = window.sizeHint()
        return windowstate.restore_geometry(
            window, geometry, default_size=(hint.width(), hint.height())
        )

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
            "End sessio&n",
            self,
        )
        quitAction.setShortcut("Ctrl+Q")
        quitAction.setStatusTip("End this session and quit SMACC")
        quitAction.triggered.connect(self.close)  # close goes to closeEvent

        sessionInfoAction = QtGui.QAction("Session &info…", self)
        sessionInfoAction.setStatusTip(
            "Edit optional subject/session/notes metadata recorded with the session."
        )
        sessionInfoAction.triggered.connect(self.session_info)

        # Marker configuration (the registry + the hardware trigger transport)
        # lives in the Markers tool window — a launcher button, not a menu item.

        # Always-on-top is a per-window interface choice that travels with the study
        # (applied by _apply_always_on_top_settings). Built in both modes so settings
        # can set its state, but only surfaced in a session's menu (tool windows carry
        # their own toggle on the PanelWindow base).
        alwaysOnTopAction = QtGui.QAction("Always on &top", self)
        # The same Ctrl+T every tool window carries (see PanelWindow); the
        # default WindowShortcut context pins whichever window is active.
        alwaysOnTopAction.setShortcut("Ctrl+T")
        alwaysOnTopAction.setStatusTip(
            "Keep the SMACC window above other applications."
        )
        alwaysOnTopAction.setCheckable(True)
        alwaysOnTopAction.setChecked(False)
        alwaysOnTopAction.toggled.connect(self.toggle_always_on_top)
        self._always_on_top_action = alwaysOnTopAction

        # The live-preview clock (12-hour vs 24-hour) is a machine preference, not
        # study state, so it persists to preferences.yaml on toggle rather than into
        # the .smacc. Surfaced only in a session's File menu (the editor has no
        # preview); built here so _apply_preferences can sync its checkmark.
        previewClockAction = QtGui.QAction("12-hour &clock", self)
        previewClockAction.setStatusTip(
            "Show the live log preview in 12-hour (AM/PM) time; "
            "the log file always stays 24-hour."
        )
        previewClockAction.setCheckable(True)
        previewClockAction.setChecked(False)
        previewClockAction.toggled.connect(self.toggle_preview_clock)
        self._preview_clock_action = previewClockAction

        # Device rescanning lives on the Devices window's Refresh button (which also
        # carries the F5 shortcut), not in this menu — hot-plugging is detected
        # automatically, so a menu entry here was redundant.
        menu_bar = self.menuBar()
        assert menu_bar is not None
        fileMenu = menu_bar.addMenu("&File")
        assert fileMenu is not None
        # Log-preview level toggles live beside the preview now (built in
        # _build_log_viewer_section), not in this menu. Initialized empty here so
        # _apply_preferences can iterate it uniformly in both modes.
        self._preview_level_boxes: dict[int, QtWidgets.QCheckBox] = {}
        self._build_session_file_menu(fileMenu, sessionInfoAction, alwaysOnTopAction)
        fileMenu.addSeparator()
        fileMenu.addAction(quitAction)

    def _add_surveys_menu(self, fileMenu: QtWidgets.QMenu) -> None:
        """Add File → Surveys (rebuilt on show, since the saved list changes)."""
        surveysMenu = fileMenu.addMenu("Sur&veys")
        assert surveysMenu is not None
        surveysMenu.aboutToShow.connect(lambda: self._rebuild_surveys_menu(surveysMenu))

    def _build_session_file_menu(self, fileMenu, sessionInfoAction, alwaysOnTopAction):
        """Session File menu: run-only. Author settings in the editor; analyze past
        runs (including event export) from the launcher. Here you record events."""
        # Snapshot the live session's current configuration to a SMACC file —
        # the in-session counterpart of the editor's Save-As (a session never
        # silently rewrites the file it was started from).
        saveAsAction = QtGui.QAction("Save SMACC file &as…", self)
        saveAsAction.setShortcut("Ctrl+Shift+S")
        saveAsAction.setStatusTip(
            "Save a snapshot of the current session's settings to a .smacc file."
        )
        saveAsAction.triggered.connect(self.export_settings)
        fileMenu.addAction(saveAsAction)
        fileMenu.addSeparator()
        fileMenu.addAction(sessionInfoAction)
        self._add_surveys_menu(fileMenu)
        fileMenu.addSeparator()
        fileMenu.addAction(alwaysOnTopAction)
        fileMenu.addAction(self._preview_clock_action)

    def _rebuild_surveys_menu(self, menu: QtWidgets.QMenu) -> None:
        """Fill File → Surveys with each available survey (open standalone).

        Lists the in-app surveys (built-in + custom) and the study's saved URLs;
        managing them lives on the Dream-recording panel's Manage… button only.
        """
        menu.clear()
        recording = cast(RecordingWindow, self.panels["recording"])
        surveys = recording.available_surveys()
        if surveys:
            for name, url in surveys.items():
                action = menu.addAction(name)
                assert action is not None
                action.setStatusTip(url)
                action.triggered.connect(partial(recording.open_survey_url, url, name))
        else:
            empty = menu.addAction("(no surveys available)")
            assert empty is not None
            empty.setEnabled(False)

    def _build_log_viewer_section(self) -> QtWidgets.QLayout:
        """Build the log-preview panel: header, level toggles, and the live list."""
        titleLabel = self._make_section_title("Log preview")

        # Live preview list --> gets updated when events/messages are logged.
        # B612 Mono (#279) keeps the "time · level · message" columns aligned and
        # the timestamps a steady width as lines stream in.
        logviewList = QtWidgets.QListWidget()
        logviewList.setAutoScroll(True)
        logviewList.setFont(mono_font())
        self.logviewList = logviewList

        # Route log records to the preview pane, filtered by the level toggles.
        # The preview keeps only the newest N lines (preferences.yaml's
        # log_preview_max_lines); the log file records everything.
        self.preview_handler = QtLogHandler(
            logviewList, max_lines=preferences.log_preview_max_lines(self._prefs)
        )
        self.preview_handler.setFormatter(
            logging.Formatter(
                fmt=_PREVIEW_LOG_FORMAT,
                datefmt=preferences.preview_time_format(self._prefs),
            )
        )
        # Only a live session routes its log to the preview. A headless window
        # records nothing, and attaching this handler to the shared 'smacc' logger
        # would outlive the (offscreen, soon-GC'd) list widget and fire into a
        # deleted object from a later test/run.
        if not self.session.headless:
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

    def toggle_always_on_top(self, enabled: bool) -> None:
        """Toggle the main window's always-on-top hint (from its File menu)."""
        self.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint, enabled)
        # Re-applying window flags hides the window on some platforms; re-show it.
        self.show()
        self.session.log_debug_msg(
            f"Always-on-top {'enabled' if enabled else 'disabled'}"
        )

    def toggle_preview_clock(self, enabled: bool) -> None:
        """Switch the live preview between 12-hour and 24-hour time (File menu).

        Presentation only: the log file keeps 24-hour ISO timestamps regardless.
        The new format applies to lines logged from here on; lines already in the
        preview keep the format they were rendered with. Saved to preferences.yaml
        (a machine preference, not study state) so it persists across sessions.
        """
        token = "12h" if enabled else "24h"
        self.preview_handler.setFormatter(
            logging.Formatter(
                fmt=_PREVIEW_LOG_FORMAT, datefmt=preferences.CLOCK_FORMATS[token]
            )
        )
        self._prefs["log_preview_clock"] = token
        preferences.update_preferences(preferences_path, {"log_preview_clock": token})
        self.session.log_debug_msg(
            f"Log preview clock set to {'12-hour' if enabled else '24-hour'}"
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
        hints = QtGui.QGuiApplication.styleHints()
        assert hints is not None
        hints.setColorScheme(
            QtCore.Qt.ColorScheme.Dark if dark else QtCore.Qt.ColorScheme.Light
        )

    ############################################################################
    # Settings export/import (.smacc)
    ############################################################################

    def gather_settings(self) -> dict:
        """Collect the window's settings, routed through the StudyConfig model.

        :class:`~smacc.studyconfig.StudyConfig` is the canonical (de)serializer for a
        ``.smacc``: gathering the flat window state and round-tripping it through the
        model is an identity for complete live state (proven in tests) and makes any
        future panel/model drift a test failure rather than a silent mis-save. Loading
        still applies the *raw* mapping to the panels (see :meth:`apply_settings`), so a
        partial study keeps its "absent key leaves the current value" semantics.
        """
        return StudyConfig.from_settings_dict(
            self._window_settings()
        ).to_settings_dict()

    def _window_settings(self) -> dict:
        """Collect each panel's parameters into one serializable settings dict.

        Device equipment + routing travel with the settings in a ``devices`` block (see
        :mod:`smacc.devices`), so a rig's whole device setup is restored on the next
        load; an unplugged bound device is flagged rather than silently dropped.
        """
        state: dict = {}
        for panel in self.panels.values():
            state.update(panel.gather_state())
        # Device equipment/routing live on the session, not a panel; persist the block.
        state["devices"] = self.session.devices.to_dict()
        # The event-code registry isn't a panel; persist it at the window level.
        state["event_codes"] = self.session.event_codes_as_list()
        state["event_code_safe_max"] = self.session.event_code_safe_max
        # Optional hardware-trigger config (transport/port/mode/…), also window-level.
        state["trigger_output"] = self.session.trigger_config.to_dict()
        # Philips Hue bridge config (#53): rig state that travels with the study,
        # like the device bindings. The app key is a local-network credential.
        state["hue"] = self.session.hue_config.to_dict()
        # The data directory (where runs are written) travels with the settings.
        state["data_directory"] = str(self.data_dir)
        # Interface choices that travel with the study: the live-preview levels and
        # the main window's always-on-top, plus a per-tool always-on-top map keyed by
        # panel key.
        state["preview_levels"] = self._gather_preview_levels()
        state["always_on_top"] = self._always_on_top_action.isChecked()
        state["tool_always_on_top"] = {
            key: panel.is_always_on_top() for key, panel in self.panels.items()
        }
        return state

    def _gather_preview_levels(self) -> list[str]:
        """The enabled preview levels as level-name strings (for the settings file)."""
        checked = {
            level for level, box in self._preview_level_boxes.items() if box.isChecked()
        }
        return preferences.levels_to_names(checked)

    def apply_settings(self, state: dict) -> None:
        """Apply a settings ``state`` dict to every panel (each reads its own keys).

        Soft interaction logging is suppressed while panels reload their widgets,
        so a study load doesn't spam the log with volume/color/device lines.
        """
        was_logging = self.session.log_interactions
        self.session.log_interactions = False
        self.session.missing_devices = []  # filled by the Devices reload below
        # The rig profile (machine-local, in preferences) supplies the physical half
        # of the device setup — equipment->device bindings, the trigger port, and the
        # Hue credential — that a portable study no longer carries (#300). Empty out of
        # the box, so this is a no-op until a rig is bound.
        rig = self._prefs
        # Device routing (study) + bindings (rig) first, so panels resolve against it.
        self.session.devices = devices.from_study_and_rig(
            state, preferences.rig_bindings(rig)
        )
        trigger_error: str | None = None
        try:
            for panel in self.panels.values():
                panel.apply_state(state)
            # Apply the study's event-code registry (or the defaults when it omits
            # event_codes) to the live session.
            self.session.set_event_codes(
                state.get("event_codes"), state.get("event_code_safe_max")
            )
            # Optional hardware-trigger config (disabled when the study omits it).
            # Open the transport now so a bad port/driver is reported at load.
            self.session.trigger_config = triggers.from_study_and_rig(
                state, preferences.rig_trigger(rig)
            )
            trigger_error = self.session.set_trigger_output(self.session.trigger_config)
            # Hue bridge config before the Devices reload: the Hue equipment dropdown
            # enumerates from the (newly loaded) bridge, so a bound light matches. The
            # bridge credential is rig-local (#300); a study value is a legacy fallback.
            self.session.hue_config = hue.from_dict(
                {**(state.get("hue") or {}), **preferences.rig_hue(rig)}
            )
            self.devices_window.refresh_device_lists()
            # A study with unbound required equipment (e.g. one authored in the
            # editor on another machine) gets *this* rig's current defaults
            # pinned, by name (#139).
            self.devices_window.autobind_defaults()
            self._refresh_registry_views()  # a loaded study may add/remove buttons
            self.devices_window.reload_from_config()  # sync widgets + flag missing
            self._refresh_device_indicators()
            # Interface choices carried by the study: preview levels and per-window
            # always-on-top. A study may omit these; the interface defaults apply.
            self._apply_preview_levels(state)
            self._apply_always_on_top_settings(state)
        finally:
            self.session.log_interactions = was_logging
        self._notify_missing_devices()
        if trigger_error:
            self.show_error_popup("Hardware trigger unavailable.", trigger_error)

    def _apply_preview_levels(self, state: dict) -> None:
        """Sync the live-preview level boxes from a loaded study's ``preview_levels``.

        Absent (the study omits the key) leaves the current selection — which the
        window seeded to the default set — untouched, so the defaults apply.
        """
        if "preview_levels" not in state:
            return
        names = state.get("preview_levels") or []
        wanted = preferences.names_to_levels(names)
        for level, box in self._preview_level_boxes.items():
            box.blockSignals(True)
            box.setChecked(level in wanted)
            box.blockSignals(False)
        self._update_preview_levels()

    def _apply_always_on_top_settings(self, state: dict) -> None:
        """Apply the main window's + each tool window's always-on-top from a study.

        The main window's flag is the ``always_on_top`` scalar; the tools read a
        ``tool_always_on_top`` map keyed by panel key. Both default to off for any
        key the study omits.
        """
        main = bool(state.get("always_on_top", False))
        self._always_on_top_action.blockSignals(True)
        self._always_on_top_action.setChecked(main)
        self._always_on_top_action.blockSignals(False)
        self.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint, main)
        if main and self.isVisible():
            self.show()  # re-applying the flag can hide the window; re-show it
        tool_map = state.get("tool_always_on_top")
        if not isinstance(tool_map, dict):
            tool_map = {}
        for key, panel in self.panels.items():
            panel.set_always_on_top(bool(tool_map.get(key, False)))

    def _refresh_registry_views(self) -> None:
        """Re-render the registry's consumers after it changes.

        The Event logging grid rebuilds its buttons (and their routing tooltips);
        the Markers window re-reads the session so its staging never goes stale.
        Reached after a study load and after a Markers-window Apply.
        """
        panel = self.panels.get("events")
        if isinstance(panel, EventsWindow):
            panel.rebuild()
        markers = self.panels.get("markers")
        if isinstance(markers, MarkersWindow):
            markers.reload_from_session()

    def _refresh_device_indicators(self) -> None:
        """Re-render every panel's device indicator from session.devices."""
        for panel in self.panels.values():
            panel.refresh_device_indicator()

    def _on_devices_hotplug(self) -> None:
        """Devices changed (debounce timer fired): rescan when nothing is streaming.

        Reached only via ``_hotplug_timer``, which coalesces Windows' bursts of
        change signals into one rescan. Skipped while audio is live (a PortAudio
        re-init would cut it); the operator can use the Devices window's Refresh
        button once idle.
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
        self.session.log_debug_msg("Devices changed; lists rescanned")

    def _notify_missing_devices(self) -> None:
        """Surface, once, any saved devices that weren't connected when settings loaded.

        Skipped for a headless window (tests, screenshots), which opens no popups.
        """
        missing = self.session.missing_devices
        if not missing or self.session.headless:
            return
        items = "\n".join(f"  • {entry}" for entry in missing)
        self.session.show_info_popup(
            "Some saved devices aren’t connected.",
            "These devices from the settings file weren’t found:\n"
            f"{items}\n\n"
            "Plug them in and click Refresh devices in the Devices window, or pick "
            "another device.",
            parent=self,
        )

    def _notify_missing_biocal_voices(self) -> None:
        """Warn once, at session start, about absent biocal voice recordings (#78).

        Live sessions only — the files are machine-level (seeded under the SMACC
        root), so a headless window (e.g. built on a different machine than the rig)
        would warn spuriously. A biocal with a missing voice still runs, just
        unvoiced, so this is a heads-up rather than a blocker.
        """
        missing = biocals.missing_voice_files(BIOCALS_DIR, fallback=BUNDLED_BIOCALS_DIR)
        if not missing:
            return
        items = "\n".join(f"  • {name}" for name in missing)
        self.session.show_info_popup(
            "Some biocal voice recordings are missing.",
            f"No recording (bundled or in {BIOCALS_DIR}) for:\n{items}\n\n"
            "These biocals will run without their spoken instruction.",
            parent=self,
        )

    def refresh_all_devices(self) -> None:
        """Rescan for devices plugged in after launch (the Devices window's Refresh, F5).

        BlinkSticks are a live USB scan and Hue lights a live bridge query, so both
        are always rescanned. PortAudio caches its device list at initialization,
        so audio devices are only picked up by re-initializing it — which
        invalidates open streams, so that is done only while nothing is playing,
        recording, or monitoring.
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
                "BlinkSticks and Hue lights were rescanned. To rescan audio "
                "devices too, stop playback, recording, and the level meter, "
                "then click Refresh devices again.",
                parent=self,
            )
        else:
            self.session.log_debug_msg("Refreshed devices")

    # ----- preferences / launch-file / file association ----------------------

    def _apply_preferences(self, prefs: dict) -> None:
        """Apply saved machine preferences (window geometry) to the freshly built window.

        Runs after the menu + log handler exist and before the window is shown. The
        always-on-top and log-preview choices no longer live here — they travel with
        the study and are applied by :meth:`apply_settings` (defaults stand until a
        file loads): off, and the default INFO+ levels seeded in init_main_window.
        Signals are blocked while setting checked states so the handlers don't fire.
        """
        # Lights always start ON each launch — the dark theme is per-session
        # state, not a saved preference. Keep the switch in sync, fire no marker.
        self.lightswitchButton.blockSignals(True)
        self.lightswitchButton.setChecked(True)
        self.lightswitchButton.blockSignals(False)
        self.set_lights(True, send_marker=False)

        # A headless window persists no geometry; give it a compact default rather
        # than inheriting (or later writing) the saved session window size.
        if self.session.headless:
            self.resize(640, 460)
        else:
            geometry = preferences.window_geometry(prefs, preferences.MAIN_WINDOW_ID)
            if not windowstate.restore_geometry(
                self, geometry, default_size=(640, 560)
            ):
                self._move_to_default_position()  # first run: sit by the launcher

        # Reflect the saved live-preview clock choice in its menu toggle. The
        # preview formatter was already built from this preference; this only syncs
        # the checkmark (signals blocked so the handler doesn't re-persist). Skipped
        # for a headless window, which touches no machine preferences.
        if not self.session.headless:
            self._preview_clock_action.blockSignals(True)
            self._preview_clock_action.setChecked(
                preferences.log_preview_clock(prefs) == "12h"
            )
            self._preview_clock_action.blockSignals(False)

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

    def _save_geometry(self) -> None:
        """Persist this window's position/size under the main-window id (best-effort).

        Merged into the on-disk per-window map so it doesn't clobber the launcher's
        recents or any other window's geometry. A headless window persists nothing.
        """
        if self.session.headless:
            return
        preferences.update_window_geometry(
            preferences_path, preferences.MAIN_WINDOW_ID, windowstate.geometry_of(self)
        )

    def _load_initial_settings(self, settings_path: str) -> None:
        """Load a settings file given on launch and apply it as the initial setup."""
        try:
            state, _metadata = settings.load_settings(settings_path)
            state = settings.resolve_paths(state, Path(settings_path).parent)
        except (OSError, ValueError) as exc:
            self.show_error_popup("Could not open settings file.", str(exc))
            return
        # A live session's metadata comes from the start-of-session prompt (#184),
        # already prefilled from this file, so the loaded metadata is not re-merged.
        self.apply_settings(state)
        self.session.log_debug_msg(f"Loaded settings from {settings_path}")

    def export_settings(self) -> bool:
        """Prompt for a path (Save-As) and write the settings there. Returns success."""
        # Default to the file we loaded, else a settings.smacc beside the data dir.
        # Never pre-fill the protected default.smacc — suggest a fresh name instead.
        if self.settings_path and not is_default_settings(self.settings_path):
            default = self.settings_path
        else:
            default = str(self.data_dir / "settings.smacc")
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save SMACC file", str(default), "SMACC file (*.smacc)"
        )
        if not path:
            return False
        return self._write_settings(path)

    def _write_settings(self, path: str) -> bool:
        """Write the current settings to ``path`` (relativizing paths). Returns success."""
        # The seeded default.smacc is SMACC's known-good template; refuse to overwrite
        # it (e.g. if it's hand-picked in the Save-As dialog) and point at Save-As.
        if is_default_settings(path):
            self.show_error_popup(
                "Can’t overwrite the default settings.",
                "default.smacc is SMACC's built-in template and stays read-only so it "
                "remains a reliable starting point. Save your changes to a new .smacc "
                "file instead.",
            )
            return False
        # Make referenced cue/noise/data paths relative to the file when possible.
        portable = settings.relativize_paths(self.gather_settings(), Path(path).parent)
        try:
            settings.save_settings(path, portable, self.session.metadata)
        except (OSError, ValueError) as exc:
            self.show_error_popup("Could not save settings.", str(exc))
            return False
        self.settings_path = path  # subsequent saves update this file
        # The physical half of the device setup is machine-local, so persist it to the
        # rig profile (preferences), not the portable study (#300). A headless window
        # records nothing and touches no machine state.
        if not self.session.headless:
            self._persist_rig_profile()
        self.session.log_debug_msg(f"Saved settings to {path}")
        status_bar = self.statusBar()
        assert status_bar is not None
        status_bar.showMessage(f"Saved settings to {Path(path).name}", 5000)
        return True

    def _persist_rig_profile(self) -> None:
        """Persist this machine's physical device setup to the rig profile (#300).

        The equipment->device bindings, the hardware trigger's port/baud/address, and
        the Hue bridge credential are machine-local: they belong in ``preferences.yaml``,
        not the portable study. Saving a session captures the current rig so the next
        study on this machine reuses it (the Rig setup tool will be the dedicated path).
        """
        rig = {
            "bindings": dict(self.session.devices.bindings),
            "trigger": self.session.trigger_config.to_rig_dict(),
            "hue": self.session.hue_config.to_dict(),
        }
        preferences.update_rig(preferences_path, rig)
        self._prefs["rig"] = rig

    def _persist_rig_bindings(self) -> None:
        """Persist just the equipment->device bindings to the rig profile (#300).

        Connected to the Devices window's ``changed`` signal so a binding made in one
        session is reused by every later study on this machine, without needing a Save.
        Writes only the ``bindings`` sub-key (leaving the rig's trigger/hue intact) and
        keeps the in-memory prefs in sync so a later load reads the new binding.
        A headless window records nothing and touches no machine state.
        """
        if self.session.headless:
            return
        bindings = dict(self.session.devices.bindings)
        preferences.update_rig(preferences_path, {"bindings": bindings})
        self._prefs.setdefault("rig", {})["bindings"] = bindings

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

    def _teardown_panels(self) -> None:
        """Stop and close every tool window (called when this window closes).

        Each panel that the operator opened this session records its geometry under
        its panel key, so it reopens where it was left next time. A headless window
        persists no geometry.
        """
        for key, panel in self.panels.items():
            if not self.session.headless and key in self._positioned_panels:
                preferences.update_window_geometry(
                    preferences_path, key, windowstate.geometry_of(panel)
                )
            panel._quitting = True
            panel.cleanup()
            panel.close()

    def closeEvent(self, event):
        """End the session and emit ``closed`` (the launcher then quits SMACC).

        Overrides Qt's closeEvent. A headless window (tests, screenshots) records no
        run, so it tears down cleanly — no end-session prompt and no preference
        writes — and the launcher brings itself back rather than quitting.
        """
        if self.session.headless:
            self._teardown_panels()
            self.session.close()
            event.accept()
            self.closed.emit()
            return

        response = QtWidgets.QMessageBox.question(
            self, "End session", "End this session and quit SMACC?"
        )
        if response == QtWidgets.QMessageBox.StandardButton.Yes:
            self._save_geometry()  # before teardown closes/moves anything
            self._teardown_panels()
            self.session.log_info_msg("Session ended")
            # Record the final settings (incl. any mid-session edits) as the tail.
            self.session.end_log(self._window_settings())
            # Detach this window's preview handler and release the session's log
            # handler + outlet so the next session in this process starts clean.
            self.session.logger.removeHandler(self.preview_handler)
            self.session.close()
            event.accept()
            self.closed.emit()
        else:
            event.ignore()
