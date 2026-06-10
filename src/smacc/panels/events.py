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

    # Sleep-stage buttons get a fixed keypad regardless of grid position; the rest
    # take the leftover digits 5-9 in order (only 0-9 exist, so extras get none).
    _STAGE_SHORTCUTS = {
        "WakeDetected": "0",
        "N1Detected": "1",
        "N2Detected": "2",
        "N3Detected": "3",
        "REMDetected": "4",
    }
    # Common signals seeded into the editable picker (#121); a study types its own
    # and they are remembered for the rest of the session.
    _SIGNAL_SEEDS = ("LRLR", "LRLRLR", "Sniff", "Eyes up-down", "Facial (EMG)")
    _CONFIDENCE_LEVELS = ("certain", "probable", "possible")

    def __init__(self, session: SmaccSession, parent: QtWidgets.QWidget | None = None):
        super().__init__(session, parent)
        self._grid = QtWidgets.QGridLayout()
        container = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout(container)
        outer.addWidget(make_section_title("Event logging"))
        outer.addLayout(self._grid)
        outer.addLayout(self._build_signal_controls())
        outer.addStretch(1)
        self.setCentralWidget(container)
        self.rebuild()

    def _build_signal_controls(self) -> QtWidgets.QHBoxLayout:
        """Build the pre-arm widgets for the Signal observed marker (#121).

        The marker fires the instant its button is pressed — no blocking dialog —
        so its timing tracks the observation; these selectors only supply the
        free-text detail (signal type + confidence) attached to that marker. The
        type combo is editable for any study-specific signal and remembers entries
        used this session.
        """
        self._signal_combo = QtWidgets.QComboBox(self)
        self._signal_combo.setEditable(True)
        self._signal_combo.addItems(self._SIGNAL_SEEDS)
        self._signal_combo.setStatusTip(
            "Signal type tagged onto the next Signal observed marker"
        )
        self._confidence_group = QtWidgets.QButtonGroup(self)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Signal:"))
        row.addWidget(self._signal_combo, 1)
        row.addWidget(QtWidgets.QLabel("Confidence:"))
        for i, level in enumerate(self._CONFIDENCE_LEVELS):
            radio = QtWidgets.QRadioButton(level, self)
            if i == 0:
                radio.setChecked(True)
            self._confidence_group.addButton(radio)
            row.addWidget(radio)
        return row

    def rebuild(self) -> None:
        """Regenerate the buttons from the session's manual-category events.

        Two-column layout sized to the button count. Sleep-stage buttons get a
        fixed keypad shortcut (0=Wake … 4=REM); the remaining buttons take the
        leftover digits 5-9 in order, and any past that get none. Shortcuts are
        active while this window is focused.
        """
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        manual = [e for e in self.session.events.values() if e.category == "manual"]
        half = (len(manual) + 1) // 2
        fill = iter("56789")
        for i, event in enumerate(manual):
            shortcut = self._STAGE_SHORTCUTS.get(event.key) or next(fill, None)
            label = event.label
            button = QtWidgets.QPushButton(label, self)
            button.setStatusTip(event.tooltip)
            if shortcut is not None:
                button.setText(f"{label} ({shortcut})")
                button.setShortcut(shortcut)
            if event.key == "SignalObserved":
                button.clicked.connect(self._emit_signal_observed)
            elif event.key == "Note":
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

    def _emit_signal_observed(self, _checked: bool = False) -> None:
        """Emit a Signal observed marker tagged with the pre-armed type + confidence.

        Fires immediately so the marker tracks the observation; the picked signal
        type and confidence ride along as the log detail (a comment — confidence
        never gates routing). A freshly typed signal is remembered in the combo.
        """
        signal = self._signal_combo.currentText().strip()
        checked = self._confidence_group.checkedButton()
        confidence = checked.text() if checked is not None else ""
        detail: str | None
        if signal and confidence:
            detail = f"{signal} ({confidence})"
        else:
            detail = signal or confidence or None
        self.session.emit_event("SignalObserved", detail=detail)
        if signal and self._signal_combo.findText(signal) < 0:
            self._signal_combo.addItem(signal)

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
