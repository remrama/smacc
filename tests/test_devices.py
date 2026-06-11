"""Tests for the pure device-roles model (no Qt, no I/O)."""

from smacc import devices


def test_default_config_routes_targets_to_their_defaults():
    cfg = devices.default_config()
    assert cfg.role_for("play_audio_cue") == "bedroom_speaker"
    assert cfg.role_for("play_noise") == "bedroom_speaker"
    assert cfg.role_for("record_dream_report") == "bedroom_mic_1"
    assert cfg.role_for("play_visual_cue") == "blinkstick_light"
    # The optional monitoring routes start off.
    assert cfg.role_for("listen_audio_cue") == ""
    assert cfg.role_for("listen_to_participant") == ""
    assert cfg.bindings == {}  # nothing bound yet


def test_device_for_resolves_target_through_role():
    cfg = devices.default_config()
    cfg.bindings["bedroom_speaker"] = "Speakers, Windows WASAPI"
    cfg.bindings["bedroom_mic_1"] = "Mic, Windows WASAPI"
    assert cfg.device_for("play_audio_cue") == "Speakers, Windows WASAPI"
    assert cfg.device_for("play_noise") == "Speakers, Windows WASAPI"  # shared sink
    assert cfg.device_for("record_dream_report") == "Mic, Windows WASAPI"


def test_device_for_is_empty_when_role_unbound_or_off():
    cfg = devices.default_config()
    assert cfg.device_for("play_audio_cue") == ""  # role routed but no device bound
    cfg.bindings["control_speaker"] = "Headphones, Windows WASAPI"
    assert cfg.device_for("listen_audio_cue") == ""  # optional route still off


def test_room_monitor_defaults_to_the_bedroom_mic():
    # Out of the box the room monitor (#37) shares the bedroom mic, so the cue
    # meter works without binding a separate device.
    cfg = devices.default_config()
    assert cfg.role_for("monitor_bedroom_noise") == "bedroom_mic_1"
    cfg.bindings["bedroom_mic_1"] = "Mic, Windows WASAPI"
    assert cfg.device_for("monitor_bedroom_noise") == "Mic, Windows WASAPI"


def test_room_monitor_can_use_a_dedicated_monitor_mic():
    cfg = devices.default_config()
    cfg.bindings["bedroom_mic_1"] = "Cheap Mic, Windows WASAPI"
    cfg.bindings["bedroom_mic_2"] = "Measurement Mic, Windows WASAPI"
    cfg.routing["monitor_bedroom_noise"] = "bedroom_mic_2"
    assert cfg.device_for("monitor_bedroom_noise") == "Measurement Mic, Windows WASAPI"
    assert (
        cfg.device_for("record_dream_report") == "Cheap Mic, Windows WASAPI"
    )  # unaffected


def test_room_monitor_route_can_be_turned_off():
    cfg = devices.default_config()
    cfg.bindings["bedroom_mic_1"] = "Mic, Windows WASAPI"
    cfg.routing["monitor_bedroom_noise"] = ""  # optional route set to none
    assert cfg.device_for("monitor_bedroom_noise") == ""


def test_routing_override_enables_a_monitor():
    cfg = devices.default_config()
    cfg.bindings["control_speaker"] = "Headphones, Windows WASAPI"
    cfg.routing["listen_audio_cue"] = "control_speaker"
    assert cfg.device_for("listen_audio_cue") == "Headphones, Windows WASAPI"


def test_to_dict_from_dict_round_trip():
    cfg = devices.default_config()
    cfg.bindings["bedroom_speaker"] = "Spk, Windows WASAPI"
    cfg.routing["listen_audio_cue"] = "control_speaker"
    restored = devices.from_dict(cfg.to_dict())
    assert restored.bindings == cfg.bindings
    assert restored.routing == cfg.routing


def test_from_dict_drops_unknown_and_invalid_entries():
    cfg = devices.from_dict(
        {
            "bindings": {
                "bedroom_speaker": "Spk",
                "bogus_role": "X",
                "bedroom_mic_1": 5,
            },
            "routing": {
                "play_audio_cue": "control_speaker",
                "nope": "x",
                "play_noise": "bad",
            },
        }
    )
    assert cfg.bindings == {"bedroom_speaker": "Spk"}  # bogus role + non-str dropped
    assert cfg.role_for("play_audio_cue") == "control_speaker"  # valid override kept
    assert cfg.role_for("play_noise") == "bedroom_speaker"  # invalid role -> default


def test_from_dict_handles_non_mapping():
    cfg = devices.from_dict(None)
    assert cfg.role_for("play_audio_cue") == "bedroom_speaker"  # falls back to defaults


def test_load_reads_devices_block():
    settings = {"devices": {"bindings": {"bedroom_speaker": "Spk"}, "routing": {}}}
    assert devices.load(settings).device_for("play_audio_cue") == "Spk"


def test_load_defaults_when_no_devices_block():
    # No devices block -> the default config (each target on its default role, with no
    # devices bound). Per-panel device keys are no longer migrated.
    cfg = devices.load({"cue_device": "Spk"})
    assert cfg.role_for("play_audio_cue") == "bedroom_speaker"  # default role
    assert cfg.bindings == {}  # nothing bound; the stray key is ignored


def test_both_light_technologies_are_visual_roles():
    # #53: separate BlinkStick and Philips Hue selectors — two roles of the
    # VISUAL kind, with the visual cue routed to whichever is in use.
    roles = devices.ROLES_BY_KEY
    assert roles["blinkstick_light"].kind == devices.VISUAL
    assert roles["philips_hue_light"].kind == devices.VISUAL
    cfg = devices.from_dict(
        {
            "bindings": {"philips_hue_light": "light:3"},
            "routing": {"play_visual_cue": "philips_hue_light"},
        }
    )
    assert cfg.device_for("play_visual_cue") == "light:3"


# ----- autobind (#139) ---------------------------------------------------------


def test_autobind_roles_are_the_required_audio_defaults():
    # Derived from TARGETS (the default role of each required audio target) plus
    # the intercom source roles (#160). Roles only optional routes point at
    # (control-room speakers, monitor mic) are excluded.
    assert devices.AUTOBIND_ROLES == ("bedroom_speaker", "bedroom_mic_1", "control_mic")


def test_talk_source_is_the_control_room_mic():
    # #160: the intercom talk mic is a bound role, not a routable target (routing
    # it to a bedroom mic would feed the bedroom's sound back out its speakers).
    role = devices.ROLES_BY_KEY[devices.TALK_SOURCE_ROLE]
    assert role.key == "control_mic"
    assert role.kind == devices.INPUT


def test_autobind_fills_only_unbound_roles():
    cfg = devices.default_config()
    cfg.bindings["bedroom_speaker"] = "Kept (USB)"
    filled = devices.autobind(
        cfg, {devices.OUTPUT: "Default Out", devices.INPUT: "Default In"}
    )
    assert cfg.bindings["bedroom_speaker"] == "Kept (USB)"  # never overwritten
    assert cfg.bindings["bedroom_mic_1"] == "Default In"
    assert cfg.bindings["control_mic"] == "Default In"
    assert [(role.key, device) for role, device in filled] == [
        ("bedroom_mic_1", "Default In"),
        ("control_mic", "Default In"),
    ]
    assert "control_speaker" not in cfg.bindings
    assert "bedroom_mic_2" not in cfg.bindings


def test_autobind_skips_kinds_without_a_default():
    cfg = devices.default_config()
    assert devices.autobind(cfg, {devices.OUTPUT: "", devices.INPUT: ""}) == []
    assert cfg.bindings == {}


def test_every_role_and_target_carries_a_description():
    # The Devices window's tooltips come from these; an empty one is a hole in
    # the window's self-documentation.
    assert all(role.description for role in devices.ROLES)
    assert all(target.description for target in devices.TARGETS)
