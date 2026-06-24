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
from ..eventregistry import EventRegistryTable
from ..session import SmaccSession
from .base import PanelWindow, make_section_title

# Common serial baud rates offered in the dropdown (it stays editable for any other).
_COMMON_BAUDS = (9600, 19200, 38400, 57600, 115200, 230400)

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
        # The session-free registry table, shared with the Study Editor (#301).
        self.registry = EventRegistryTable(self)

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
        columns.addWidget(self.registry, 1)
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
        self.registry.set_ttl_enabled(self.enabledBox.isChecked())

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

    # ----- session sync (reload / apply) ----------------------------------------

    def reload_from_session(self) -> None:
        """Replace all staged edits with the session's current marker setup."""
        registry = [replace(e) for e in self.session.events.values()]
        self.registry.load(registry, int(self.session.event_code_safe_max))
        self.registry.set_ttl_enabled(self.session.trigger_config.enabled)
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
        candidate = self.registry.current_events()
        safe_max = self.registry.current_safe_max()
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
