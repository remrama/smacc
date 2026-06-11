"""Tests for the pure device-roles model (no Qt, no I/O)."""

from smacc import devices


def test_default_config_routes_targets_to_their_defaults():
    cfg = devices.default_config()
    assert cfg.role_for("cue_out") == "bedroom_out"
    assert cfg.role_for("noise_out") == "bedroom_out"
    assert cfg.role_for("report_in") == "bedroom_mic"
    assert cfg.role_for("visual_out") == "blinkstick"
    # The optional monitoring routes start off.
    assert cfg.role_for("cue_monitor") == ""
    assert cfg.role_for("intercom_listen") == ""
    assert cfg.bindings == {}  # nothing bound yet


def test_device_for_resolves_target_through_role():
    cfg = devices.default_config()
    cfg.bindings["bedroom_out"] = "Speakers, Windows WASAPI"
    cfg.bindings["bedroom_mic"] = "Mic, Windows WASAPI"
    assert cfg.device_for("cue_out") == "Speakers, Windows WASAPI"
    assert cfg.device_for("noise_out") == "Speakers, Windows WASAPI"  # shared sink
    assert cfg.device_for("report_in") == "Mic, Windows WASAPI"


def test_device_for_is_empty_when_role_unbound_or_off():
    cfg = devices.default_config()
    assert cfg.device_for("cue_out") == ""  # role routed but no device bound
    cfg.bindings["control_out"] = "Headphones, Windows WASAPI"
    assert cfg.device_for("cue_monitor") == ""  # optional route still off


def test_room_monitor_defaults_to_the_bedroom_mic():
    # Out of the box the room monitor (#37) shares the bedroom mic, so the cue
    # meter works without binding a separate device.
    cfg = devices.default_config()
    assert cfg.role_for("monitor_in") == "bedroom_mic"
    cfg.bindings["bedroom_mic"] = "Mic, Windows WASAPI"
    assert cfg.device_for("monitor_in") == "Mic, Windows WASAPI"


def test_room_monitor_can_use_a_dedicated_monitor_mic():
    cfg = devices.default_config()
    cfg.bindings["bedroom_mic"] = "Cheap Mic, Windows WASAPI"
    cfg.bindings["monitor_mic"] = "Measurement Mic, Windows WASAPI"
    cfg.routing["monitor_in"] = "monitor_mic"
    assert cfg.device_for("monitor_in") == "Measurement Mic, Windows WASAPI"
    assert cfg.device_for("report_in") == "Cheap Mic, Windows WASAPI"  # unaffected


def test_room_monitor_route_can_be_turned_off():
    cfg = devices.default_config()
    cfg.bindings["bedroom_mic"] = "Mic, Windows WASAPI"
    cfg.routing["monitor_in"] = ""  # optional route set to none
    assert cfg.device_for("monitor_in") == ""


def test_routing_override_enables_a_monitor():
    cfg = devices.default_config()
    cfg.bindings["control_out"] = "Headphones, Windows WASAPI"
    cfg.routing["cue_monitor"] = "control_out"
    assert cfg.device_for("cue_monitor") == "Headphones, Windows WASAPI"


def test_to_dict_from_dict_round_trip():
    cfg = devices.default_config()
    cfg.bindings["bedroom_out"] = "Spk, Windows WASAPI"
    cfg.routing["cue_monitor"] = "control_out"
    restored = devices.from_dict(cfg.to_dict())
    assert restored.bindings == cfg.bindings
    assert restored.routing == cfg.routing


def test_from_dict_drops_unknown_and_invalid_entries():
    cfg = devices.from_dict(
        {
            "bindings": {"bedroom_out": "Spk", "bogus_role": "X", "bedroom_mic": 5},
            "routing": {"cue_out": "control_out", "nope": "x", "noise_out": "bad"},
        }
    )
    assert cfg.bindings == {"bedroom_out": "Spk"}  # bogus role + non-str dropped
    assert cfg.role_for("cue_out") == "control_out"  # valid override kept
    assert cfg.role_for("noise_out") == "bedroom_out"  # invalid role -> default


def test_from_dict_handles_non_mapping():
    cfg = devices.from_dict(None)
    assert cfg.role_for("cue_out") == "bedroom_out"  # falls back to defaults


def test_load_reads_devices_block():
    settings = {"devices": {"bindings": {"bedroom_out": "Spk"}, "routing": {}}}
    assert devices.load(settings).device_for("cue_out") == "Spk"


def test_load_defaults_when_no_devices_block():
    # No devices block -> the default config (each target on its default role, with no
    # devices bound). Per-panel device keys are no longer migrated.
    cfg = devices.load({"cue_device": "Spk"})
    assert cfg.role_for("cue_out") == "bedroom_out"  # default role
    assert cfg.bindings == {}  # nothing bound; the stray key is ignored


def test_both_light_technologies_are_visual_roles():
    # #53: separate BlinkStick and Philips Hue selectors — two roles of the
    # VISUAL kind, with the visual cue routed to whichever is in use.
    roles = devices.ROLES_BY_KEY
    assert roles["blinkstick"].kind == devices.VISUAL
    assert roles["hue"].kind == devices.VISUAL
    cfg = devices.from_dict(
        {"bindings": {"hue": "light:3"}, "routing": {"visual_out": "hue"}}
    )
    assert cfg.device_for("visual_out") == "light:3"
