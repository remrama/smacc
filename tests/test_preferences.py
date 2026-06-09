"""Tests for operator/machine preferences load/save (no GUI required)."""

import logging

import yaml

from smacc import preferences


def test_missing_file_returns_defaults(tmp_path):
    prefs = preferences.load_preferences(tmp_path / "nope.yaml")
    assert prefs == preferences.DEFAULTS
    # A copy, not the singleton — mutating the result must not affect DEFAULTS.
    prefs["windows"]["main"] = {"x": 1}
    assert preferences.DEFAULTS["windows"] == {}


def test_corrupt_file_returns_defaults(tmp_path):
    path = tmp_path / "preferences.yaml"
    path.write_text("{ not valid: yaml ::::", encoding="utf-8")
    assert preferences.load_preferences(path) == preferences.DEFAULTS


def test_wrong_kind_returns_defaults(tmp_path):
    path = tmp_path / "preferences.yaml"
    path.write_text(
        yaml.safe_dump({"kind": "smacc/settings", "preferences": {"lights_on": False}}),
        encoding="utf-8",
    )
    assert preferences.load_preferences(path) == preferences.DEFAULTS


def test_partial_file_merges_over_defaults(tmp_path):
    path = tmp_path / "preferences.yaml"
    preferences.save_preferences(path, {"last_settings": "/x"})
    prefs = preferences.load_preferences(path)
    assert prefs["last_settings"] == "/x"  # from file
    assert prefs["windows"] == {}  # default
    assert "association_prompted" in prefs  # every default key present


def test_round_trip(tmp_path):
    path = tmp_path / "preferences.yaml"
    custom = preferences.default_preferences()
    custom["windows"] = {
        "main": {"x": 10, "y": 20, "w": 800, "h": 600},
        "launcher": {"x": 0, "y": 0, "w": 340, "h": 360},
    }
    custom["recent_settings"] = ["/a", "/b"]
    preferences.save_preferences(path, custom)
    assert preferences.load_preferences(path) == custom


def test_legacy_window_migrates_into_main_entry(tmp_path):
    # A pre-per-window-map file stored only the session window under a flat ``window``.
    path = tmp_path / "preferences.yaml"
    preferences.save_preferences(path, {"window": {"x": 5, "y": 6, "w": 700, "h": 500}})
    prefs = preferences.load_preferences(path)
    assert prefs["windows"][preferences.MAIN_WINDOW_ID] == {
        "x": 5,
        "y": 6,
        "w": 700,
        "h": 500,
    }


def test_explicit_windows_entry_wins_over_legacy_window(tmp_path):
    # If both the new map and the legacy key are present, the newer map is kept.
    path = tmp_path / "preferences.yaml"
    preferences.save_preferences(
        path,
        {
            "window": {"x": 5, "y": 6, "w": 700, "h": 500},
            "windows": {"main": {"x": 1, "y": 2, "w": 100, "h": 200}},
        },
    )
    prefs = preferences.load_preferences(path)
    assert prefs["windows"]["main"] == {"x": 1, "y": 2, "w": 100, "h": 200}


def test_save_to_unwritable_path_does_not_raise(tmp_path):
    # A directory can't be written as a file; save must swallow the error.
    preferences.save_preferences(tmp_path, {"last_settings": "/x"})  # no exception


def test_update_preferences_merges_without_clobbering(tmp_path):
    path = tmp_path / "preferences.yaml"
    preferences.update_preferences(path, {"last_settings": "/x"})
    preferences.update_preferences(path, {"recent_settings": ["/a", "/b"]})
    prefs = preferences.load_preferences(path)
    assert prefs["last_settings"] == "/x"  # first writer's key preserved
    assert prefs["recent_settings"] == ["/a", "/b"]  # second writer's key applied


def test_window_geometry_accessor(tmp_path):
    path = tmp_path / "preferences.yaml"
    preferences.update_window_geometry(path, "main", {"x": 1, "y": 2, "w": 3, "h": 4})
    prefs = preferences.load_preferences(path)
    assert preferences.window_geometry(prefs, "main") == {
        "x": 1,
        "y": 2,
        "w": 3,
        "h": 4,
    }
    assert preferences.window_geometry(prefs, "absent") == {}  # unknown id reads empty


def test_update_window_geometry_is_per_window_and_non_clobbering(tmp_path):
    path = tmp_path / "preferences.yaml"
    preferences.update_preferences(path, {"recent_settings": ["/a"]})
    preferences.update_window_geometry(path, "main", {"x": 1, "y": 1, "w": 5, "h": 5})
    preferences.update_window_geometry(path, "events", {"x": 9, "y": 9, "w": 6, "h": 6})
    prefs = preferences.load_preferences(path)
    # Each window keeps its own entry; the unrelated recents list is untouched.
    assert preferences.window_geometry(prefs, "main")["x"] == 1
    assert preferences.window_geometry(prefs, "events")["x"] == 9
    assert prefs["recent_settings"] == ["/a"]


def test_recent_settings_keys_round_trip(tmp_path):
    path = tmp_path / "preferences.yaml"
    preferences.update_preferences(
        path, {"last_settings": "/x", "recent_settings": ["/x"]}
    )
    prefs = preferences.load_preferences(path)
    assert prefs["last_settings"] == "/x"
    assert prefs["recent_settings"] == ["/x"]


def test_push_recent_moves_to_front_and_dedupes():
    assert preferences.push_recent(["/a", "/b"], "/b") == ["/b", "/a"]
    assert preferences.push_recent([], "/a") == ["/a"]
    assert preferences.push_recent(["/a"], "/a") == ["/a"]  # no duplicate


def test_push_recent_caps_length():
    recents = [f"/{i}" for i in range(8)]
    out = preferences.push_recent(recents, "/new", limit=8)
    assert out[0] == "/new"
    assert len(out) == 8
    assert "/7" not in out  # oldest dropped to make room


def test_level_name_int_round_trip():
    levels = {logging.INFO, logging.ERROR}
    names = preferences.levels_to_names(levels)
    assert names == ["INFO", "ERROR"]  # sorted by severity (20 < 40)
    assert preferences.names_to_levels(names) == levels


def test_names_to_levels_drops_unknown():
    assert preferences.names_to_levels(["INFO", "BOGUS"]) == {logging.INFO}
