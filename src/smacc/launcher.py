"""The SMACC launcher: a small hub for picking a study and choosing what to do.

This is the FSL-style opening menu (#61). Instead of dropping straight into a live
session, SMACC opens this small window so the operator first picks (or creates) a
study, then chooses to **Start session**, **Create study**, or **Analyze session**.

The launcher is the app's persistent root window: opening a tool hides the
launcher, closing the tool brings it back (via the tool's ``closed`` signal), and
closing the launcher quits SMACC (``main`` sets ``quitOnLastWindowClosed`` False).
"""

from __future__ import annotations

from pathlib import Path

from PyQt5 import QtCore, QtGui, QtWidgets

from . import bids, preferences
from .config import VERSION
from .gui import SmaccWindow
from .paths import LOGO_PATH, preferences_path, studies_directory
from .session import SmaccSession
from .study import Study, default_study

# Characters disallowed in a new study folder name (kept to a portable subset).
_INVALID_NAME_CHARS = set('<>:"/\\|?*')


def resolve_initial_study(prefs: dict, studies_dir: str | Path) -> Study:
    """Return the study to preselect at launch: the last-used one, else the default.

    Falls back to the auto-managed ``default`` study when no valid last study is
    recorded (first run, or the folder was moved or deleted).
    """
    last = prefs.get("last_study")
    if last and Path(last).is_dir():
        return Study.open(last)
    return default_study(studies_dir)


class LauncherWindow(QtWidgets.QMainWindow):
    """Small hub window: pick a study, then start / create / analyze."""

    def __init__(self, study: Study) -> None:
        super().__init__()
        self._study = study
        # Held so Qt doesn't garbage-collect the open tool window; replaced (not
        # cleared) when the next tool opens, so it survives its own closeEvent.
        self._tool: QtWidgets.QMainWindow | None = None
        self.setWindowTitle("SMACC")
        if LOGO_PATH.is_file():
            self.setWindowIcon(QtGui.QIcon(str(LOGO_PATH)))
        self._build()
        self._set_study(study)  # seed the label + recents with the launch study

    # ----- UI construction --------------------------------------------------

    def _build(self) -> None:
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

        layout.addWidget(self._build_study_box())

        for label, slot, tip in (
            (
                "Start session",
                self.start_session,
                "Open the live session interface for the selected study.",
            ),
            (
                "Create study",
                self.create_study,
                "Set up a new study folder (config, cues, sessions).",
            ),
            (
                "Analyze session",
                self.analyze_session,
                "Export a past session's events to a BIDS events.tsv.",
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
        footer.setEnabled(False)  # de-emphasized caption
        layout.addWidget(footer)

        self.statusBar()  # give setStatusTip hints somewhere to show
        self.setCentralWidget(central)
        self.resize(360, 460)

    def _build_study_box(self) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("Study", self)
        grid = QtWidgets.QGridLayout(box)
        self.studyLabel = QtWidgets.QLabel(self)
        self.studyLabel.setWordWrap(True)
        self.studyLabel.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.recentCombo = QtWidgets.QComboBox(self)
        self.recentCombo.setStatusTip("Switch to a recently used study.")
        self.recentCombo.activated.connect(self._on_recent_selected)
        openButton = QtWidgets.QPushButton("Open…", self)
        openButton.setStatusTip("Open an existing study folder.")
        openButton.clicked.connect(self.open_study)
        editButton = QtWidgets.QPushButton("Edit…", self)
        editButton.setStatusTip(
            "Edit the current study's configuration in the designer."
        )
        editButton.clicked.connect(self.edit_study)
        grid.addWidget(self.studyLabel, 0, 0, 1, 2)
        grid.addWidget(QtWidgets.QLabel("Recent:"), 1, 0)
        grid.addWidget(self.recentCombo, 1, 1)
        grid.addWidget(openButton, 2, 0)
        grid.addWidget(editButton, 2, 1)
        return box

    # ----- study selection --------------------------------------------------

    def _refresh_study_label(self) -> None:
        self.studyLabel.setText(
            f"<b>{self._study.name}</b><br><small>{self._study.root}</small>"
        )

    def _populate_recents(self) -> None:
        """Fill the recents dropdown from preferences, selecting the current study."""
        prefs = preferences.load_preferences(preferences_path)
        recents = [r for r in prefs.get("recent_studies", []) if isinstance(r, str)]
        self.recentCombo.blockSignals(True)  # programmatic fill: don't fire activated
        self.recentCombo.clear()
        for path in recents:
            self.recentCombo.addItem(Path(path).name, path)
        current = self.recentCombo.findData(str(self._study.root))
        if current >= 0:
            self.recentCombo.setCurrentIndex(current)
        self.recentCombo.blockSignals(False)

    def _on_recent_selected(self, index: int) -> None:
        path = self.recentCombo.itemData(index)
        if not path:
            return
        if not Path(path).is_dir():
            QtWidgets.QMessageBox.warning(
                self, "Study", "That study folder no longer exists."
            )
            self._populate_recents()  # reselect the still-valid current study
            return
        self._set_study(Study.open(path))

    def _set_study(self, study: Study) -> None:
        self._study = study
        self._remember(study)
        self._refresh_study_label()
        self._populate_recents()

    def _remember(self, study: Study) -> None:
        """Push ``study`` onto the persisted recent-studies list (most-recent first)."""
        prefs = preferences.load_preferences(preferences_path)
        recents = [r for r in prefs.get("recent_studies", []) if isinstance(r, str)]
        recents = preferences.push_recent(recents, str(study.root))
        preferences.update_preferences(preferences_path, {"recent_studies": recents})

    def open_study(self) -> None:
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Open study folder", str(studies_directory)
        )
        if path:
            self._set_study(Study.open(path))

    def create_study(self) -> None:
        name, ok = QtWidgets.QInputDialog.getText(self, "New study", "Study name:")
        if not ok:
            return
        name = name.strip()
        if not name or name in {".", ".."} or set(name) & _INVALID_NAME_CHARS:
            QtWidgets.QMessageBox.warning(
                self,
                "New study",
                'Please enter a valid study name (no \\ / : * ? " < > |).',
            )
            return
        try:
            study = Study.create(studies_directory, name)
        except FileExistsError:
            QtWidgets.QMessageBox.warning(
                self, "New study", f"A study named '{name}' already exists."
            )
            return
        except OSError as exc:
            QtWidgets.QMessageBox.critical(self, "New study", str(exc))
            return
        # Drop straight into the designer to configure the new study.
        self._open_designer(study)

    def edit_study(self) -> None:
        """Edit the current study's configuration in the designer."""
        self._open_designer(self._study)

    def _open_designer(self, study: Study) -> None:
        """Open the study designer on ``study`` (loading its config if it has one)."""
        session = SmaccSession(study, design=True)
        settings_path = str(study.config_path) if study.has_config() else None
        window = SmaccWindow(session, settings_path=settings_path)
        self._set_study(study)  # make it current so the launcher reflects it on return
        self._open_tool(window)

    # ----- actions ----------------------------------------------------------

    def start_session(self, settings_path: str | None = None) -> None:
        """Open a live session for the current study (loading its config if any)."""
        session = SmaccSession(self._study)
        if settings_path is None and self._study.has_config():
            settings_path = str(self._study.config_path)
        window = SmaccWindow(session, settings_path=settings_path)
        preferences.update_preferences(
            preferences_path, {"last_study": str(self._study.root)}
        )
        self._open_tool(window)

    def analyze_session(self) -> None:
        """Export a chosen session log to a BIDS events.tsv (+ JSON sidecar)."""
        log_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Choose a SMACC log",
            str(self._study.sessions_dir),
            "SMACC log (*.log)",
        )
        if not log_path:
            return
        out_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export events (BIDS)",
            str(Path(log_path).with_suffix(".tsv")),
            "BIDS events (*.tsv)",
        )
        if not out_path:
            return
        try:
            count = bids.convert_log_file(log_path, out_path)
        except OSError as exc:
            QtWidgets.QMessageBox.critical(self, "Analyze", str(exc))
            return
        QtWidgets.QMessageBox.information(
            self, "Analyze", f"Exported {count} events to\n{out_path}"
        )

    # ----- tool-window lifecycle -------------------------------------------

    def _open_tool(self, window: SmaccWindow) -> None:
        """Show a tool window (it shows itself) and hide the launcher until it closes."""
        self._tool = window
        window.closed.connect(self._on_tool_closed)
        self.hide()

    def _on_tool_closed(self) -> None:
        """Bring the launcher back when a tool window returns control."""
        self._populate_recents()  # a new study may have been created/used meanwhile
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        """Closing the launcher quits SMACC (it is the app's root window)."""
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.quit()
        event.accept()
