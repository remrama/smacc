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

from PyQt5 import QtCore, QtGui, QtWidgets

from . import preferences, settings
from .analyze import AnalyzeWindow
from .config import VERSION
from .dialogs import PreferencesDialog
from .gui import SmaccWindow
from .paths import DEFAULT_DATA_DIR, DEFAULT_SETTINGS_PATH, LOGO_PATH, preferences_path
from .session import SmaccSession
from .toolwindow import ToolWindow


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
        self._refresh_settings_label()
        self._populate_recents()

    # ----- current-settings helpers ----------------------------------------

    def _data_dir(self) -> Path:
        """The data directory of the current settings file (default when none)."""
        if self._settings_path:
            return settings.load_data_directory(self._settings_path, DEFAULT_DATA_DIR)
        return DEFAULT_DATA_DIR

    def _settings_name(self) -> str:
        return Path(self._settings_path).name if self._settings_path else "(defaults)"

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
                    72, QtCore.Qt.SmoothTransformation
                )
            )
            logo.setAlignment(QtCore.Qt.AlignCenter)
            layout.addWidget(logo)
        title = QtWidgets.QLabel("SMACC")
        title_font = QtGui.QFont()
        title_font.setPointSize(20)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(title)

        layout.addWidget(self._build_settings_box())

        for label, slot, tip in (
            (
                "Start session",
                self.start_session,
                "Run a session using the selected settings.",
            ),
            (
                "Create settings",
                self.create_settings,
                "Build a new .smacc settings file in the editor.",
            ),
            (
                "Analyze session",
                self.analyze_session,
                "Summarize a past session, export its events, or recover its settings.",
            ),
        ):
            button = QtWidgets.QPushButton(label, self)
            button.setMinimumHeight(48)
            button.setStatusTip(tip)
            button.clicked.connect(slot)
            layout.addWidget(button)

        layout.addStretch(1)
        footer = QtWidgets.QLabel(f"v{VERSION} — github.com/remrama/smacc")
        footer.setAlignment(QtCore.Qt.AlignCenter)
        footer.setEnabled(False)
        layout.addWidget(footer)

        self.statusBar()
        self.setCentralWidget(central)
        self.resize(360, 480)

    def _build_menu(self) -> None:
        fileMenu = self.menuBar().addMenu("&File")
        prefsAction = fileMenu.addAction("&Preferences…")
        prefsAction.setStatusTip("Edit interface preferences (theme, log preview, …).")
        prefsAction.triggered.connect(self.edit_preferences)
        fileMenu.addSeparator()
        quitAction = fileMenu.addAction("&Quit")
        quitAction.setShortcut("Ctrl+Q")
        quitAction.setStatusTip("Quit SMACC.")
        quitAction.triggered.connect(self.close)

    def _build_settings_box(self) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("Settings", self)
        grid = QtWidgets.QGridLayout(box)
        self.settingsLabel = QtWidgets.QLabel(self)
        self.settingsLabel.setWordWrap(True)
        self.settingsLabel.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.recentCombo = QtWidgets.QComboBox(self)
        self.recentCombo.setStatusTip("Switch to a recently used settings file.")
        self.recentCombo.activated.connect(self._on_recent_selected)
        openButton = QtWidgets.QPushButton("Open…", self)
        openButton.setStatusTip("Open an existing .smacc settings file.")
        openButton.clicked.connect(self.open_settings)
        editButton = QtWidgets.QPushButton("Edit…", self)
        editButton.setStatusTip("Edit the current settings in the editor.")
        editButton.clicked.connect(self.edit_settings)
        grid.addWidget(self.settingsLabel, 0, 0, 1, 2)
        grid.addWidget(QtWidgets.QLabel("Recent:"), 1, 0)
        grid.addWidget(self.recentCombo, 1, 1)
        grid.addWidget(openButton, 2, 0)
        grid.addWidget(editButton, 2, 1)
        return box

    # ----- settings selection ----------------------------------------------

    def _refresh_settings_label(self) -> None:
        if self._settings_path:
            self.settingsLabel.setText(
                f"<b>{self._settings_name()}</b><br><small>{self._settings_path}</small>"
            )
        else:
            self.settingsLabel.setText(
                "<b>(defaults)</b><br><small>built-in defaults → "
                f"{DEFAULT_DATA_DIR}</small>"
            )

    def _populate_recents(self) -> None:
        prefs = preferences.load_preferences(preferences_path)
        recents = [r for r in prefs.get("recent_settings", []) if isinstance(r, str)]
        self.recentCombo.blockSignals(True)  # programmatic fill: don't fire activated
        self.recentCombo.clear()
        if not recents:
            self.recentCombo.addItem("(none yet)", None)
            self.recentCombo.setEnabled(False)
        else:
            self.recentCombo.setEnabled(True)
            for path in recents:
                self.recentCombo.addItem(Path(path).name, path)
            if self._settings_path:
                current = self.recentCombo.findData(self._settings_path)
                if current >= 0:
                    self.recentCombo.setCurrentIndex(current)
        self.recentCombo.blockSignals(False)

    def _on_recent_selected(self, index: int) -> None:
        path = self.recentCombo.itemData(index)
        if not path:
            return
        if not Path(path).is_file():
            QtWidgets.QMessageBox.warning(
                self, "Settings", "That settings file no longer exists."
            )
            self._populate_recents()  # reselect the still-valid current file
            return
        self._set_settings(path)

    def _set_settings(self, path: str | None) -> None:
        self._settings_path = path
        if path:
            self._remember(path)
        self._refresh_settings_label()
        self._populate_recents()

    def _remember(self, path: str) -> None:
        """Push ``path`` onto the persisted recent-settings list (most-recent first)."""
        prefs = preferences.load_preferences(preferences_path)
        recents = [r for r in prefs.get("recent_settings", []) if isinstance(r, str)]
        recents = preferences.push_recent(recents, str(path))
        preferences.update_preferences(preferences_path, {"recent_settings": recents})

    def open_settings(self) -> None:
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
            self._populate_recents()
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        """Closing the launcher quits SMACC (it is the app's root window)."""
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.quit()
        event.accept()
