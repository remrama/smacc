"""Event-logging window: the manual event-marker buttons (built-in + custom).

The lights toggle stays on the main window (it also drives the dark theme); every
other manual event button lives here so a study's custom buttons can be added or
removed (via File ▸ Event codes…) and the grid resized to fit. The grid is rebuilt
whenever the registry changes.
"""

from __future__ import annotations

from functools import partial

from PyQt6 import QtWidgets

from ..session import SmaccSession
from .base import ModalityWindow, make_section_title


class EventsWindow(ModalityWindow):
    """A rebuildable grid of manual event-marker buttons."""

    TITLE = "Event logging"

    def __init__(self, session: SmaccSession, parent: QtWidgets.QWidget | None = None):
        super().__init__(session, parent)
        self._grid = QtWidgets.QGridLayout()
        container = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout(container)
        outer.addWidget(make_section_title("Event logging"))
        outer.addLayout(self._grid)
        outer.addStretch(1)
        self.setCentralWidget(container)
        self.rebuild()

    def rebuild(self) -> None:
        """Regenerate the buttons from the session's manual-category events.

        Two-column layout sized to the button count; the first nine buttons get a
        1–9 keyboard shortcut (active while this window is focused).
        """
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        manual = [e for e in self.session.events.values() if e.category == "manual"]
        half = (len(manual) + 1) // 2
        for i, event in enumerate(manual):
            label = event.label
            button = QtWidgets.QPushButton(label, self)
            button.setStatusTip(event.tooltip)
            if i < 9:  # single-key shortcuts only go 1..9
                button.setText(f"{label} ({i + 1})")
                button.setShortcut(str(i + 1))
            if event.key == "Note":
                button.clicked.connect(self.open_note_marker_dialogue)
            elif event.key == "RecordingStarted":
                button.clicked.connect(self._mark_recording_start)
            else:
                button.clicked.connect(partial(self._emit, event.key))
            row, col = (i, 0) if i < half else (i - half, 1)
            self._grid.addWidget(button, row, col)
        self.adjustSize()

    def _emit(self, key: str, _checked: bool = False) -> None:
        self.session.emit_event(key)

    def _mark_recording_start(self, _checked: bool = False) -> None:
        """Stamp the recording-start reference clock and emit its marker (#60)."""
        self.session.mark_recording_start()

    def open_note_marker_dialogue(self, _checked: bool = False) -> None:
        """Prompt for free text and emit a Note marker with it."""
        text, ok = QtWidgets.QInputDialog.getText(
            self, "Note", "Custom note (no commas):"
        )
        if ok:
            self.session.emit_event("Note", detail=text)
