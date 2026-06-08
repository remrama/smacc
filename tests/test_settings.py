"""Tests for settings YAML save/load (no GUI required)."""

import json

import pytest
import yaml

import smacc
from smacc import settings

SAMPLE_SETTINGS = {
    "cues": [
        {"name": "Cue 1", "file": "cue.wav", "volume": 0.4, "loop": True},
        {"name": "Cue 2", "file": "", "volume": 0.2, "loop": False},
    ],
    "cue_attack": 1.0,
    "cue_release": 1.5,
    "noise_volume": 0.1,
    "noise_color": "pink",
    "noise_source": "builtin",
    "noise_file": "",
    "blink_color": "#ff8800",
    "blink_length": 2.5,
    "survey_url": "",
    "survey_options": {"Morning": "https://example.com/survey"},
}

SAMPLE_METADATA = {"subject": "001", "session": "2", "notes": "n", "created": "x"}


def test_save_load_round_trip(tmp_path):
    path = tmp_path / "settings.yaml"
    settings.save_settings(path, SAMPLE_SETTINGS, SAMPLE_METADATA)
    state, metadata = settings.load_settings(path)
    assert state == SAMPLE_SETTINGS
    assert metadata == SAMPLE_METADATA


def test_saved_file_is_tagged_yaml(tmp_path):
    path = tmp_path / "settings.yaml"
    settings.save_settings(path, {"cue_attack": 0.2}, {})
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert payload["kind"] == settings.KIND
    assert payload["schema_version"] == settings.SCHEMA_VERSION == 3
    assert payload["smacc_version"] == smacc.__version__
    assert payload["settings"] == {"cue_attack": 0.2}


def test_load_accepts_legacy_study_json(tmp_path):
    # Old study.json (no kind, schema 1/2, "state" key) still loads: YAML is a
    # superset of JSON, so the YAML loader reads it directly.
    path = tmp_path / "study.json"
    state = {"cue_file": "cue.wav", "cue_volume": 0.3}
    path.write_text(json.dumps({"schema_version": 1, "state": state}), encoding="utf-8")
    loaded_state, metadata = settings.load_settings(path)
    assert loaded_state == state
    assert metadata == {}


def test_load_accepts_current_schema(tmp_path):
    path = tmp_path / "settings.yaml"
    settings.save_settings(path, {"cue_attack": 1.0}, {})
    state, _ = settings.load_settings(path)
    assert state == {"cue_attack": 1.0}


def test_load_rejects_unsupported_schema(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text(
        yaml.safe_dump({"schema_version": 999, "settings": {}}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="schema version"):
        settings.load_settings(path)


def test_load_rejects_nonpositive_schema(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text(
        yaml.safe_dump({"schema_version": 0, "settings": {}}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="schema version"):
        settings.load_settings(path)


def test_load_rejects_wrong_kind(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text(
        yaml.safe_dump({"kind": "something/else", "schema_version": 3, "settings": {}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="compatible"):
        settings.load_settings(path)


def test_load_rejects_missing_settings(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text(yaml.safe_dump({"schema_version": 3}), encoding="utf-8")
    with pytest.raises(ValueError, match="settings"):
        settings.load_settings(path)


def test_load_rejects_empty_file(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError):
        settings.load_settings(path)


def test_save_handles_none_values(tmp_path):
    # A None survey value (no preset selected) must serialize cleanly.
    path = tmp_path / "settings.yaml"
    settings.save_settings(
        path, {"survey_url": "", "survey_options": {}, "preset": None}, {}
    )
    state, _ = settings.load_settings(path)
    assert state["preset"] is None
