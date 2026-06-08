"""The Analyze window: post-hoc tools over a past session, with no live session.

Reached from the launcher's **Analyze session**. Point it at a session — a
``.log`` file, a session folder (its log is found automatically), or a zipped
session/study — and it shows a summary (events, duration, subject/session, dream
reports) and offers to export the events to BIDS or recover the study config from
the log. All the parsing is done by the pure helpers in :mod:`smacc.bids`.
"""

from __future__ import annotations

import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt5 import QtCore, QtGui, QtWidgets

from . import bids, settings
from .dialogs import ask_initial_or_final
from .panels.base import make_section_title
from .paths import LOGO_PATH, studies_directory
from .toolwindow import ToolWindow

if TYPE_CHECKING:
    from .study import Study


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
    """Summarize a past session and export its events / recover its study."""

    def __init__(self, study: Study | None = None) -> None:
        super().__init__()
        # Default the open dialogs to the current study's runs when known.
        self._default_dir = (
            str(study.sessions_dir) if study is not None else str(studies_directory)
        )
        self._log_path: Path | None = None
        self._base_dir: Path | None = None
        self._temp_dirs: list[Path] = []  # extracted zips, cleaned up on close
        self.setWindowTitle("SMACC — Analyze session")
        if LOGO_PATH.is_file():
            self.setWindowIcon(QtGui.QIcon(str(LOGO_PATH)))
        self._build()
        self._set_loaded(False)

    # ----- UI construction --------------------------------------------------

    def _build(self) -> None:
        central = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)
        layout.addWidget(make_section_title("Analyze session"))

        openFileButton = QtWidgets.QPushButton("Open log / zip…", self)
        openFileButton.setStatusTip("Open a SMACC .log file or a zipped session/study.")
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
        self.sourceLabel.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        layout.addWidget(self.sourceLabel)

        self.summaryLabel = QtWidgets.QLabel("", self)
        self.summaryLabel.setTextFormat(QtCore.Qt.RichText)
        layout.addWidget(self.summaryLabel)

        layout.addWidget(QtWidgets.QLabel("Dream reports:", self))
        self.reportsList = QtWidgets.QListWidget(self)
        layout.addWidget(self.reportsList, 1)

        self.exportButton = QtWidgets.QPushButton("Export events (BIDS)…", self)
        self.exportButton.setStatusTip(
            "Write the events to a BIDS events.tsv + sidecar."
        )
        self.exportButton.clicked.connect(self.export_events)
        self.recoverButton = QtWidgets.QPushButton("Recover study (.smacc)…", self)
        self.recoverButton.setStatusTip(
            "Save the study config recorded in the log to a .smacc file."
        )
        self.recoverButton.clicked.connect(self.recover_study)
        self.revealButton = QtWidgets.QPushButton("Open session folder", self)
        self.revealButton.setStatusTip("Open the session's folder in the file browser.")
        self.revealButton.clicked.connect(self.reveal_folder)
        for button in (self.exportButton, self.recoverButton, self.revealButton):
            layout.addWidget(button)

        self.statusBar()
        self.setCentralWidget(central)
        self.resize(460, 540)

    def _set_loaded(self, loaded: bool) -> None:
        """Enable the action buttons only once a session has been loaded."""
        for button in (self.exportButton, self.recoverButton, self.revealButton):
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
            empty.setFlags(QtCore.Qt.NoItemFlags)
            self.reportsList.addItem(empty)
        self._set_loaded(True)
        self.statusBar().showMessage(f"Loaded {log_path.name}", 5000)

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
            self, "Analyze", f"Exported {count} events to\n{out_path}"
        )

    def recover_study(self) -> None:
        if self._log_path is None:
            return
        which = ask_initial_or_final(self, title="Recover study from log")
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
            self._error("Could not recover the study.", str(exc))
            return
        base = self._base_dir or Path(self._default_dir)
        out_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Recover study (.smacc)",
            str(base / "recovered.smacc"),
            "SMACC study (*.smacc)",
        )
        if not out_path:
            return
        try:
            settings.save_settings(out_path, state, metadata)
        except (OSError, ValueError) as exc:
            self._error("Could not save the study.", str(exc))
            return
        QtWidgets.QMessageBox.information(
            self, "Analyze", f"Saved recovered study to\n{out_path}"
        )

    def reveal_folder(self) -> None:
        if self._base_dir is not None:
            QtGui.QDesktopServices.openUrl(
                QtCore.QUrl.fromLocalFile(str(self._base_dir))
            )

    # ----- helpers / lifecycle ----------------------------------------------

    def _error(self, short: str, detail: str | None = None) -> None:
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Warning)
        box.setWindowTitle("Analyze")
        box.setText(short)
        if detail is not None:
            box.setInformativeText(detail)
        box.exec()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        """Clean up any extracted zips and hand control back to the launcher."""
        for tmp in self._temp_dirs:
            shutil.rmtree(tmp, ignore_errors=True)
        self._temp_dirs.clear()
        event.accept()
        self.closed.emit()
