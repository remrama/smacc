"""Tests for study.json save/load (no GUI required)."""

import json

import pytest

from smacc import study


def test_save_load_round_trip(tmp_path):
    state = {
        "cue_file": "cue.wav",
        "cue_volume": 0.4,
        "cue_loop": True,
        "noise_volume": 0.1,
        "noise_color": "pink",
        "blink_color": "#ff8800",
        "blink_length": 2.5,
        "survey_url": "https://example.com/survey",
        "survey_options": {"Morning": "https://example.com/survey"},
    }
    path = tmp_path / "study.json"
    study.save_study(path, state)
    assert study.load_study(path) == state


def test_saved_file_records_schema_version(tmp_path):
    path = tmp_path / "study.json"
    study.save_study(path, {"cue_volume": 0.2})
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == study.SCHEMA_VERSION
    assert payload["state"] == {"cue_volume": 0.2}


def test_load_rejects_unsupported_schema(tmp_path):
    path = tmp_path / "study.json"
    path.write_text(json.dumps({"schema_version": 999, "state": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="schema version"):
        study.load_study(path)


def test_load_rejects_missing_state(tmp_path):
    path = tmp_path / "study.json"
    path.write_text(
        json.dumps({"schema_version": study.SCHEMA_VERSION}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="state"):
        study.load_study(path)
