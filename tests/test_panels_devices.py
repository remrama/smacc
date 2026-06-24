"""Tests for DevicesWindow: combo population and edits into session.devices.

DevicesWindow enumerates audio/BlinkStick hardware when it builds its combos, so
every test takes the ``mock_devices`` fixture (which advertises a fixed device
set). Edits flow through the combos' ``currentIndexChanged`` signals into
``session.devices``; selecting a row fires them synchronously.
"""

from __future__ import annotations

from PyQt6 import QtWidgets

from smacc.panels.devices import DevicesWindow


def test_equipment_combos_populate_from_enumeration(
    qtbot, headless_session, mock_devices
):
    window = DevicesWindow(headless_session)
    qtbot.addWidget(window)
    out_combo = window._equipment_combos["bedroom_speaker"]
    # Index 0 is the "(none)" entry, then one row per advertised output.
    assert out_combo.itemText(0) == "(none)"
    assert out_combo.count() == 1 + len(mock_devices["outputs"])
    assert out_combo.itemData(1) == mock_devices["outputs"][0]

    blink_combo = window._equipment_combos["blinkstick_light"]
    assert blink_combo.count() == 1 + len(mock_devices["blinksticks"])
    # BlinkStick rows carry the serial as item data.
    assert blink_combo.itemData(1) == mock_devices["blinksticks"][0][1]


def test_reload_from_config_selects_bound_device(qtbot, headless_session, mock_devices):
    bound = mock_devices["outputs"][1]
    headless_session.devices.bindings["bedroom_speaker"] = bound
    window = DevicesWindow(headless_session)
    qtbot.addWidget(window)
    window.reload_from_config()
    assert window._equipment_combos["bedroom_speaker"].currentText() == bound


def test_set_binding_writes_to_session(qtbot, headless_session, mock_devices):
    window = DevicesWindow(headless_session)
    qtbot.addWidget(window)
    changed = []
    window.changed.connect(lambda: changed.append(True))

    # Selecting a real device row binds it to the equipment.
    window._equipment_combos["bedroom_speaker"].setCurrentIndex(1)
    assert (
        headless_session.devices.bindings["bedroom_speaker"]
        == mock_devices["outputs"][0]
    )
    assert changed  # the changed signal fired

    # Returning to the "(none)" entry clears the binding.
    window._equipment_combos["bedroom_speaker"].setCurrentIndex(0)
    assert "bedroom_speaker" not in headless_session.devices.bindings


def test_set_routing_writes_to_session(qtbot, headless_session, mock_devices):
    window = DevicesWindow(headless_session)
    qtbot.addWidget(window)
    combo = window._action_combos["play_audio_cue"]
    # Point play_audio_cue at the control-room output equipment instead of its default.
    index = combo.findData("control_speaker")
    assert index >= 0
    combo.setCurrentIndex(index)
    assert headless_session.devices.routing["play_audio_cue"] == "control_speaker"


def test_reload_flags_missing_bound_device(qtbot, headless_session, mock_devices):
    headless_session.devices.bindings["bedroom_speaker"] = "Unplugged speaker"
    window = DevicesWindow(headless_session)
    qtbot.addWidget(window)
    window.reload_from_config()
    # The bound device isn't among the advertised ones, so it's flagged and shown
    # as an explicit "(not connected)" row; the binding is kept, never swapped.
    combo = window._equipment_combos["bedroom_speaker"]
    assert combo.currentText() == "Unplugged speaker (not connected)"
    assert combo.currentData() == "Unplugged speaker"
    assert headless_session.devices.bindings["bedroom_speaker"] == "Unplugged speaker"
    assert any(
        "Unplugged speaker" in entry for entry in headless_session.missing_devices
    )


def test_refresh_button_emits_refresh_requested(qtbot, headless_session, mock_devices):
    # The in-window Refresh button defers to the session window's rescan via this
    # signal (rather than duplicating the PortAudio re-init).
    window = DevicesWindow(headless_session)
    qtbot.addWidget(window)
    button = window.findChild(QtWidgets.QPushButton)
    assert button is not None and button.text() == "Refresh devices (F5)"
    with qtbot.waitSignal(window.refresh_requested, timeout=1000):
        button.click()


def test_hue_combo_lists_bridge_targets(
    qtbot, headless_session, mock_devices, monkeypatch
):
    from smacc import hue

    headless_session.hue_config = hue.HueConfig("192.168.1.50", "key")
    monkeypatch.setattr(hue, "targets", lambda cfg: [("Bed lamp (light 1)", "light:1")])
    window = DevicesWindow(headless_session)
    qtbot.addWidget(window)
    combo = window._equipment_combos["philips_hue_light"]
    assert [combo.itemText(i) for i in range(combo.count())] == [
        "(none)",
        "Bed lamp (light 1)",
    ]
    combo.setCurrentIndex(1)  # bind the lamp
    assert headless_session.devices.bindings["philips_hue_light"] == "light:1"


def test_hue_combo_says_no_bridge_without_one(qtbot, headless_session, mock_devices):
    window = DevicesWindow(headless_session)
    qtbot.addWidget(window)
    combo = window._equipment_combos["philips_hue_light"]
    assert [combo.itemText(i) for i in range(combo.count())] == ["No bridge paired"]


def test_empty_enumeration_says_no_device_found(
    qtbot, headless_session, mock_no_devices
):
    # With nothing connected, each combo's sole row says so (#139) instead of an
    # ambiguous "(none)" (or the old "(system default)", which implied an output
    # exists when none does).
    window = DevicesWindow(headless_session)
    qtbot.addWidget(window)
    texts = {
        key: [combo.itemText(i) for i in range(combo.count())]
        for key, combo in window._equipment_combos.items()
    }
    assert texts["bedroom_speaker"] == ["No output device found"]
    assert texts["control_speaker"] == ["No output device found"]
    assert texts["bedroom_mic_1"] == ["No input device found"]
    assert texts["control_mic"] == ["No input device found"]
    assert texts["blinkstick_light"] == ["No BlinkStick found"]
    assert texts["philips_hue_light"] == ["No bridge paired"]


def test_paired_bridge_with_no_targets_says_no_lights(
    qtbot, headless_session, mock_devices, monkeypatch
):
    from smacc import hue

    headless_session.hue_config = hue.HueConfig("192.168.1.50", "key")
    monkeypatch.setattr(hue, "targets", lambda cfg: [])
    window = DevicesWindow(headless_session)
    qtbot.addWidget(window)
    combo = window._equipment_combos["philips_hue_light"]
    assert [combo.itemText(i) for i in range(combo.count())] == ["No lights found"]


def test_autobind_defaults_pins_the_required_equipment(
    qtbot, live_session, mock_devices
):
    window = DevicesWindow(live_session)
    qtbot.addWidget(window)
    changed = []
    window.changed.connect(lambda: changed.append(True))
    window.autobind_defaults()
    # The current Windows defaults are bound explicitly, by name (#139); equipment
    # only optional routes use stay unbound.
    bindings = live_session.devices.bindings
    assert bindings["bedroom_speaker"] == mock_devices["default_output"]
    assert bindings["bedroom_mic_1"] == mock_devices["default_input"]
    assert bindings["control_mic"] == mock_devices["default_input"]  # #160
    assert "control_speaker" not in bindings
    assert "bedroom_mic_2" not in bindings
    assert changed  # indicators are told to re-render
    # The combos show the pinned devices.
    out_combo = window._equipment_combos["bedroom_speaker"]
    assert out_combo.currentData() == mock_devices["default_output"]


def test_autobind_defaults_is_a_noop_in_the_editor(
    qtbot, headless_session, mock_devices
):
    window = DevicesWindow(headless_session)
    qtbot.addWidget(window)
    window.autobind_defaults()
    # The editor often runs on a non-rig machine; the rig binds its own defaults.
    assert headless_session.devices.bindings == {}


def test_autobind_defaults_keeps_existing_bindings(qtbot, live_session, mock_devices):
    live_session.devices.bindings["bedroom_speaker"] = mock_devices["outputs"][1]
    window = DevicesWindow(live_session)
    qtbot.addWidget(window)
    window.autobind_defaults()
    # An explicit choice is never overwritten; only the unbound mics are filled.
    assert (
        live_session.devices.bindings["bedroom_speaker"] == mock_devices["outputs"][1]
    )
    assert (
        live_session.devices.bindings["bedroom_mic_1"] == mock_devices["default_input"]
    )
    assert live_session.devices.bindings["control_mic"] == mock_devices["default_input"]


def test_combos_carry_description_tooltips(qtbot, headless_session, mock_devices):
    from smacc import devices

    window = DevicesWindow(headless_session)
    qtbot.addWidget(window)
    for equipment in devices.EQUIPMENT:
        assert (
            window._equipment_combos[equipment.key].toolTip() == equipment.description
        )
    for action in devices.ACTIONS:
        assert window._action_combos[action.key].toolTip() == action.description


def test_route_indicators_show_the_resolved_device(
    qtbot, headless_session, mock_devices
):
    window = DevicesWindow(headless_session)
    qtbot.addWidget(window)
    # A default route on an unbound equipment is honest about it...
    cue = window._action_indicators["play_audio_cue"]
    assert cue.text() == "→ no device"
    # ...an off (optional) route shows nothing...
    assert window._action_indicators["listen_audio_cue"].text() == ""
    # ...and binding the equipment resolves the route live.
    window._equipment_combos["bedroom_speaker"].setCurrentIndex(1)
    assert cue.text() == f"→ {mock_devices['outputs'][0]}"
