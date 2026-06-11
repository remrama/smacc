"""Tests for DevicesWindow: combo population and edits into session.devices.

DevicesWindow enumerates audio/BlinkStick hardware when it builds its combos, so
every test takes the ``mock_devices`` fixture (which advertises a fixed device
set). Edits flow through the combos' ``currentIndexChanged`` signals into
``session.devices``; selecting a row fires them synchronously.
"""

from __future__ import annotations

from PyQt6 import QtWidgets

from smacc.panels.devices import DevicesWindow


def test_role_combos_populate_from_enumeration(qtbot, design_session, mock_devices):
    window = DevicesWindow(design_session)
    qtbot.addWidget(window)
    out_combo = window._role_combos["bedroom_out"]
    # Index 0 is the default/none entry, then one row per advertised output.
    assert out_combo.count() == 1 + len(mock_devices["outputs"])
    assert out_combo.itemData(1) == mock_devices["outputs"][0]

    blink_combo = window._role_combos["blinkstick"]
    assert blink_combo.count() == 1 + len(mock_devices["blinksticks"])
    # BlinkStick rows carry the serial as item data.
    assert blink_combo.itemData(1) == mock_devices["blinksticks"][0][1]


def test_reload_from_config_selects_bound_device(qtbot, design_session, mock_devices):
    bound = mock_devices["outputs"][1]
    design_session.devices.bindings["bedroom_out"] = bound
    window = DevicesWindow(design_session)
    qtbot.addWidget(window)
    window.reload_from_config()
    assert window._role_combos["bedroom_out"].currentText() == bound


def test_set_binding_writes_to_session(qtbot, design_session, mock_devices):
    window = DevicesWindow(design_session)
    qtbot.addWidget(window)
    changed = []
    window.changed.connect(lambda: changed.append(True))

    # Selecting a real device row (index > 0) binds it to the role.
    window._role_combos["bedroom_out"].setCurrentIndex(1)
    assert design_session.devices.bindings["bedroom_out"] == mock_devices["outputs"][0]
    assert changed  # the changed signal fired

    # Returning to the default/none entry clears the binding.
    window._role_combos["bedroom_out"].setCurrentIndex(0)
    assert "bedroom_out" not in design_session.devices.bindings


def test_set_routing_writes_to_session(qtbot, design_session, mock_devices):
    window = DevicesWindow(design_session)
    qtbot.addWidget(window)
    combo = window._route_combos["cue_out"]
    # Point cue_out at the control-room output role instead of its default.
    index = combo.findData("control_out")
    assert index >= 0
    combo.setCurrentIndex(index)
    assert design_session.devices.routing["cue_out"] == "control_out"


def test_reload_flags_missing_bound_device(qtbot, design_session, mock_devices):
    design_session.devices.bindings["bedroom_out"] = "Unplugged speaker"
    window = DevicesWindow(design_session)
    qtbot.addWidget(window)
    window.reload_from_config()
    # The bound device isn't among the advertised ones, so it's flagged and the
    # combo falls back to the default entry.
    assert window._role_combos["bedroom_out"].currentIndex() == 0
    assert any("Unplugged speaker" in entry for entry in design_session.missing_devices)


def test_refresh_button_emits_refresh_requested(qtbot, design_session, mock_devices):
    # The in-window Refresh button defers to the session window's rescan via this
    # signal (rather than duplicating the PortAudio re-init).
    window = DevicesWindow(design_session)
    qtbot.addWidget(window)
    button = window.findChild(QtWidgets.QPushButton)
    assert button is not None and button.text() == "Refresh devices (F5)"
    with qtbot.waitSignal(window.refresh_requested, timeout=1000):
        button.click()


def test_hue_role_combo_lists_bridge_targets(
    qtbot, design_session, mock_devices, monkeypatch
):
    from smacc import hue

    design_session.hue_config = hue.HueConfig("192.168.1.50", "key")
    monkeypatch.setattr(hue, "targets", lambda cfg: [("Bed lamp (light 1)", "light:1")])
    window = DevicesWindow(design_session)
    qtbot.addWidget(window)
    combo = window._role_combos["hue"]
    assert [combo.itemText(i) for i in range(combo.count())] == [
        "(none)",
        "Bed lamp (light 1)",
    ]
    combo.setCurrentIndex(1)  # bind the lamp
    assert design_session.devices.bindings["hue"] == "light:1"


def test_hue_role_combo_is_empty_without_a_bridge(qtbot, design_session, mock_devices):
    window = DevicesWindow(design_session)
    qtbot.addWidget(window)
    combo = window._role_combos["hue"]
    assert [combo.itemText(i) for i in range(combo.count())] == ["(none)"]
