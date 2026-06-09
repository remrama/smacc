"""Tests for settings YAML save/load (no GUI required)."""

import json
from pathlib import Path

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
    "volume_cap": 0.8,
    "devices": {
        "bindings": {
            "bedroom_out": "Speakers (USB Audio), Windows WASAPI",
            "bedroom_mic": "Microphone (USB Audio)",
        },
        "routing": {"cue_out": "bedroom_out", "report_in": "bedroom_mic"},
    },
    "survey_url": "https://example.com/post",
    "survey_options": {
        "Post-dream survey": "https://example.com/post",
        "Pre-sleep questionnaire": "https://example.com/pre",
    },
}

SAMPLE_METADATA = {"subject": "001", "session": "2", "notes": "n", "created": "x"}


def test_save_load_round_trip(tmp_path):
    path = tmp_path / "settings.yaml"
    settings.save_settings(path, SAMPLE_SETTINGS, SAMPLE_METADATA)
    state, metadata = settings.load_settings(path)
    assert state == SAMPLE_SETTINGS
    assert metadata == SAMPLE_METADATA


def test_saved_file_is_tagged_yaml(tmp_path):
    path = tmp_path / "study.smacc"
    settings.save_settings(path, {"cue_attack": 0.2}, {})
    text = path.read_text(encoding="utf-8")
    assert text.splitlines()[0].startswith("#")  # self-identifying header comment
    payload = yaml.safe_load(text)  # comment is ignored, so it still parses
    assert payload["kind"] == settings.KIND
    assert payload["schema_version"] == settings.SCHEMA_VERSION == 4
    assert payload["smacc_version"] == smacc.__version__
    assert payload["settings"] == {"cue_attack": 0.2}


def test_data_directory_of_resolves_relative_absolute_and_default(tmp_path):
    base = tmp_path / "cfg"
    base.mkdir()
    # Relative resolves against the .smacc's folder.
    assert (
        settings.data_directory_of({"data_directory": "data"}, base, tmp_path / "fb")
        == (base / "data").resolve()
    )
    # Absolute is kept as-is.
    elsewhere = tmp_path / "elsewhere"
    assert (
        settings.data_directory_of({"data_directory": str(elsewhere)}, base, tmp_path)
        == elsewhere
    )
    # Missing/blank falls back to the default.
    assert settings.data_directory_of({}, base, tmp_path / "fb") == tmp_path / "fb"


def test_data_directory_relativized_when_beside_file(tmp_path):
    # A data dir under the .smacc's folder is stored relative (so the folder is
    # portable); resolve_paths turns it back into an absolute path on load.
    base = tmp_path / "study"
    (base / "data").mkdir(parents=True)
    portable = settings.relativize_paths({"data_directory": str(base / "data")}, base)
    assert portable["data_directory"] == "data"
    resolved = settings.resolve_paths(portable, base)
    assert Path(resolved["data_directory"]) == (base / "data").resolve()


def test_load_data_directory_reads_file(tmp_path):
    base = tmp_path / "cfg"
    base.mkdir()
    path = base / "peter.smacc"
    settings.save_settings(path, {"data_directory": "data"}, {})
    assert (
        settings.load_data_directory(path, tmp_path / "fb") == (base / "data").resolve()
    )
    # An unreadable/missing file yields the default.
    assert settings.load_data_directory(base / "nope.smacc", tmp_path / "fb") == (
        tmp_path / "fb"
    )


def test_bundled_default_settings_is_valid_and_complete():
    from smacc.paths import BUNDLED_DEFAULT_SETTINGS

    assert BUNDLED_DEFAULT_SETTINGS.is_file()  # shipped example/default
    state, _ = settings.load_settings(BUNDLED_DEFAULT_SETTINGS)
    assert state["data_directory"] == "data"
    assert state["event_codes"]  # carries the default event registry as an example


def test_load_rejects_legacy_state_key(tmp_path):
    # The legacy study.json "state" key fallback was dropped (intended breaking
    # change), so old study.json files no longer load.
    path = tmp_path / "study.json"
    path.write_text(
        json.dumps({"schema_version": 1, "state": {"cue_volume": 0.3}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="settings"):
        settings.load_settings(path)


def test_load_accepts_current_schema(tmp_path):
    path = tmp_path / "study.smacc"
    settings.save_settings(path, {"cue_attack": 1.0}, {})
    state, _ = settings.load_settings(path)
    assert state == {"cue_attack": 1.0}


def test_load_accepts_older_schema_without_event_codes(tmp_path):
    # A pre-v4 study (no event_codes) must still load; the GUI fills the default
    # registry on apply via events.merge_event_codes.
    path = tmp_path / "old.smacc"
    path.write_text(
        yaml.safe_dump(
            {
                "kind": settings.KIND,
                "schema_version": 3,
                "settings": {"cue_attack": 0.5},
            }
        ),
        encoding="utf-8",
    )
    state, _ = settings.load_settings(path)
    assert state == {"cue_attack": 0.5}


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
    path = tmp_path / "study.smacc"
    settings.save_settings(
        path, {"survey_url": "", "survey_options": {}, "preset": None}, {}
    )
    state, _ = settings.load_settings(path)
    assert state["preset"] is None


# ----- relative-path portability --------------------------------------------


def _cue_state(file: str) -> dict:
    return {"cues": [{"name": "c", "file": file, "volume": 0.2, "loop": False}]}


def test_relativize_path_under_base_becomes_relative_posix(tmp_path):
    wav = tmp_path / "sounds" / "cue.wav"
    wav.parent.mkdir()
    wav.write_bytes(b"x")
    state = _cue_state(str(wav))
    out = settings.relativize_paths(state, tmp_path)
    assert out["cues"][0]["file"] == "sounds/cue.wav"  # relative, forward slashes
    assert state["cues"][0]["file"] == str(wav)  # input not mutated (deep copy)


def test_relativize_path_outside_base_stays_absolute(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    wav = other / "cue.wav"
    wav.write_bytes(b"x")
    base = tmp_path / "study"
    base.mkdir()
    out = settings.relativize_paths(_cue_state(str(wav)), base)
    assert Path(out["cues"][0]["file"]).is_absolute()


def test_relativize_and_resolve_round_trip(tmp_path):
    wav = tmp_path / "cue.wav"
    wav.write_bytes(b"x")
    state = {**_cue_state(str(wav)), "noise_file": str(wav)}
    rel = settings.relativize_paths(state, tmp_path)
    resolved = settings.resolve_paths(rel, tmp_path)
    assert Path(resolved["cues"][0]["file"]) == wav.resolve()
    assert Path(resolved["noise_file"]) == wav.resolve()


def test_resolve_keeps_absolute_and_skips_empty(tmp_path):
    wav = tmp_path / "cue.wav"
    state = {**_cue_state(str(wav)), "noise_file": ""}
    out = settings.resolve_paths(state, tmp_path / "elsewhere")
    assert out["cues"][0]["file"] == str(wav)  # absolute unchanged
    assert out["noise_file"] == ""  # empty untouched
