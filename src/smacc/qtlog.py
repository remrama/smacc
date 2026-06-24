"""Logging handler that mirrors log records into the GUI log preview list."""

import logging

from PyQt6 import QtCore, QtWidgets


class _LogSignaller(QtCore.QObject):
    """QObject carrying the cross-thread signal for QtLogHandler."""

    message = QtCore.pyqtSignal(str)


class QtLogHandler(logging.Handler):
    """Logging handler that appends records to the GUI log preview list.

    Which records appear is governed by ``enabled_levels`` (an explicit set of
    level numbers), driven by the level checkboxes above the preview so any
    subset of levels can be shown. A record may also opt out of the preview with a falsey
    ``smacc_preview`` attribute (set per event in the Markers window); the file
    handler still receives every record regardless. The widget update is marshalled
    to the GUI thread via a Qt signal, so logging from a non-GUI thread (e.g. the
    audio callback) is safe.

    The preview keeps only the newest ``max_lines`` items (the log *file* keeps
    everything) — an overnight session logs thousands of lines, and an unbounded
    list would grow the GUI's memory and repaint cost all night.
    """

    def __init__(
        self, list_widget: QtWidgets.QListWidget, max_lines: int = 1000
    ) -> None:
        super().__init__()
        self._list = list_widget
        self.max_lines = max(int(max_lines), 1)
        self.enabled_levels: set[int] = {
            logging.INFO,
            logging.WARNING,
            logging.ERROR,
            logging.CRITICAL,
        }
        self._signaller = _LogSignaller()
        self._signaller.message.connect(self._append)

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno not in self.enabled_levels:
            return
        # An event may be sent/logged to file but hidden from the live preview.
        if not getattr(record, "smacc_preview", True):
            return
        try:
            msg = self.format(record)
        except Exception:
            self.handleError(record)
            return
        self._signaller.message.emit(msg)

    def _append(self, msg: str) -> None:
        try:
            self._list.addItem(msg)
            while self._list.count() > self.max_lines:
                self._list.takeItem(0)
            self._list.scrollToBottom()
        except RuntimeError:
            # The preview list was destroyed (its window closed or was GC'd) while
            # this handler still lingered on the shared 'smacc' logger. Drop the
            # line rather than crash on the dead C++ object.
            pass
