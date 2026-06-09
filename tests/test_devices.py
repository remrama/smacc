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


def test_migrate_legacy_maps_panel_keys_to_roles():
    cfg = devices.migrate_legacy(
        {
            "cue_device": "Spk, Windows WASAPI",
            "noise_device": "Other, Windows WASAPI",  # ignored: bedroom_out already set
            "recording_device": "Mic, Windows WASAPI",
            "blink_device": "BS012345",
        }
    )
    assert cfg.bindings["bedroom_out"] == "Spk, Windows WASAPI"  # first output wins
    assert cfg.bindings["bedroom_mic"] == "Mic, Windows WASAPI"
    assert cfg.bindings["blinkstick"] == "BS012345"
    assert "control_out" not in cfg.bindings  # new role starts unbound
    assert cfg.device_for("noise_out") == "Spk, Windows WASAPI"  # shares bedroom_out


def test_migrate_legacy_falls_back_to_noise_when_no_cue_device():
    cfg = devices.migrate_legacy({"noise_device": "N, Windows WASAPI"})
    assert cfg.bindings["bedroom_out"] == "N, Windows WASAPI"


def test_load_prefers_devices_block_over_legacy():
    settings = {
        "devices": {"bindings": {"bedroom_out": "New"}, "routing": {}},
        "cue_device": "Old",  # legacy key ignored when a devices block is present
    }
    assert devices.load(settings).device_for("cue_out") == "New"


def test_load_migrates_when_no_devices_block():
    assert devices.load({"cue_device": "Spk"}).device_for("cue_out") == "Spk"
