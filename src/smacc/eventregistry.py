"""The event-code registry table, shared by the Markers window and Study Editor.

A session-free :class:`QtWidgets.QWidget` that edits a study's event registry — the
per-event port code, LSL/TTL/preview/increment routing, plus custom-event add/remove
and the TTL safe-max. It operates purely on a list of :class:`smacc.events.EventDef`
(via :meth:`load` / :meth:`current_events`), so the same table backs both the live
:class:`~smacc.panels.markers.MarkersWindow` (which loads from / applies to the
running session) and the hardware-free Study Editor's Markers section (which loads
from / commits to a :class:`~smacc.studyconfig.StudyConfig`).

It imports no session, panels, ``sounddevice`` or ``pylsl`` — only the pure event
model and the (panels-free) Add-event dialog — so the editor can embed it and stay
hardware-free by construction (enforced by the import-linter contract via #301).
"""

from __future__ import annotations

from dataclasses import replace

from PyQt6 import QtCore, QtGui, QtWidgets

from . import events
from .dialogs import AddEventDialog
from .fonts import mono_font

# Registry table grouping: category key -> the group header shown in the table.
# Unknown categories (a hand-edited custom event) are appended after these.
_CATEGORY_LABELS = (
    ("manual", "Event grid"),
    ("control", "Controls & lights"),
    ("biocal", "Biocals"),
    ("system", "System"),
)


class EventRegistryTable(QtWidgets.QWidget):
    """An editor for a study's event registry: codes, routing, add/remove, safe-max."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._events: list[events.EventDef] = []

        self.table = QtWidgets.QTableWidget(0, 6, self)
        self.table.setHorizontalHeaderLabels(
            ["Event", "Code", "LSL", "TTL", "Preview", "Increment"]
        )
        for col, tip in (
            (1, "The 8-bit port code (1-255) sent when the event fires."),
            (2, "Send this event's code over the LSL marker stream."),
            (
                3,
                "Send this event's code over the hardware TTL trigger "
                "(when one is configured).",
            ),
            (
                4,
                "Show this event in the live log viewer (the log file always records it).",
            ),
            (5, "Advance the code on each firing (e.g. dream reports: 201, 202, …)."),
        ):
            header_item = self.table.horizontalHeaderItem(col)
            if header_item is not None:
                header_item.setToolTip(tip)
        vheader = self.table.verticalHeader()
        assert vheader is not None
        vheader.setVisible(False)
        self.table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        header = self.table.horizontalHeader()
        assert header is not None
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        for col in range(1, 6):
            header.setSectionResizeMode(
                col, QtWidgets.QHeaderView.ResizeMode.ResizeToContents
            )

        self.addButton = QtWidgets.QPushButton("Add event…", self)
        self.addButton.setStatusTip("Add a custom event button.")
        self.addButton.clicked.connect(self._add_event)
        self.removeButton = QtWidgets.QPushButton("Remove", self)
        self.removeButton.setStatusTip("Remove the selected custom event.")
        self.removeButton.clicked.connect(self._remove_selected)
        self.safeMaxSpin = QtWidgets.QSpinBox(self)
        self.safeMaxSpin.setRange(events.CODE_MIN, events.CODE_MAX)
        self.safeMaxSpin.setStatusTip(
            "TTL-routed codes above this raise a soft warning (some older trigger "
            "hardware accepts only a limited range; LSL carries any code)."
        )
        buttonRow = QtWidgets.QHBoxLayout()
        buttonRow.addWidget(self.addButton)
        buttonRow.addWidget(self.removeButton)
        buttonRow.addStretch(1)
        buttonRow.addWidget(QtWidgets.QLabel("TTL safe max code:"))
        buttonRow.addWidget(self.safeMaxSpin)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table, 1)
        layout.addLayout(buttonRow)

    # ----- load / read --------------------------------------------------------

    def load(self, registry: list[events.EventDef], safe_max: int) -> None:
        """Replace the staged registry and rebuild the table."""
        self._events = [replace(e) for e in registry]
        self.safeMaxSpin.setValue(int(safe_max))
        self._populate()

    def current_events(self) -> list[events.EventDef]:
        """The staged registry, with the table's edits folded in (fresh copies)."""
        self._sync()
        return [replace(e) for e in self._events]

    def current_safe_max(self) -> int:
        return self.safeMaxSpin.value()

    def set_ttl_enabled(self, enabled: bool) -> None:
        """Gray the TTL column while no hardware transport is enabled.

        The checkbox values are kept (they persist with the study and re-arm when
        a transport is enabled); the disabled state just makes plain that nothing
        reaches a TTL line until a transport is configured.
        """
        tip = (
            "Send this event's code over the hardware TTL trigger."
            if enabled
            else "No hardware transport is enabled, so nothing is sent over TTL; "
            "the routing is kept for when one is."
        )
        for box in self._ttl_boxes:
            box.setEnabled(enabled)
            box.setToolTip(tip)

    # ----- table build --------------------------------------------------------

    def _populate(self) -> None:
        """(Re)build the table rows from ``self._events``, grouped by category.

        Widgets are kept in lists *aligned with* ``self._events`` (not with table
        rows — the group-header rows offset those); ``self._row_event`` maps a
        table row back to its event index for selection-based actions.
        """
        self._code_spins: list[QtWidgets.QSpinBox] = []
        self._lsl_boxes: list[QtWidgets.QCheckBox] = []
        self._ttl_boxes: list[QtWidgets.QCheckBox] = []
        self._preview_boxes: list[QtWidgets.QCheckBox] = []
        self._increment_boxes: list[QtWidgets.QCheckBox] = []
        self._label_edits: list[QtWidgets.QLineEdit | None] = []
        self._row_event: dict[int, int] = {}

        grouped: dict[str, list[int]] = {}
        for i, event in enumerate(self._events):
            grouped.setdefault(event.category, []).append(i)
        ordered: list[tuple[str, list[int]]] = []
        for key, label in _CATEGORY_LABELS:
            if key in grouped:
                ordered.append((label, grouped.pop(key)))
        for key in list(grouped):  # any unknown category lands after the known ones
            ordered.append((key.title(), grouped.pop(key)))

        self.table.clearContents()
        self.table.setRowCount(sum(len(indices) + 1 for _, indices in ordered))
        for _ in self._events:
            self._code_spins.append(None)  # type: ignore[arg-type]  # filled below
            self._lsl_boxes.append(None)  # type: ignore[arg-type]
            self._ttl_boxes.append(None)  # type: ignore[arg-type]
            self._preview_boxes.append(None)  # type: ignore[arg-type]
            self._increment_boxes.append(None)  # type: ignore[arg-type]
            self._label_edits.append(None)

        row = 0
        bold = QtGui.QFont()
        bold.setBold(True)
        for group_label, indices in ordered:
            header_item = QtWidgets.QTableWidgetItem(group_label)
            header_item.setFont(bold)
            header_item.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(row, 0, header_item)
            self.table.setSpan(row, 0, 1, self.table.columnCount())
            row += 1
            for i in indices:
                self._build_event_row(row, i)
                self._row_event[row] = i
                row += 1

    def _build_event_row(self, row: int, i: int) -> None:
        """Fill table ``row`` with the widgets for event index ``i``."""
        event = self._events[i]
        if event.builtin:
            label_item = QtWidgets.QTableWidgetItem(event.label)
            label_item.setFlags(label_item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
            if event.tooltip:
                label_item.setToolTip(event.tooltip)
            self.table.setItem(row, 0, label_item)
        else:
            label_edit = QtWidgets.QLineEdit(event.label, self)
            label_edit.setPlaceholderText("Custom event label")
            self.table.setCellWidget(row, 0, label_edit)
            self._label_edits[i] = label_edit

        code_spin = QtWidgets.QSpinBox(self)
        code_spin.setRange(events.CODE_MIN, events.CODE_MAX)
        code_spin.setValue(event.code)
        code_spin.setFont(mono_font())  # B612 Mono for the numeric port code (#279)
        self.table.setCellWidget(row, 1, code_spin)
        self._code_spins[i] = code_spin

        for col, checked, boxes in (
            (2, event.lsl, self._lsl_boxes),
            (3, event.ttl, self._ttl_boxes),
            (4, event.preview, self._preview_boxes),
            (5, event.increment, self._increment_boxes),
        ):
            cell, box = self._checkbox_cell(checked)
            self.table.setCellWidget(row, col, cell)
            boxes[i] = box

    @staticmethod
    def _checkbox_cell(checked: bool) -> tuple[QtWidgets.QWidget, QtWidgets.QCheckBox]:
        """Return a ``(container, checkbox)`` with the box centered in its cell."""
        container = QtWidgets.QWidget()
        box = QtWidgets.QCheckBox(container)
        box.setChecked(checked)
        lay = QtWidgets.QHBoxLayout(container)
        lay.addWidget(box)
        lay.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        lay.setContentsMargins(0, 0, 0, 0)
        return container, box

    def _sync(self) -> None:
        """Read widget values back into ``self._events`` before add/remove/read."""
        for i, event in enumerate(self._events):
            label = event.label
            edit = self._label_edits[i]
            if edit is not None:
                label = edit.text().strip() or event.label
            self._events[i] = replace(
                event,
                label=label,
                code=self._code_spins[i].value(),
                lsl=self._lsl_boxes[i].isChecked(),
                ttl=self._ttl_boxes[i].isChecked(),
                preview=self._preview_boxes[i].isChecked(),
                increment=self._increment_boxes[i].isChecked(),
            )

    # ----- add / remove -------------------------------------------------------

    def _suggested_code(self) -> int:
        """A free-ish default code for a new event (one past the current max)."""
        used = [e.code for e in self._events if isinstance(e.code, int)]
        return min((max(used) + 1) if used else events.CODE_MIN, events.CODE_MAX)

    def _add_event(self) -> None:
        self._sync()
        dialog = AddEventDialog(self._suggested_code(), parent=self)
        if not dialog.exec():
            return
        label, code, tooltip, increment = dialog.get_inputs()
        event = events.make_custom_event(
            label,
            code,
            [e.key for e in self._events],
            tooltip=tooltip,
            increment=increment,
        )
        self._events.append(event)
        self._populate()
        for row, i in self._row_event.items():
            if i == len(self._events) - 1:
                self.table.selectRow(row)
                break

    def _remove_selected(self) -> None:
        row = self.table.currentRow()
        i = self._row_event.get(row)
        if i is None:
            return
        self._sync()
        if self._events[i].builtin:
            QtWidgets.QMessageBox.information(
                self, "Markers", "Built-in events can't be removed."
            )
            return
        del self._events[i]
        self._populate()
