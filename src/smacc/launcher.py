"""The SMACC Launcher: a flat list of tools to open.

SMACC opens this small window first rather than dropping straight into a session.
It is a list of the SMACC tools — **Session**, **Editor**, **Analyzer**, **Audio
Cue Designer**, and **EEG Annotator**. Choosing a SMACC file (`.smacc`) is not done
up front: the Session and Editor entries each prompt for one when opened (a file
names the **data directory** its runs are written to), since the other tools don't
need a file.

The launcher is the app's persistent root window: opening a tool hides it, and
closing the tool brings it back (via the tool's ``closed`` signal) — except a live
session, whose end quits SMACC outright. Closing the launcher quits SMACC
(``main`` sets ``quitOnLastWindowClosed`` False).
"""

from __future__ import annotations

from pathlib import Path

from PyQt6 import QtCore, QtGui, QtWidgets

from . import dialogs, eeg, preferences, settings, updates, winassoc, windowstate
from .analyze import AnalyzeWindow
from .config import VERSION
from .cuedesigner import CueDesignerWindow
from .gui import SmaccWindow
from .paths import DEFAULT_DATA_DIR, DEFAULT_SETTINGS_PATH, LOGO_PATH, preferences_path
from .session import SmaccSession
from .toolwindow import ToolWindow

# Stable id for the launcher's geometry entry in the per-window preferences map.
_LAUNCHER_WINDOW_ID = "launcher"


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
    """Small hub: a button per SMACC tool (Session / Editor / Analyzer / …)."""

    def __init__(self, settings_path: str | None = None) -> None:
        super().__init__()
        self._tool: ToolWindow | None = None
        # A .smacc given at launch (a double-clicked file) preselects the Session
        # dialog the first time it opens; it is consumed there, then None.
        self._launch_file = settings_path
        self.setWindowTitle("SMACC")
        if LOGO_PATH.is_file():
            self.setWindowIcon(QtGui.QIcon(str(LOGO_PATH)))
        self._build()

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

        # One button per tool. Session and Editor prompt for a SMACC file when
        # opened (the trailing "…" signals that); the rest open straight away.
        def tool_button(label: str, tip: str, slot) -> QtWidgets.QPushButton:
            button = QtWidgets.QPushButton(label, self)
            button.setMinimumHeight(44)
            button.setStatusTip(tip)
            button.clicked.connect(slot)
            layout.addWidget(button)
            return button

        tool_button(
            "Session…",
            "Start a session: choose a SMACC file, confirm the subject/session.",
            self._open_session,
        )
        tool_button(
            "Editor…",
            "Create a new SMACC file or edit an existing one.",
            self._open_editor,
        )
        layout.addSpacing(8)  # group the file-acting tools above the rest
        tool_button(
            "Analyzer",
            "Summarize a past session, export its events, or recover its settings.",
            self.analyze_session,
        )
        tool_button(
            "Audio Cue Designer",
            "Create a tone cue and export it as a WAV file.",
            self.design_cues,
        )
        # The EEG Annotator (#136) opens in its own process so it can outlive a
        # session (see review_eeg). MNE ships inside the one SMACC binary, so the
        # tool is always present — the button is never gated.
        self.reviewEegButton = tool_button(
            "EEG Annotator",
            "Open the EEG Annotator in its own window (annotate a recording).",
            self.review_eeg,
        )

        layout.addStretch(1)
        # Link to the documentation site (not the repo), hyperlinked. Rich text +
        # open-external-links makes it clickable; we don't disable the label
        # (which would also kill the link), so style it subdued instead. The link
        # text is the short word "documentation" rather than the full URL so the
        # footer doesn't force the whole launcher wider than it needs to be.
        footer = QtWidgets.QLabel(
            f'v{VERSION} — <a href="https://remrama.github.io/smacc">documentation</a>'
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
        # Reopen where it was last left (machine-local), else the default anchor.
        prefs = preferences.load_preferences(preferences_path)
        geometry = preferences.window_geometry(prefs, _LAUNCHER_WINDOW_ID)
        if not windowstate.restore_geometry(self, geometry, default_size=(300, 360)):
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
        style = self.style()
        assert style is not None
        menu_bar = self.menuBar()
        assert menu_bar is not None
        fileMenu = menu_bar.addMenu("&File")
        assert fileMenu is not None
        # The installer owns the .smacc association (#187); this action is the
        # portable-SMACC.exe / repair affordance. Only a packaged Windows build
        # can register the handler; hide the action entirely on dev runs / other
        # platforms (a dev run is python.exe).
        if winassoc.is_associatable():
            associateAction = fileMenu.addAction("&Associate .smacc files (Windows)")
            assert associateAction is not None
            associateAction.setStatusTip(
                "Register SMACC as the handler for .smacc files (double-click to open)."
            )
            associateAction.triggered.connect(self.associate_files)
            fileMenu.addSeparator()
        updateAction = fileMenu.addAction("Check for &updates…")
        assert updateAction is not None
        updateAction.setStatusTip(
            "Check GitHub for a newer SMACC release (manual only; SMACC never "
            "checks on its own)."
        )
        updateAction.triggered.connect(self.check_for_updates)
        self._updateAction = updateAction
        aboutAction = fileMenu.addAction(
            style.standardIcon(
                QtWidgets.QStyle.StandardPixmap.SP_MessageBoxInformation
            ),
            "&About",
        )
        assert aboutAction is not None
        aboutAction.setStatusTip("About SMACC (version and links).")
        aboutAction.triggered.connect(self.show_about_popup)
        quitAction = fileMenu.addAction(
            style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_DialogCloseButton),
            "&Quit",
        )
        assert quitAction is not None
        quitAction.setShortcut("Ctrl+Q")
        quitAction.setStatusTip("Quit SMACC.")
        quitAction.triggered.connect(self.close)

    # ----- actions ----------------------------------------------------------

    def _open_session(self) -> None:
        """Choose a SMACC file + metadata, then start a session in its data dir.

        Opened from "Session…" (and from a double-clicked .smacc, which preselects
        that file the first time). Cancel backs out — and, since the double-click
        flow runs before the launcher is shown, brings the launcher up rather than
        leaving no window. The chosen file is re-checked before committing (#186):
        it may have changed on disk since the dialog selected it.
        """
        preselect = self._launch_file or resolve_initial_settings(
            preferences.load_preferences(preferences_path)
        )
        self._launch_file = None  # a launch file preselects only the first time
        dialog = dialogs.StartSessionDialog(preselect=preselect, parent=self)
        if not dialog.exec():
            self.show()
            return
        path = dialog.chosen_path()
        if path and not dialogs.validate_settings_file(path, self):
            self.show()
            return
        subject, session_id, notes = dialog.get_inputs()
        metadata = {"subject": subject, "session": session_id, "notes": notes}
        data_dir = (
            settings.load_data_directory(path, DEFAULT_DATA_DIR)
            if path
            else DEFAULT_DATA_DIR
        )
        session = SmaccSession(data_dir, metadata=metadata)
        window = SmaccWindow(session, settings_path=path)
        if path:
            dialogs.remember_settings(path)  # a started file joins the recents
            preferences.update_preferences(preferences_path, {"last_settings": path})
        self._open_tool(window)

    def _open_editor(self) -> None:
        """Open the Editor on a new SMACC file or an existing one (from "Editor…")."""
        dialog = dialogs.EditorFileDialog(parent=self)
        if not dialog.exec():
            return
        path = None if dialog.is_new() else dialog.chosen_path()
        data_dir = (
            settings.load_data_directory(path, DEFAULT_DATA_DIR)
            if path
            else DEFAULT_DATA_DIR
        )
        session = SmaccSession(data_dir, design=True)
        self._open_tool(SmaccWindow(session, settings_path=path))

    def design_cues(self) -> None:
        """Open the standalone Audio Cue Designer (exports WAVs to the cues folder)."""
        self._open_tool(CueDesignerWindow(DEFAULT_DATA_DIR / "cues"))

    def analyze_session(self) -> None:
        """Open the Analyzer over the default data directory."""
        self._open_tool(AnalyzeWindow(DEFAULT_DATA_DIR))

    def review_eeg(self) -> None:
        """Open the EEG Annotator in its own process (this binary, re-exec'd).

        Unlike the launcher-managed tools this never hides the launcher: the
        Annotator runs in a separate process so it can outlive the launcher (or
        a session), so there is no ``closed`` signal to bring the launcher back.
        """
        if eeg.launch():
            bar = self.statusBar()
            if bar is not None:
                bar.showMessage("EEG Annotator opened in its own window.", 5000)
            return
        QtWidgets.QMessageBox.warning(
            self,
            "EEG Annotator",
            "Could not start the EEG Annotator.",
        )

    def associate_files(self) -> None:
        """Register SMACC as the Windows handler for .smacc files (packaged build)."""
        try:
            winassoc.register_smacc()
        except OSError as exc:
            QtWidgets.QMessageBox.critical(
                self, "File association", f"Could not associate .smacc files.\n\n{exc}"
            )
            return
        QtWidgets.QMessageBox.information(
            self,
            "File association",
            "SMACC now handles .smacc files — double-click a SMACC file to open it.",
        )

    def check_for_updates(self) -> None:
        """Ask GitHub for a newer release (manual only — never runs on its own).

        The query runs off the GUI thread (:class:`smacc.updates.UpdateChecker`);
        the action is disabled until the result lands so a double-click can't
        stack two checks/dialogs. The checker is kept on ``self`` so it outlives
        this call.
        """
        self._updateAction.setEnabled(False)
        bar = self.statusBar()
        if bar is not None:
            bar.showMessage("Checking for updates…")
        self._update_checker = updates.UpdateChecker(self)
        self._update_checker.finished.connect(self._on_update_result)
        self._update_checker.check()

    def _on_update_result(self, result: updates.UpdateResult) -> None:
        """Show the outcome of a finished update check (GUI thread)."""
        self._updateAction.setEnabled(True)
        bar = self.statusBar()
        if bar is not None:
            bar.clearMessage()
        if result.latest is None:
            QtWidgets.QMessageBox.information(
                self,
                "Check for updates",
                "Could not reach GitHub to check for updates (no internet "
                f"connection?).\n\nReleases are listed at:\n{updates.RELEASES_URL}",
            )
            return
        if not result.newer:
            QtWidgets.QMessageBox.information(
                self,
                "Check for updates",
                f"You are running the latest version of SMACC (v{VERSION}).",
            )
            return
        reply = QtWidgets.QMessageBox.question(
            self,
            "Update available",
            f"SMACC {result.latest} is available (you are running v{VERSION}).\n\n"
            "Open the download page in your browser?",
        )
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(result.url))

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
        """Bring the launcher back after a tool closes.

        Ending a live session is the exception: a night's run is over, so SMACC
        quits outright rather than reopening the launcher. The editor and the
        standalone tools still return here. An editor that saved a file is
        remembered (recents + last_settings) so the next Session… or Editor…
        dialog offers and preselects it.
        """
        tool = self._tool
        if isinstance(tool, SmaccWindow) and not tool.design:
            self.close()  # persists launcher geometry, then quits the app
            return
        if isinstance(tool, SmaccWindow) and tool.settings_path:
            dialogs.remember_settings(tool.settings_path)
            preferences.update_preferences(
                preferences_path, {"last_settings": tool.settings_path}
            )
        # The dark theme is a per-session "lights off" state; a session that ended
        # dark shouldn't leave the launcher dark, so reset to light on return.
        hints = QtGui.QGuiApplication.styleHints()
        assert hints is not None
        hints.setColorScheme(QtCore.Qt.ColorScheme.Light)
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event: QtGui.QCloseEvent | None) -> None:
        """Closing the launcher quits SMACC (it is the app's root window)."""
        # Remember where the launcher sat for next launch (best-effort, never raises).
        preferences.update_window_geometry(
            preferences_path, _LAUNCHER_WINDOW_ID, windowstate.geometry_of(self)
        )
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.quit()
        if event is not None:
            event.accept()
