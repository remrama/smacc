"""The Analyzer window: post-hoc tools over a past session, with no live session.

Reached from the launcher's **Analyzer**. Point it at a session — a
``.log`` file, a session folder (its log is found automatically), or a zipped
session — and it shows a summary (events, duration, subject/session, dream
reports) and offers to export the events to BIDS or recover the settings from the
log. All the parsing is done by the pure helpers in :mod:`smacc.bids`.
"""

from __future__ import annotations

import shutil
import tempfile
import zipfile
from pathlib import Path

from PyQt6 import QtCore, QtGui, QtWidgets

from . import bids, eeg, preferences, settings, windowstate
from .dialogs import ask_initial_or_final
from .panels.base import make_section_title
from .paths import DEFAULT_DATA_DIR, LOGO_PATH, preferences_path
from .toolwindow import ToolWindow

# Stable id for the analyze window's geometry entry in the per-window prefs map.
_ANALYZE_WINDOW_ID = "analyze"


def format_duration(seconds: float) -> str:
    """Render a span of seconds as a compact ``Hh Mm Ss`` (dropping leading zeros)."""
    total = int(round(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def find_log_in_dir(folder: Path, *, recursive: bool = False) -> Path | None:
    """Return the SMACC ``.log`` in ``folder`` (prefer the one named like it), or None.

    ``recursive`` searches subfolders too (used for an extracted zip, where the log
    may sit under ``sessions/<stem>/``).
    """
    globber = folder.rglob if recursive else folder.glob
    logs = sorted(globber("*.log"))
    if not logs:
        return None
    named = folder / f"{folder.name}.log"
    return named if named in logs else logs[0]


def extract_zip(zip_path: Path, dest: Path) -> None:
    """Extract ``zip_path`` into ``dest``, rejecting entries that escape ``dest``.

    Raises:
        zipfile.BadZipFile: if the archive is not a valid zip.
        ValueError: if a member would extract outside ``dest`` (zip-slip).
        OSError: on read/write failure.
    """
    dest_root = dest.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            target = (dest / member).resolve()
            if target != dest_root and dest_root not in target.parents:
                raise ValueError(f"Unsafe path in zip: {member}")
        zf.extractall(dest)


class AnalyzeWindow(ToolWindow):
    """Summarize a past session and export its events / recover its settings."""

    def __init__(self, data_dir: str | Path | None = None) -> None:
        super().__init__()
        # Default the open dialogs to the current settings' data directory when known.
        self._default_dir = (
            str(data_dir) if data_dir is not None else str(DEFAULT_DATA_DIR)
        )
        self._log_path: Path | None = None
        self._base_dir: Path | None = None
        self._temp_dirs: list[Path] = []  # extracted zips, cleaned up on close
        self.setWindowTitle("SMACC Analyzer")
        if LOGO_PATH.is_file():
            self.setWindowIcon(QtGui.QIcon(str(LOGO_PATH)))
        self._build()
        self._set_loaded(False)
        self.show()  # the launcher hides itself and relies on the tool showing itself

    # ----- UI construction --------------------------------------------------

    def _build(self) -> None:
        central = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)
        layout.addWidget(make_section_title("Analyzer"))

        openFileButton = QtWidgets.QPushButton("Open log / zip…", self)
        openFileButton.setStatusTip("Open a SMACC .log file or a zipped session.")
        openFileButton.clicked.connect(self.open_file)
        openFolderButton = QtWidgets.QPushButton("Open session folder…", self)
        openFolderButton.setStatusTip(
            "Open a session folder (its .log is found automatically)."
        )
        openFolderButton.clicked.connect(self.open_folder)
        openRow = QtWidgets.QHBoxLayout()
        openRow.addWidget(openFileButton)
        openRow.addWidget(openFolderButton)
        layout.addLayout(openRow)

        self.sourceLabel = QtWidgets.QLabel("No session loaded.", self)
        self.sourceLabel.setWordWrap(True)
        self.sourceLabel.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.sourceLabel)

        self.summaryLabel = QtWidgets.QLabel("", self)
        self.summaryLabel.setTextFormat(QtCore.Qt.TextFormat.RichText)
        layout.addWidget(self.summaryLabel)

        layout.addWidget(QtWidgets.QLabel("Dream reports:", self))
        self.reportsList = QtWidgets.QListWidget(self)
        layout.addWidget(self.reportsList, 1)

        self.exportButton = QtWidgets.QPushButton("Export events (BIDS)…", self)
        self.exportButton.setStatusTip(
            "Write the events to a BIDS events.tsv + sidecar."
        )
        self.exportButton.clicked.connect(self.export_events)
        self.recoverButton = QtWidgets.QPushButton("Recover settings (.smacc)…", self)
        self.recoverButton.setStatusTip(
            "Save the settings recorded in the log to a .smacc file."
        )
        self.recoverButton.clicked.connect(self.recover_settings)
        self.revealButton = QtWidgets.QPushButton("Open session folder", self)
        self.revealButton.setStatusTip("Open the session's folder in the file browser.")
        self.revealButton.clicked.connect(self.reveal_folder)
        # Hand the session to the EEG Annotator, which overlays this log on the
        # timeline (#125).
        self.annotateButton = QtWidgets.QPushButton("Open log in EEG Annotator", self)
        self.annotateButton.setStatusTip(
            "Open this session log in the EEG Annotator (overlaid on a recording, "
            "or on its own time axis)."
        )
        self.annotateButton.clicked.connect(self.open_in_annotator)
        for button in (
            self.exportButton,
            self.recoverButton,
            self.revealButton,
            self.annotateButton,
        ):
            layout.addWidget(button)

        self.statusBar()
        self.setCentralWidget(central)
        # Reopen at the last position/size (machine-local), else the default size.
        prefs = preferences.load_preferences(preferences_path)
        geometry = preferences.window_geometry(prefs, _ANALYZE_WINDOW_ID)
        windowstate.restore_geometry(self, geometry, default_size=(460, 540))

    def _set_loaded(self, loaded: bool) -> None:
        """Enable the action buttons only once a session has been loaded."""
        for button in (
            self.exportButton,
            self.recoverButton,
            self.revealButton,
            self.annotateButton,
        ):
            button.setEnabled(loaded)

    # ----- opening a session ------------------------------------------------

    def open_file(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Open SMACC log or zip",
            self._default_dir,
            "SMACC session (*.log *.zip);;All files (*)",
        )
        if not path:
            return
        chosen = Path(path)
        if chosen.suffix.lower() == ".zip":
            self._load_zip(chosen)
        else:
            self._load_log(chosen, chosen.parent)

    def open_folder(self) -> None:
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Open session folder", self._default_dir
        )
        if not path:
            return
        folder = Path(path)
        log = find_log_in_dir(folder)
        if log is None:
            self._error("No .log file found in that folder.")
            return
        self._load_log(log, folder)

    def _load_zip(self, zip_path: Path) -> None:
        try:
            dest = Path(tempfile.mkdtemp(prefix="smacc-analyze-"))
            extract_zip(zip_path, dest)
        except (OSError, zipfile.BadZipFile, ValueError) as exc:
            self._error("Could not open the zip.", str(exc))
            return
        self._temp_dirs.append(dest)
        log = find_log_in_dir(dest, recursive=True)
        if log is None:
            self._error("No .log file found in that zip.")
            return
        self._load_log(log, log.parent)

    def _load_log(self, log_path: Path, base_dir: Path) -> None:
        try:
            text = log_path.read_text(encoding="utf-8")
        except OSError as exc:
            self._error("Could not read the log.", str(exc))
            return
        summary = bids.summarize_log(text)
        self._log_path = log_path
        self._base_dir = base_dir
        self.sourceLabel.setText(
            f"<b>{log_path.name}</b><br><small>{log_path.parent}</small>"
        )
        self.summaryLabel.setText(
            f"Subject: <b>{summary['subject'] or '—'}</b> &nbsp; "
            f"Session: <b>{summary['session'] or '—'}</b><br>"
            f"Duration: <b>{format_duration(summary['duration_seconds'])}</b><br>"
            f"Events: <b>{summary['event_count']}</b>"
        )
        self.reportsList.clear()
        reports = sorted(base_dir.glob("report-*.wav"))
        for report in reports:
            self.reportsList.addItem(report.name)
        if not reports:
            empty = QtWidgets.QListWidgetItem("(none)")
            empty.setFlags(QtCore.Qt.ItemFlag.NoItemFlags)
            self.reportsList.addItem(empty)
        self._set_loaded(True)
        status_bar = self.statusBar()
        assert status_bar is not None
        status_bar.showMessage(f"Loaded {log_path.name}", 5000)

    # ----- actions ----------------------------------------------------------

    def export_events(self) -> None:
        if self._log_path is None:
            return
        out_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export events (BIDS)",
            str(self._log_path.with_suffix(".tsv")),
            "BIDS events (*.tsv)",
        )
        if not out_path:
            return
        try:
            count = bids.convert_log_file(self._log_path, out_path)
        except OSError as exc:
            self._error("Could not export events.", str(exc))
            return
        QtWidgets.QMessageBox.information(
            self, "Analyzer", f"Exported {count} events to\n{out_path}"
        )

    def recover_settings(self) -> None:
        if self._log_path is None:
            return
        which = ask_initial_or_final(self, title="Recover settings from log")
        if which is None:
            return
        try:
            text = self._log_path.read_text(encoding="utf-8")
        except OSError as exc:
            self._error("Could not read the log.", str(exc))
            return
        payload = bids.extract_settings_from_log(text, which)
        if payload is None:
            self._error(
                f"No {which} settings found in that log.",
                "The log may predate settings recording, or the session may have "
                "ended before its final settings were written.",
            )
            return
        try:
            state, metadata = settings.parse_settings_mapping(payload)
        except ValueError as exc:
            self._error("Could not recover the settings.", str(exc))
            return
        base = self._base_dir or Path(self._default_dir)
        out_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Recover settings (.smacc)",
            str(base / "recovered.smacc"),
            "SMACC settings (*.smacc)",
        )
        if not out_path:
            return
        try:
            settings.save_settings(out_path, state, metadata)
        except (OSError, ValueError) as exc:
            self._error("Could not save the settings.", str(exc))
            return
        QtWidgets.QMessageBox.information(
            self, "Analyzer", f"Saved recovered settings to\n{out_path}"
        )

    def reveal_folder(self) -> None:
        if self._base_dir is not None:
            QtGui.QDesktopServices.openUrl(
                QtCore.QUrl.fromLocalFile(str(self._base_dir))
            )

    def open_in_annotator(self) -> None:
        """Hand this session's log to the EEG Annotator as its own process (#125).

        The Analyzer stays the no-EEG summary/BIDS tool; the annotator is where the log
        is seen on a timeline (overlaid on a recording, or standalone). Launched
        detached, like the launcher's EEG Annotator button.
        """
        if self._log_path is None:
            return
        if not eeg.launch(["--log", str(self._log_for_handoff())]):
            self._error(
                "Could not start the EEG Annotator.",
                "Re-running the SMACC installer and selecting the EEG Annotator "
                "component may fix this.",
            )

    def _log_for_handoff(self) -> Path:
        """A log path that outlives this window — copied out of a zip extraction.

        The annotator reads the file later, in its own detached process; a
        zip-extracted log lives under a temp dir this window deletes on close
        (``closeEvent``), so it is copied to a directory the cleanup never
        touches. A log opened directly (its own ``.log`` or a folder) is passed
        through unchanged.
        """
        assert self._log_path is not None
        in_temp = any(tmp in self._log_path.parents for tmp in self._temp_dirs)
        if not in_temp:
            return self._log_path
        # A fresh temp dir deliberately *not* tracked in _temp_dirs, so closeEvent
        # leaves it for the annotator (and the OS) to own.
        keep = Path(tempfile.mkdtemp(prefix="smacc-handoff-"))
        return Path(shutil.copy(self._log_path, keep / self._log_path.name))

    # ----- helpers / lifecycle ----------------------------------------------

    def _error(self, short: str, detail: str | None = None) -> None:
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        box.setWindowTitle("Analyzer")
        box.setText(short)
        if detail is not None:
            box.setInformativeText(detail)
        box.exec()

    def closeEvent(self, event: QtGui.QCloseEvent | None) -> None:
        """Clean up any extracted zips and hand control back to the launcher."""
        # Remember where this window sat for next launch (best-effort, never raises).
        preferences.update_window_geometry(
            preferences_path, _ANALYZE_WINDOW_ID, windowstate.geometry_of(self)
        )
        for tmp in self._temp_dirs:
            shutil.rmtree(tmp, ignore_errors=True)
        self._temp_dirs.clear()
        if event is not None:
            event.accept()
        self.closed.emit()
