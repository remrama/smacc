"""Tests for the pure :class:`smacc.studyconfig.StudyConfig` model.

No Qt, no GUI: the model is pure data, so these run without the offscreen Qt
platform the panel tests need. The contract is that ``to_settings_dict`` /
``from_settings_dict`` are a faithful, idempotent serializer pair for the flat
``.smacc`` *settings* mapping, emitted in the exact order
``SmaccWindow.gather_settings`` produces.

Note on the shipped ``default.smacc``: it is a hand-trimmed seed in an older key
order that omits every block the live ``gather_settings`` fills in by default
(``cues``, the chat presets, ``volume_cap``, ``devices``, ``trigger_output``,
``hue`` …). So ``from_settings_dict(raw).to_settings_dict() == raw`` is *not*
achievable, and is not the contract — the model upgrades a trimmed seed to a
complete mapping, exactly as the app does on save. The true
``gather_settings() == to_settings_dict()`` equivalence is proven at the GUI
cut-over, against a built window.
"""

from __future__ import annotations

from pathlib import Path

import yaml

import smacc
from smacc import biocals, devices, events, settings, studyconfig, triggers
from smacc.studyconfig import StudyConfig

DEFAULT_SMACC = Path(smacc.__file__).parent / "assets" / "default.smacc"

# The exact flat key order SmaccWindow.gather_settings emits, for a config with
# no chat presets set (the two preset keys slot in after survey_options when
# present — see test_presets_emit_in_gather_order).
EXPECTED_ORDER = [
    "biocals",
    "visual_cues",
    "visual_attack",
    "visual_release",
    "cues",
    "cue_attack",
    "cue_release",
    "noise_volume",
    "noise_color",
    "noise_source",
    "noise_file",
    "survey_url",
    "survey_options",
    "chat_font_size",
    "chat_red_text",
    "volume_cap",
    "output_latency",
    "devices",
    "event_codes",
    "event_code_safe_max",
    "trigger_output",
    "data_directory",
    "preview_levels",
    "always_on_top",
    "tool_always_on_top",
]


def _full_settings() -> dict:
    """A self-consistent kitchen-sink mapping with every block populated.

    Each block is built through its owning module's emitter (or the model's cue
    helpers), so the fixture is exactly what ``to_settings_dict`` would emit and
    a round-trip is expected to reproduce it byte-for-byte.
    """
    dev = devices.default_config()  # complete routing, so from_dict round-trips
    custom = events.EventDef(
        key="DoorKnock",
        label="Door knock",
        code=150,
        category="manual",
        builtin=False,
    )
    return {
        "biocals": {
            "voice_volume": 0.4,
            "rows": biocals.rows_to_list(biocals.default_rows()),
        },
        "visual_cues": [
            studyconfig.visual_cue_to_dict(
                studyconfig.VisualCue("Glow", "#00ff00", 0.8, "pulse", 2.0, 0.5, True)
            )
        ],
        "visual_attack": 0.1,
        "visual_release": 0.2,
        "cues": [
            studyconfig.cue_to_dict(
                studyconfig.AudioCue("Buzz", "cues/buzz.wav", 0.3, True)
            )
        ],
        "cue_attack": 0.05,
        "cue_release": 0.15,
        "noise_volume": 0.3,
        "noise_color": "pink",
        "noise_source": "file",
        "noise_file": "noise/pink.wav",
        "survey_url": "smacc://survey/lusk",
        "survey_options": {"Morning report": "https://example.com/m"},
        "chat_experimenter_presets": ["How asleep were you?"],
        "chat_participant_presets": ["1", "2"],
        "chat_font_size": 22,
        "chat_red_text": True,
        "volume_cap": 0.8,
        "output_latency": "low",
        "devices": dev.to_study_dict(),  # routing only; bindings are rig-local (#300)
        "event_codes": events.events_to_list([*events.default_events(), custom]),
        "event_code_safe_max": 200,
        "trigger_output": triggers.TriggerConfig(
            enabled=True, mode="hold", pulse_ms=5
        ).to_study_dict(),  # behavior only; port/baud/address are rig-local
        "data_directory": "data",
        "preview_levels": ["DEBUG", "INFO"],
        "always_on_top": True,
        "tool_always_on_top": {"events": True},
    }


def _yaml(mapping: dict) -> str:
    return yaml.safe_dump(
        mapping, sort_keys=False, default_flow_style=False, allow_unicode=True
    )


# ----- fresh defaults --------------------------------------------------------


def test_fresh_config_serializes_to_documented_defaults():
    out = StudyConfig().to_settings_dict()
    assert out["noise_volume"] == 0.2
    assert out["noise_color"] == "white"
    assert out["noise_source"] == "builtin"
    assert out["cue_attack"] == 0.0
    assert out["volume_cap"] == 1.0
    assert out["output_latency"] == "high"
    assert out["chat_font_size"] == 18
    assert out["chat_red_text"] is False
    assert out["cues"] == []
    assert out["visual_cues"] == []
    assert out["biocals"] == {"voice_volume": 0.5}  # rows unspecified -> omitted
    assert out["data_directory"] == "data"
    assert out["event_code_safe_max"] == 255
    assert out["preview_levels"] == ["INFO", "WARNING", "ERROR", "CRITICAL"]
    assert out["always_on_top"] is False
    assert out["tool_always_on_top"] == {}
    # The study carries only the portable half of devices/trigger; bindings, the
    # trigger port, and the Hue credential are rig-local (#300).
    assert out["devices"] == devices.default_config().to_study_dict()
    assert "bindings" not in out["devices"]
    assert out["trigger_output"] == triggers.TriggerConfig().to_study_dict()
    assert "hue" not in out
    assert out["event_codes"] == events.events_to_list(events.default_events())


def test_emission_order_matches_gather_settings():
    assert list(StudyConfig().to_settings_dict().keys()) == EXPECTED_ORDER


def test_empty_mapping_yields_defaults():
    assert StudyConfig.from_settings_dict({}).to_settings_dict() == (
        StudyConfig().to_settings_dict()
    )


# ----- the round-trip contract ----------------------------------------------


def test_kitchen_sink_round_trips_exactly():
    full = _full_settings()
    out = StudyConfig.from_settings_dict(full).to_settings_dict()
    assert out == full


def test_round_trip_is_byte_stable():
    full = _full_settings()
    pass1 = StudyConfig.from_settings_dict(full).to_settings_dict()
    pass2 = StudyConfig.from_settings_dict(pass1).to_settings_dict()
    assert _yaml(pass1) == _yaml(pass2)  # deterministic order + stable values


def test_smacc_file_round_trips_byte_stable_through_the_model(tmp_path):
    # The keystone the Study Editor relies on (#301): a complete study saved as a
    # .smacc, then loaded and re-saved through the model, is byte-identical. Proves
    # "the editor's save is a faithful, stable .smacc" before the editor exists.
    full = _full_settings()
    meta = {"subject": "", "session": "", "notes": ""}
    path1 = tmp_path / "study.smacc"
    settings.save_settings(str(path1), full, meta)
    raw, loaded_meta = settings.load_settings(str(path1))
    rebuilt = StudyConfig.from_settings_dict(raw).to_settings_dict()
    path2 = tmp_path / "study2.smacc"
    settings.save_settings(str(path2), rebuilt, loaded_meta)
    assert path1.read_text(encoding="utf-8") == path2.read_text(encoding="utf-8")


# ----- the shipped default.smacc --------------------------------------------


def test_default_smacc_loads_and_is_idempotent():
    raw, _meta = settings.load_settings(str(DEFAULT_SMACC))
    out1 = StudyConfig.from_settings_dict(raw).to_settings_dict()
    out2 = StudyConfig.from_settings_dict(out1).to_settings_dict()
    assert out1 == out2  # a second round-trip changes nothing

    # Values the seed does carry are preserved.
    assert out1["visual_cues"] == raw["visual_cues"]
    assert out1["noise_color"] == "white"
    assert out1["biocals"]["voice_volume"] == 0.5
    assert out1["event_code_safe_max"] == 255
    assert out1["data_directory"] == "data"

    # Omissions in the seed stay omitted (the None sentinels).
    assert "rows" not in out1["biocals"]
    assert "chat_experimenter_presets" not in out1
    assert "chat_participant_presets" not in out1

    # Blocks the live gather always emits are filled in (the seed upgrades).
    for key in (
        "cues",
        "volume_cap",
        "output_latency",
        "devices",
        "trigger_output",
        "preview_levels",
        "always_on_top",
        "tool_always_on_top",
    ):
        assert key in out1
    assert "hue" not in out1  # the Hue credential is rig-local now (#300)
    assert "bindings" not in out1["devices"]  # bindings are rig-local


# ----- leniency (mirrors each panel's apply_state tolerance) -----------------


def test_malformed_scalars_fall_back_to_defaults():
    out = StudyConfig.from_settings_dict(
        {
            "noise_volume": "loud",
            "chat_font_size": "big",
            "volume_cap": None,
            "output_latency": "full",  # not in {high, low}
            "noise_source": "tape",  # not in {builtin, file}
            "event_code_safe_max": "x",
        }
    ).to_settings_dict()
    assert out["noise_volume"] == 0.2
    assert out["chat_font_size"] == 18
    assert out["volume_cap"] == 1.0
    assert out["output_latency"] == "high"
    assert out["noise_source"] == "builtin"
    assert out["event_code_safe_max"] == 255


def test_chat_font_size_is_clamped():
    assert (
        StudyConfig.from_settings_dict({"chat_font_size": 999}).interface.chat_font_size
        == 72
    )
    assert (
        StudyConfig.from_settings_dict({"chat_font_size": 1}).interface.chat_font_size
        == 8
    )


def test_present_empty_presets_are_a_deliberate_clear():
    out = StudyConfig.from_settings_dict(
        {"chat_experimenter_presets": []}
    ).to_settings_dict()
    assert out["chat_experimenter_presets"] == []  # present-and-empty is honored
    assert "chat_participant_presets" not in out  # still absent -> omitted


def test_absent_biocal_rows_keep_voice_volume_only():
    out = StudyConfig.from_settings_dict({"biocals": {"voice_volume": 0.7}})
    block = out.to_settings_dict()["biocals"]
    assert block == {"voice_volume": 0.7}


def test_present_biocal_rows_round_trip():
    rows = biocals.rows_to_list(biocals.default_rows())
    out = StudyConfig.from_settings_dict(
        {"biocals": {"voice_volume": 0.5, "rows": rows}}
    )
    assert out.to_settings_dict()["biocals"]["rows"] == rows


def test_paths_stay_plain_strings():
    out = StudyConfig.from_settings_dict(
        {"cues": [{"name": "c", "file": "cues/c.wav"}], "noise_file": "n/x.wav"}
    )
    assert out.cueing.audio.cues[0].file == "cues/c.wav"
    assert isinstance(out.cueing.audio.cues[0].file, str)
    assert out.cueing.noise.file == "n/x.wav"
