"""Tests for the Markers window (#132): registry staging, routing, transport."""

from __future__ import annotations

import logging

import pytest
from PyQt6 import QtWidgets

from smacc import events, triggers
from smacc.panels import markers as markers_module
from smacc.panels.markers import MarkersWindow


@pytest.fixture
def stub_serial_ports(monkeypatch):
    """Pin the serial-port list so these tests don't depend on the machine's ports."""
    ports = [("COM2", "USB Trigger Box (COM2)"), ("COM7", "COM7")]
    monkeypatch.setattr(triggers, "list_serial_ports", lambda: ports)
    return ports


@pytest.fixture
def window(qtbot, design_session):
    win = MarkersWindow(design_session)
    qtbot.addWidget(win)
    return win


def _capture_session_log(session) -> list[logging.LogRecord]:
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    session.logger.addHandler(_Capture())
    return records


def _index_of(win: MarkersWindow, key: str) -> int:
    return next(i for i, e in enumerate(win._events) if e.key == key)


# ----- registry table ---------------------------------------------------------


def test_window_stages_the_whole_registry_grouped(window, design_session):
    # Every event is staged (one widget set per event)...
    assert len(window._events) == len(design_session.events)
    assert all(spin is not None for spin in window._code_spins)
    # ...and the table carries one extra (spanned header) row per category group.
    categories = {e.category for e in design_session.events.values()}
    assert window.table.rowCount() == len(design_session.events) + len(categories)
    # The header rows are not mapped to events (not editable/selectable rows).
    assert len(window._row_event) == len(design_session.events)


def test_apply_commits_staged_edits_and_logs_loudly(window, design_session):
    records = _capture_session_log(design_session)
    i = _index_of(window, "REMDetected")
    window._code_spins[i].setValue(99)
    window._lsl_boxes[i].setChecked(False)
    window.apply()
    assert design_session.events["REMDetected"].code == 99
    assert design_session.events["REMDetected"].lsl is False
    assert design_session.events["REMDetected"].ttl is True
    changed = [
        r for r in records if r.getMessage().startswith("Port code changed: REM")
    ]
    assert changed and changed[0].levelno == logging.WARNING
    assert "code 41->99" in changed[0].getMessage()
    assert "LSL off" in changed[0].getMessage()


def test_apply_blocks_on_validation_errors(window, design_session, monkeypatch):
    warned: list[str] = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *a, **k: warned.append(a[2]) or QtWidgets.QMessageBox.StandardButton.Ok,
    )
    # Stage a duplicate routed code: REMDetected takes Clapper's 49.
    window._code_spins[_index_of(window, "REMDetected")].setValue(49)
    window.apply()
    assert warned and "49" in warned[0]
    assert design_session.events["REMDetected"].code == 41  # unchanged


def test_safe_max_round_trips_and_logs(window, design_session):
    records = _capture_session_log(design_session)
    window.safeMaxSpin.setValue(127)
    # 127 would warn on the biocal/dream codes above it; keep them TTL-off so the
    # apply is clean (the point here is the safe-max commit, not the warning).
    for i, event in enumerate(window._events):
        if event.code > 127:
            window._ttl_boxes[i].setChecked(False)
    window.apply()
    assert design_session.event_code_safe_max == 127
    assert any("safe max changed" in r.getMessage() for r in records)


def test_revert_discards_staged_edits(window, design_session):
    i = _index_of(window, "REMDetected")
    window._code_spins[i].setValue(99)
    window._revert()
    i = _index_of(window, "REMDetected")
    assert window._code_spins[i].value() == 41
    assert design_session.events["REMDetected"].code == 41


def test_reload_from_session_picks_up_external_changes(window, design_session):
    new = events.make_custom_event("Door knock", 150, design_session.events.keys())
    design_session.events[new.key] = new
    window.reload_from_session()
    assert any(e.key == new.key for e in window._events)


def test_add_event_stages_a_custom_event(window, monkeypatch):
    class _StubAddDialog:
        def __init__(self, *args, **kwargs):
            pass

        def exec(self):
            return 1  # accepted

        def get_inputs(self):
            return ("New event", 199, "tip", False)

    monkeypatch.setattr(markers_module, "AddEventDialog", _StubAddDialog)
    before = len(window._events)
    window._add_event()
    assert len(window._events) == before + 1
    assert any(e.label == "New event" for e in window._events)


def test_remove_only_removes_custom_events(window, design_session, monkeypatch):
    infos: list[str] = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "information",
        lambda *a, **k: infos.append(a[2]) or QtWidgets.QMessageBox.StandardButton.Ok,
    )
    # A built-in row refuses removal...
    builtin_row = next(
        row for row, i in window._row_event.items() if window._events[i].builtin
    )
    window.table.selectRow(builtin_row)
    window._remove_selected()
    assert infos and "Built-in" in infos[0]
    # ...while a staged custom event goes away.
    new = events.make_custom_event("Door knock", 150, design_session.events.keys())
    design_session.events[new.key] = new
    window.reload_from_session()
    custom_row = next(
        row for row, i in window._row_event.items() if not window._events[i].builtin
    )
    window.table.selectRow(custom_row)
    window._remove_selected()
    assert not any(e.key == new.key for e in window._events)


def test_show_reloads_but_minimize_restore_keeps_edits(window, design_session, qtbot):
    i = _index_of(window, "REMDetected")
    window._code_spins[i].setValue(99)
    window.hide()
    window.show()  # programmatic (re)open -> reload from the session
    assert window._code_spins[_index_of(window, "REMDetected")].value() == 41


# ----- TTL column gating --------------------------------------------------------


def test_ttl_column_grays_out_without_a_transport(window):
    assert window.enabledBox.isChecked() is False
    assert all(not box.isEnabled() for box in window._ttl_boxes)
    # The values are kept (they persist and re-arm with a transport)...
    i = _index_of(window, "REMDetected")
    assert window._ttl_boxes[i].isChecked() is True
    # ...and enabling the transport re-arms the column.
    window.enabledBox.setChecked(True)
    assert all(box.isEnabled() for box in window._ttl_boxes)


# ----- hardware detection hints ---------------------------------------------------


def test_no_serial_ports_shows_the_hint_but_gates_nothing(
    qtbot, design_session, monkeypatch
):
    monkeypatch.setattr(triggers, "list_serial_ports", lambda: [])
    win = MarkersWindow(design_session)
    qtbot.addWidget(win)
    assert not win.portStatusLabel.isHidden()
    # A hint, not a gate: the per-event TTL routing is untouched (not emptied).
    assert win._ttl_boxes[_index_of(win, "REMDetected")].isChecked() is True


def test_attached_serial_ports_hide_the_hint(stub_serial_ports, window):
    assert window.portStatusLabel.isHidden()


def test_refresh_updates_the_port_hint(window, monkeypatch):
    monkeypatch.setattr(triggers, "list_serial_ports", lambda: [])
    window._refresh_ports()
    assert not window.portStatusLabel.isHidden()
    monkeypatch.setattr(triggers, "list_serial_ports", lambda: [("COM2", "COM2")])
    window._refresh_ports()
    assert window.portStatusLabel.isHidden()


def test_missing_inpout_driver_shows_the_hint(qtbot, design_session, monkeypatch):
    monkeypatch.setattr(triggers, "parallel_driver_available", lambda: False)
    win = MarkersWindow(design_session)
    qtbot.addWidget(win)
    assert not win.driverStatusLabel.isHidden()


def test_present_inpout_driver_hides_the_hint(qtbot, design_session, monkeypatch):
    monkeypatch.setattr(triggers, "parallel_driver_available", lambda: True)
    win = MarkersWindow(design_session)
    qtbot.addWidget(win)
    assert win.driverStatusLabel.isHidden()


# ----- hardware transport (the former Trigger output dialog, #28) ----------------


def test_transport_config_round_trips(window, stub_serial_ports):
    cfg = triggers.TriggerConfig(
        enabled=True,
        transport="serial",
        port="COM7",
        baud=57600,
        mode="hold",
        pulse_ms=25,
    )
    window._load_trigger_config(cfg)
    assert window._gather_trigger_config() == cfg


def test_transport_applies_to_the_session(window, design_session, stub_serial_ports):
    records = _capture_session_log(design_session)
    window.enabledBox.setChecked(True)
    window._select_data(window.transportCombo, "serial")
    window.portCombo.setEditText("COM4")
    window.apply()
    assert design_session.trigger_config.enabled is True
    assert design_session.trigger_config.port == "COM4"
    assert any("Trigger output changed" in r.getMessage() for r in records)
    # A design session opens no hardware (set_trigger_output is a no-op there).
    assert design_session.trigger_out is None


def test_selecting_listed_port_returns_device(window, stub_serial_ports):
    window._load_trigger_config(
        triggers.TriggerConfig(enabled=True, transport="serial", port="COM2")
    )
    # The combo shows the descriptive label, but the config gets the device name.
    assert window._gather_trigger_config().port == "COM2"


def test_unlisted_saved_port_survives_as_free_text(window, stub_serial_ports):
    window._load_trigger_config(
        triggers.TriggerConfig(enabled=True, transport="serial", port="COM9")
    )
    assert window._gather_trigger_config().port == "COM9"


def test_test_button_reports_result(window, design_session, monkeypatch):
    monkeypatch.setattr(design_session, "test_trigger", lambda cfg: None)
    window._on_test()
    assert "test pulse" in window.testResult.text()
    monkeypatch.setattr(design_session, "test_trigger", lambda cfg: "no such port")
    window._on_test()
    assert "no such port" in window.testResult.text()


def test_pulse_spin_follows_mode(window):
    window.enabledBox.setChecked(True)
    window._select_data(window.modeCombo, "pulsed")
    window._update_pulse_enabled()
    assert window.pulseSpin.isEnabled()
    window._select_data(window.modeCombo, "hold")
    window._update_pulse_enabled()
    assert not window.pulseSpin.isEnabled()
