"""The SMACC launcher: pick a settings file and choose what to do.

This is the FSL-style opening menu. Instead of dropping straight into a session,
SMACC opens this small window so the operator first picks (or creates) a **settings
file** (`.smacc`), then chooses to **Start session**, **Create settings**, or
**Analyze session**. Each settings file names the **data directory** its runs are
written to; with none chosen, SMACC uses built-in defaults and the default data
directory.

The launcher is the app's persistent root window: opening a tool hides it, closing
the tool brings it back (via the tool's ``closed`` signal), and closing the
launcher quits SMACC (``main`` sets ``quitOnLastWindowClosed`` False).
"""

from __future__ import annotations

from pathlib import Path

from PyQt6 import QtCore, QtGui, QtWidgets

from . import preferences, settings
from .analyze import AnalyzeWindow
from .config import VERSION
from .dialogs import PreferencesDialog
from .gui import SmaccWindow
from .paths import DEFAULT_DATA_DIR, DEFAULT_SETTINGS_PATH, LOGO_PATH, preferences_path
from .session import SmaccSession
from .toolwindow import ToolWindow

# Sentinel item-data for the Settings dropdown's "Browse…" entry (vs. a path str).
_BROWSE_SENTINEL = "\x00browse"


def resolve_initial_settings(prefs: dict) -> str | None:
    """Return the settings file to preselect at launch, or None for built-in defaults.

    Prefers the last-used file, then the seeded ``default.smacc``; None means start
    from SMACC's built-in defaults (writing to the default data directory).
    """
    last = prefs.get("last_settings")
    if last and Path(last).is_file():
        return str(last)
    if DEFAULT_SETTINGS_PATH.is_file():
        return str(DEFAULT_SETTINGS_PATH)
    return None


class LauncherWindow(QtWidgets.QMainWindow):
    """Small hub: pick a settings file, then start / create / analyze."""

    def __init__(self, settings_path: str | None) -> None:
        super().__init__()
        self._settings_path = settings_path  # current .smacc, or None for defaults
        self._tool: ToolWindow | None = None
        self.setWindowTitle("SMACC")
        if LOGO_PATH.is_file():
            self.setWindowIcon(QtGui.QIcon(str(LOGO_PATH)))
        self._build()
        if settings_path:
            self._remember(settings_path)
        self._populate_settings_combo()

    # ----- current-settings helpers ----------------------------------------

    def _data_dir(self) -> Path:
        """The data directory of the current settings file (default when none)."""
        if self._settings_path:
            return settings.load_data_directory(self._settings_path, DEFAULT_DATA_DIR)
        return DEFAULT_DATA_DIR

    # ----- UI construction --------------------------------------------------

    def _build(self) -> None:
        self._build_menu()
        central = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        if LOGO_PATH.is_file():
            logo = QtWidgets.QLabel()
            logo.setPixmap(
                QtGui.QPixmap(str(LOGO_PATH)).scaledToHeight(
                    72, QtCore.Qt.TransformationMode.SmoothTransformation
                )
            )
            logo.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(logo)
        title = QtWidgets.QLabel("SMACC")
        title_font = QtGui.QFont()
        title_font.setPointSize(20)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # One row to choose the settings, then Start / Edit / New acting on it.
        layout.addLayout(self._build_settings_row())
        layout.addLayout(self._build_action_row())

        # Analyzing a past session is a separate, post-hoc task.
        layout.addSpacing(8)
        analyzeButton = QtWidgets.QPushButton("Analyze", self)
        analyzeButton.setMinimumHeight(40)
        analyzeButton.setStatusTip(
            "Summarize a past session, export its events, or recover its settings."
        )
        analyzeButton.clicked.connect(self.analyze_session)
        layout.addWidget(analyzeButton)

        layout.addStretch(1)
        # Link to the documentation site (not the repo), hyperlinked. Rich text +
        # open-external-links makes it clickable; we don't disable the label
        # (which would also kill the link), so style it subdued instead.
        footer = QtWidgets.QLabel(
            f'v{VERSION} — <a href="https://remrama.github.io/smacc">'
            "remrama.github.io/smacc</a>"
        )
        footer.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        footer.setTextFormat(QtCore.Qt.TextFormat.RichText)
        footer.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextBrowserInteraction
        )
        footer.setOpenExternalLinks(True)
        footer.setStatusTip("Open the SMACC documentation site.")
        layout.addWidget(footer)

        self.statusBar()
        self.setCentralWidget(central)
        self.resize(340, 360)
        self._move_to_default_position()

    def _move_to_default_position(self) -> None:
        """Open near the upper-left of the screen (not tucked into the corner).

        Sets the anchor for the whole window stack: a started session opens just
        down-right of here, and its tool windows cascade farther right (see
        :mod:`smacc.gui`).
        """
        screen = self.screen() or QtWidgets.QApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        self.move(avail.left() + 48, avail.top() + 48)

    def _build_menu(self) -> None:
        menu_bar = self.menuBar()
        assert menu_bar is not None
        fileMenu = menu_bar.addMenu("&File")
        assert fileMenu is not None
        prefsAction = fileMenu.addAction("&Preferences…")
        assert prefsAction is not None
        prefsAction.setStatusTip("Edit interface preferences (theme, log preview, …).")
        prefsAction.triggered.connect(self.edit_preferences)
        fileMenu.addSeparator()
        aboutAction = fileMenu.addAction("&About")
        assert aboutAction is not None
        aboutAction.setStatusTip("About SMACC (version and links).")
        aboutAction.triggered.connect(self.show_about_popup)
        quitAction = fileMenu.addAction("&Quit")
        assert quitAction is not None
        quitAction.setShortcut("Ctrl+Q")
        quitAction.setStatusTip("Quit SMACC.")
        quitAction.triggered.connect(self.close)

    def _build_settings_row(self) -> QtWidgets.QLayout:
        """One row: 'Settings:' + a dropdown of default / recents / Browse…."""
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Settings:", self))
        self.settingsCombo = QtWidgets.QComboBox(self)
        self.settingsCombo.setStatusTip(
            "Choose the settings to start, edit, or analyze."
        )
        self.settingsCombo.activated.connect(self._on_settings_selected)
        row.addWidget(self.settingsCombo, 1)
        return row

    def _build_action_row(self) -> QtWidgets.QLayout:
        """Three buttons acting on the selected settings: Start / Edit / New."""
        row = QtWidgets.QHBoxLayout()
        for label, slot, tip in (
            (
                "Start",
                self.start_session,
                "Start a session with the selected settings.",
            ),
            ("Edit", self.edit_settings, "Edit the selected settings."),
            ("New", self.create_settings, "Create a new settings file."),
        ):
            button = QtWidgets.QPushButton(label, self)
            button.setMinimumHeight(44)
            button.setStatusTip(tip)
            button.clicked.connect(slot)
            row.addWidget(button)
        return row

    # ----- settings selection ----------------------------------------------

    def _populate_settings_combo(self) -> None:
        """Fill the Settings dropdown: 'default', recents (no .smacc/path), Browse…."""
        prefs = preferences.load_preferences(preferences_path)
        recents = [r for r in prefs.get("recent_settings", []) if isinstance(r, str)]
        default = str(DEFAULT_SETTINGS_PATH)
        combo = self.settingsCombo
        combo.blockSignals(True)  # programmatic fill: don't fire activated
        combo.clear()
        combo.addItem("default", default)
        combo.setItemData(
            0, default, QtCore.Qt.ItemDataRole.ToolTipRole
        )  # full path on hover
        seen = {default}
        for path in recents:
            if path in seen:
                continue
            seen.add(path)
            combo.addItem(Path(path).stem, path)  # name only — no extension/path
            combo.setItemData(
                combo.count() - 1, path, QtCore.Qt.ItemDataRole.ToolTipRole
            )
        combo.insertSeparator(combo.count())
        combo.addItem("Browse…", _BROWSE_SENTINEL)
        target = self._settings_path or default
        index = combo.findData(target)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)

    def _on_settings_selected(self, index: int) -> None:
        data = self.settingsCombo.itemData(index)
        if data == _BROWSE_SENTINEL:
            self.open_settings()  # may set a new file; re-sync the dropdown either way
            self._populate_settings_combo()
            return
        if not data:
            return
        if not Path(data).is_file():
            if data == str(DEFAULT_SETTINGS_PATH):
                self._set_settings(None)  # default absent → SMACC's built-in defaults
            else:
                QtWidgets.QMessageBox.warning(
                    self, "Settings", "That settings file no longer exists."
                )
                self._populate_settings_combo()
            return
        self._set_settings(data)

    def _set_settings(self, path: str | None) -> None:
        self._settings_path = path
        if path:
            self._remember(path)
        self._populate_settings_combo()

    def _remember(self, path: str) -> None:
        """Push ``path`` onto the persisted recent-settings list (most-recent first)."""
        prefs = preferences.load_preferences(preferences_path)
        recents = [r for r in prefs.get("recent_settings", []) if isinstance(r, str)]
        recents = preferences.push_recent(recents, str(path))
        preferences.update_preferences(preferences_path, {"recent_settings": recents})

    def open_settings(self) -> None:
        """Browse for a .smacc not already in the dropdown and make it current."""
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Open settings (.smacc)",
            str(self._data_dir()),
            "SMACC settings (*.smacc *.yaml *.yml)",
        )
        if path:
            self._set_settings(path)

    # ----- actions ----------------------------------------------------------

    def start_session(self) -> None:
        """Run a session using the current settings (writing to its data directory)."""
        session = SmaccSession(self._data_dir())
        window = SmaccWindow(session, settings_path=self._settings_path)
        if self._settings_path:
            preferences.update_preferences(
                preferences_path, {"last_settings": self._settings_path}
            )
        self._open_tool(window)

    def create_settings(self) -> None:
        """Open the editor on a fresh settings file (built-in defaults; Save-As)."""
        session = SmaccSession(DEFAULT_DATA_DIR, design=True)
        self._open_tool(SmaccWindow(session, settings_path=None))

    def edit_settings(self) -> None:
        """Open the editor on the current settings file."""
        session = SmaccSession(self._data_dir(), design=True)
        self._open_tool(SmaccWindow(session, settings_path=self._settings_path))

    def analyze_session(self) -> None:
        """Open the analyze window over the current settings' data directory."""
        self._open_tool(AnalyzeWindow(self._data_dir()))

    def edit_preferences(self) -> None:
        """Edit interface preferences (theme, always-on-top, log-preview levels)."""
        prefs = preferences.load_preferences(preferences_path)
        dialog = PreferencesDialog(prefs, parent=self)
        if dialog.exec():
            preferences.update_preferences(preferences_path, dialog.changes())

    def show_about_popup(self) -> None:
        """Show SMACC's About dialog (version and links)."""
        box = QtWidgets.QMessageBox(self)
        box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok)
        box.setWindowTitle("About SMACC")
        box.setText("Sleep Manipulation and Communication Clickything")
        box.setInformativeText(f"version: v{VERSION}\nhttps://github.com/remrama/smacc")
        box.exec()

    # ----- tool-window lifecycle -------------------------------------------

    def _open_tool(self, window: ToolWindow) -> None:
        """Show a tool window (it shows itself) and hide the launcher until it closes."""
        self._tool = window
        window.closed.connect(self._on_tool_closed)
        self.hide()

    def _on_tool_closed(self) -> None:
        """Bring the launcher back; adopt a settings file the editor may have saved."""
        tool = self._tool
        if isinstance(tool, SmaccWindow) and tool.settings_path:
            self._set_settings(tool.settings_path)
        else:
            self._populate_settings_combo()
        # The dark theme is a per-session "lights off" state; a session that ended
        # dark shouldn't leave the launcher dark, so reset to light on return.
        QtGui.QGuiApplication.styleHints().setColorScheme(QtCore.Qt.ColorScheme.Light)
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event: QtGui.QCloseEvent | None) -> None:
        """Closing the launcher quits SMACC (it is the app's root window)."""
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.quit()
        if event is not None:
            event.accept()
