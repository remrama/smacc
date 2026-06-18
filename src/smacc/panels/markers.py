"""The Markers window: the definitive home for event-marker configuration (#132).

One tool window shows everything about how SMACC signals events, in one place:

* a **routing legend** — what the log file, the live preview, the LSL stream, and
  the hardware TTL line each receive, and which switch governs it;
* the full **event registry** — every event, including the ones with no grid
  button (lights, panel controls, biocals, chat, system), grouped by category,
  with each event's port code, per-transport LSL/TTL routing, preview flag, and
  increment behavior, plus custom-event add/remove and the TTL safe-max;
* the **hardware transport** — the optional serial/parallel TTL output (#28),
  with a Test button.

It absorbs the former Event codes and Trigger output dialogs. Edits are staged in
working copies and committed by **Apply** (validated first; mid-session changes
are logged at WARNING so the session's code map stays traceable); **Revert**
re-reads the live session. The window also reloads from the session whenever it
is (re)opened and whenever the registry changes elsewhere (e.g. the Event logging
panel's Add event…).
"""

from __future__ import annotations

from dataclasses import replace

from PyQt6 import QtCore, QtGui, QtWidgets

from .. import events, triggers
from ..dialogs import AddEventDialog
from ..fonts import mono_font
from ..session import SmaccSession
from .base import PanelWindow, make_section_title

# Common serial baud rates offered in the dropdown (it stays editable for any other).
_COMMON_BAUDS = (9600, 19200, 38400, 57600, 115200, 230400)

# Registry table grouping: category key -> the group header shown in the table.
# Unknown categories (a hand-edited custom event) are appended after these.
_CATEGORY_LABELS = (
    ("manual", "Event grid"),
    ("control", "Controls & lights"),
    ("biocal", "Biocals"),
    ("system", "System"),
)

# What governs each destination — the read-only legend at the top of the window.
_LEGEND_ROWS = (
    ("Log file", "always on — every event is written to the session log file"),
    (
        "Log preview",
        "the event's Preview box, filtered by the level toggles beside the preview",
    ),
    ("LSL stream", "the event's LSL box"),
    ("Hardware TTL", "the event's TTL box, when a transport is enabled below"),
)


class MarkersWindow(PanelWindow):
    """View and edit the whole marker setup: registry, routing, and transport."""

    TITLE = "Markers"

    # Emitted after Apply commits to the session, so the main window can re-render
    # the registry's other consumers (the Event logging grid's buttons/tooltips).
    changed = QtCore.pyqtSignal()

    def __init__(self, session: SmaccSession, parent: QtWidgets.QWidget | None = None):
        super().__init__(session, parent)
        self.resize(900, 640)
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

        addButton = QtWidgets.QPushButton("Add event…", self)
        addButton.setStatusTip("Add a custom event button.")
        addButton.clicked.connect(self._add_event)
        self.removeButton = QtWidgets.QPushButton("Remove", self)
        self.removeButton.setStatusTip("Remove the selected custom event.")
        self.removeButton.clicked.connect(self._remove_selected)
        self.safeMaxSpin = QtWidgets.QSpinBox(self)
        self.safeMaxSpin.setRange(events.CODE_MIN, events.CODE_MAX)
        self.safeMaxSpin.setStatusTip(
            "TTL-routed codes above this raise a soft warning (some older trigger "
            "hardware accepts only a limited range; LSL carries any code)."
        )
        tableButtonRow = QtWidgets.QHBoxLayout()
        tableButtonRow.addWidget(addButton)
        tableButtonRow.addWidget(self.removeButton)
        tableButtonRow.addStretch(1)
        tableButtonRow.addWidget(QtWidgets.QLabel("TTL safe max code:"))
        tableButtonRow.addWidget(self.safeMaxSpin)

        registryColumn = QtWidgets.QVBoxLayout()
        registryColumn.addWidget(self.table, 1)
        registryColumn.addLayout(tableButtonRow)

        self.applyButton = QtWidgets.QPushButton("Apply", self)
        self.applyButton.setStatusTip(
            "Validate and apply these markers settings to the session."
        )
        self.applyButton.clicked.connect(self.apply)
        self.revertButton = QtWidgets.QPushButton("Revert", self)
        self.revertButton.setStatusTip(
            "Discard unapplied edits and re-read the session's current settings."
        )
        self.revertButton.clicked.connect(self._revert)
        applyRow = QtWidgets.QHBoxLayout()
        applyRow.addStretch(1)
        applyRow.addWidget(self.revertButton)
        applyRow.addWidget(self.applyButton)

        sideColumn = QtWidgets.QVBoxLayout()
        sideColumn.addWidget(self._build_legend())
        sideColumn.addWidget(self._build_transport_group())
        sideColumn.addStretch(1)
        sideColumn.addLayout(applyRow)

        columns = QtWidgets.QHBoxLayout()
        columns.addLayout(registryColumn, 1)
        columns.addLayout(sideColumn)

        container = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout(container)
        outer.addWidget(make_section_title("Markers"))
        outer.addLayout(columns, 1)
        self.setCentralWidget(container)

        self.reload_from_session()

    # ----- legend -------------------------------------------------------------

    def _build_legend(self) -> QtWidgets.QGroupBox:
        """The read-only routing legend: destination -> what governs it."""
        box = QtWidgets.QGroupBox("Where each event goes", self)
        grid = QtWidgets.QGridLayout(box)
        bold = QtGui.QFont()
        bold.setBold(True)
        for row, (name, rule) in enumerate(_LEGEND_ROWS):
            name_label = QtWidgets.QLabel(name, box)
            name_label.setFont(bold)
            rule_label = QtWidgets.QLabel(rule, box)
            rule_label.setWordWrap(True)
            grid.addWidget(name_label, row, 0, QtCore.Qt.AlignmentFlag.AlignTop)
            grid.addWidget(rule_label, row, 1)
        grid.setColumnStretch(1, 1)
        return box

    # ----- transport (the former Trigger output dialog, #28) -------------------

    def _build_transport_group(self) -> QtWidgets.QGroupBox:
        """The optional hardware TTL transport config, with a Test button."""
        box = QtWidgets.QGroupBox("Hardware TTL transport", self)

        self.enabledBox = QtWidgets.QCheckBox("Enable hardware trigger output", box)
        self.enabledBox.setStatusTip(
            "Also drive a physical TTL trigger for amplifiers that read a pulse "
            "(LSL is independent; see the Triggers docs)."
        )
        self.enabledBox.toggled.connect(self._update_enabled_state)

        self.transportCombo = QtWidgets.QComboBox(box)
        self.transportCombo.addItem("Serial (USB trigger box)", "serial")
        self.transportCombo.addItem("Parallel port (LPT)", "parallel")
        self.transportCombo.currentIndexChanged.connect(self._on_transport_changed)

        # Serial page: COM port (editable, in case the rig isn't attached now) + baud.
        self.portCombo = QtWidgets.QComboBox(box)
        self.portCombo.setEditable(True)
        self.portCombo.setMinimumWidth(200)
        refreshButton = QtWidgets.QPushButton("Refresh", box)
        refreshButton.setStatusTip("Rescan for attached serial ports.")
        refreshButton.clicked.connect(self._refresh_ports)
        portRow = QtWidgets.QHBoxLayout()
        portRow.addWidget(self.portCombo, 1)
        portRow.addWidget(refreshButton)
        # Detection hint, not a gate: the combo stays editable and the per-event
        # TTL routing is kept, because studies are usually configured away from
        # the rig — the hint just says nothing is attached *right now*.
        self.portStatusLabel = QtWidgets.QLabel(
            "⚠ No serial ports detected — attach the trigger box and click "
            "Refresh. A typed/saved port is kept and used once attached.",
            box,
        )
        self.portStatusLabel.setWordWrap(True)
        self.baudCombo = QtWidgets.QComboBox(box)
        self.baudCombo.setEditable(True)
        self.baudCombo.addItems([str(b) for b in _COMMON_BAUDS])
        serialPage = QtWidgets.QWidget(box)
        serialForm = QtWidgets.QFormLayout(serialPage)
        serialForm.setContentsMargins(0, 0, 0, 0)
        serialForm.addRow("Port", portRow)
        serialForm.addRow("", self.portStatusLabel)
        serialForm.addRow("Baud", self.baudCombo)

        # Parallel page: base address (hex), with help on finding it.
        self.addressEdit = QtWidgets.QLineEdit(box)
        self.addressEdit.setPlaceholderText(triggers.DEFAULT_LPT_ADDRESS)
        addressHelp = QtWidgets.QLabel(
            "Base I/O address as hex (e.g. 0x378). Find it in Device Manager → the "
            "LPT port → Resources → I/O Range. Needs the InpOut32 driver installed "
            "(see the Triggers docs)."
        )
        addressHelp.setWordWrap(True)
        # Same idea as the serial hint: warn that the driver isn't loadable here
        # and now, without gating any configuration on it.
        self.driverStatusLabel = QtWidgets.QLabel(
            "⚠ InpOut32 driver not detected on this machine — parallel output "
            "will fail until it is installed (see the Triggers docs).",
            box,
        )
        self.driverStatusLabel.setWordWrap(True)
        parallelPage = QtWidgets.QWidget(box)
        parallelForm = QtWidgets.QFormLayout(parallelPage)
        parallelForm.setContentsMargins(0, 0, 0, 0)
        parallelForm.addRow("Address", self.addressEdit)
        parallelForm.addRow("", self.driverStatusLabel)
        parallelForm.addRow("", addressHelp)

        self.transportStack = QtWidgets.QStackedWidget(box)
        self.transportStack.addWidget(serialPage)  # index 0 == serial
        self.transportStack.addWidget(parallelPage)  # index 1 == parallel

        self.modeCombo = QtWidgets.QComboBox(box)
        self.modeCombo.addItem("Pulsed (SMACC times the pulse)", "pulsed")
        self.modeCombo.addItem("Set-and-hold (until next event)", "hold")
        self.modeCombo.currentIndexChanged.connect(self._update_pulse_enabled)
        self.pulseSpin = QtWidgets.QSpinBox(box)
        self.pulseSpin.setRange(1, 1000)
        self.pulseSpin.setSuffix(" ms")

        self.testButton = QtWidgets.QPushButton("Test", box)
        self.testButton.setStatusTip("Send one test pulse through these settings.")
        self.testButton.clicked.connect(self._on_test)
        self.testResult = QtWidgets.QLabel("", box)
        self.testResult.setWordWrap(True)
        testRow = QtWidgets.QHBoxLayout()
        testRow.addWidget(self.testButton)
        testRow.addWidget(self.testResult, 1)

        # The transport/mode/pulse/test controls are gated behind the enable box.
        self._config_widget = QtWidgets.QWidget(box)
        configForm = QtWidgets.QFormLayout(self._config_widget)
        configForm.setContentsMargins(0, 0, 0, 0)
        configForm.addRow("Transport", self.transportCombo)
        configForm.addRow(self.transportStack)
        configForm.addRow("Mode", self.modeCombo)
        configForm.addRow("Pulse width", self.pulseSpin)
        configForm.addRow(testRow)

        layout = QtWidgets.QVBoxLayout(box)
        layout.addWidget(self.enabledBox)
        layout.addWidget(self._config_widget)
        return box

    @staticmethod
    def _select_data(combo: QtWidgets.QComboBox, value: str) -> None:
        """Select the combo entry whose itemData is ``value`` (no-op if absent)."""
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _refresh_ports(self, *, selected: str | None = None) -> None:
        """Repopulate the serial-port dropdown, preserving the current selection."""
        if selected is None:
            selected = self._current_port()
        self.portCombo.clear()
        ports = triggers.list_serial_ports()
        self.portStatusLabel.setVisible(not ports)
        for device, description in ports:
            label = device if description == device else f"{device} — {description}"
            self.portCombo.addItem(label, device)
        if selected:
            index = self.portCombo.findData(selected)
            if index >= 0:
                self.portCombo.setCurrentIndex(index)
            else:
                # Saved port not attached now: show it as free text, and clear the
                # current index so it doesn't resolve back to a *listed* port.
                self.portCombo.setCurrentIndex(-1)
                self.portCombo.setEditText(selected)

    def _on_transport_changed(self) -> None:
        self.transportStack.setCurrentIndex(self.transportCombo.currentIndex())

    def _update_pulse_enabled(self) -> None:
        self.pulseSpin.setEnabled(self.modeCombo.currentData() == "pulsed")

    def _update_enabled_state(self) -> None:
        self._config_widget.setEnabled(self.enabledBox.isChecked())
        self._update_ttl_boxes()

    def _update_ttl_boxes(self) -> None:
        """Gray the TTL column while no hardware transport is enabled.

        The checkbox values are kept (they persist with the study and re-arm when
        a transport is enabled); the disabled state just makes plain that nothing
        reaches a TTL line until the transport below is configured.
        """
        enabled = self.enabledBox.isChecked()
        tip = (
            "Send this event's code over the hardware TTL trigger."
            if enabled
            else "No hardware transport is enabled (see Hardware TTL transport), "
            "so nothing is sent over TTL; the routing is kept for when one is."
        )
        for box in self._ttl_boxes:
            box.setEnabled(enabled)
            box.setToolTip(tip)

    def _current_port(self) -> str:
        """Resolve the chosen port to its device name.

        The combo is editable and its labels may carry a description, so the shown
        text isn't always the device. If it matches a listed entry, return that
        entry's device (itemData); otherwise it's a free-typed port (a rig not
        attached now), so return the text as-is. Avoids the stale ``currentData()``
        an editable combo keeps when its edit text was set without changing index.
        """
        text = self.portCombo.currentText().strip()
        index = self.portCombo.findText(text)
        if index >= 0:
            device = self.portCombo.itemData(index)
            return str(device) if device else text
        return text

    def _current_baud(self) -> int:
        try:
            return int(self.baudCombo.currentText().strip())
        except ValueError:
            return triggers.DEFAULT_BAUD

    def _on_test(self) -> None:
        """Send one test pulse through the staged settings and report the result."""
        error = self.session.test_trigger(self._gather_trigger_config())
        if error:
            self.testResult.setText(f"⚠ {error}")
        else:
            self.testResult.setText("✓ Sent test pulse — check the amplifier.")

    def _gather_trigger_config(self) -> triggers.TriggerConfig:
        """Read the staged transport widgets into a config (committed on Apply)."""
        return triggers.TriggerConfig(
            enabled=self.enabledBox.isChecked(),
            transport=self.transportCombo.currentData(),
            port=self._current_port(),
            baud=self._current_baud(),
            address=self.addressEdit.text().strip() or triggers.DEFAULT_LPT_ADDRESS,
            mode=self.modeCombo.currentData(),
            pulse_ms=self.pulseSpin.value(),
        )

    def _load_trigger_config(self, config: triggers.TriggerConfig) -> None:
        """Seed the transport widgets from ``config``, then sync dependent states."""
        self.enabledBox.setChecked(config.enabled)
        self._select_data(self.transportCombo, config.transport)
        self._select_data(self.modeCombo, config.mode)
        self._refresh_ports(selected=config.port)
        # Re-probed on every (re)load, so installing the driver and reopening the
        # window clears the hint without restarting SMACC.
        self.driverStatusLabel.setVisible(not triggers.parallel_driver_available())
        self.baudCombo.setCurrentText(str(config.baud))
        self.addressEdit.setText(config.address)
        self.pulseSpin.setValue(config.pulse_ms)
        self.testResult.setText("")
        self._on_transport_changed()
        self._update_pulse_enabled()
        self._update_enabled_state()

    # ----- registry table -----------------------------------------------------

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
        # The per-event widget lists are appended in event order below, so seed
        # them index-aligned first.
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
        self._update_ttl_boxes()

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
        """Read widget values back into ``self._events`` before add/remove/apply."""
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
                self, self.TITLE, "Built-in events can't be removed."
            )
            return
        del self._events[i]
        self._populate()

    # ----- session sync (reload / apply) ----------------------------------------

    def reload_from_session(self) -> None:
        """Replace all staged edits with the session's current marker setup."""
        self._events = [replace(e) for e in self.session.events.values()]
        self.safeMaxSpin.setValue(int(self.session.event_code_safe_max))
        self._populate()
        self._load_trigger_config(self.session.trigger_config)

    def _revert(self) -> None:
        self.reload_from_session()
        status_bar = self.statusBar()
        assert status_bar is not None
        status_bar.showMessage("Reverted to the session's current settings", 4000)

    def apply(self) -> None:
        """Validate and commit the staged registry + transport to the session.

        Mirrors the old dialogs' accept paths: hard validation errors block the
        apply, soft warnings ask first, and every change is logged at WARNING so a
        mid-session edit stays traceable in the log. The transport is (re)opened
        from the new config; a failure is surfaced but never blocks the registry
        apply (the session falls back to LSL-only, as at load).
        """
        self._sync()
        candidate = [replace(e) for e in self._events]
        safe_max = self.safeMaxSpin.value()
        errors, warnings = events.validate_events(candidate, safe_max)
        if errors:
            QtWidgets.QMessageBox.warning(
                self, self.TITLE, "Please fix these first:\n\n" + "\n".join(errors)
            )
            return
        if warnings:
            reply = QtWidgets.QMessageBox.question(
                self, self.TITLE, "Apply anyway?\n\n" + "\n".join(warnings)
            )
            if reply != QtWidgets.QMessageBox.StandardButton.Yes:
                return
        self._log_registry_changes(candidate, safe_max)
        self.session.events = {e.key: e for e in candidate}
        self.session.event_code_safe_max = safe_max

        config = self._gather_trigger_config()
        if config != self.session.trigger_config:
            self.session.logger.warning(f"Trigger output changed: {config.summary()}")
        self.session.trigger_config = config
        error = self.session.set_trigger_output(config)
        status_bar = self.statusBar()
        assert status_bar is not None
        status_bar.showMessage("Applied", 4000)
        self.changed.emit()
        if error:
            self.session.show_error_popup(
                "Hardware trigger unavailable.", error, parent=self
            )

    def _log_registry_changes(
        self, new_events: list[events.EventDef], safe_max: int
    ) -> None:
        """Log every registry difference loudly (WARNING).

        The window stays available throughout a session (there's no reliable lock
        point), so each change is recorded with a timestamp to keep the session's
        code map traceable even if it changes mid-study.
        """
        before = dict(self.session.events)
        new_by_key = {e.key: e for e in new_events}
        for event in new_events:
            old = before.get(event.key)
            if old is None:
                self.session.logger.warning(
                    f"Event added: {event.label} (code {event.code})"
                )
                continue
            changes = []
            if old.code != event.code:
                changes.append(f"code {old.code}->{event.code}")
            if old.lsl != event.lsl:
                changes.append(f"LSL {'on' if event.lsl else 'off'}")
            if old.ttl != event.ttl:
                changes.append(f"TTL {'on' if event.ttl else 'off'}")
            if old.preview != event.preview:
                changes.append(f"preview {'on' if event.preview else 'off'}")
            if old.increment != event.increment:
                changes.append(f"increment {'on' if event.increment else 'off'}")
            if changes:
                self.session.logger.warning(
                    f"Port code changed: {event.label} ({', '.join(changes)})"
                )
        for key, old in before.items():
            if key not in new_by_key:
                self.session.logger.warning(f"Event removed: {old.label}")
        if safe_max != self.session.event_code_safe_max:
            self.session.logger.warning(
                f"Event-code safe max changed: "
                f"{self.session.event_code_safe_max} -> {safe_max}"
            )

    def showEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        """Re-read the session whenever the window is (re)opened.

        Closing a tool window only hides it, so without this a reopened Markers
        window could show a stale staging of a registry that changed elsewhere
        (a study load, the Event logging panel's Add event…). Spontaneous show
        events (e.g. restoring from minimized) keep the staged edits.
        """
        if not event.spontaneous():
            self.reload_from_session()
        super().showEvent(event)
