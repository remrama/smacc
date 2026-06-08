"""Tests for operator/machine preferences load/save (no GUI required)."""

import logging

import yaml

from smacc import preferences


def test_missing_file_returns_defaults(tmp_path):
    prefs = preferences.load_preferences(tmp_path / "nope.yaml")
    assert prefs == preferences.DEFAULTS
    # A copy, not the singleton — mutating the result must not affect DEFAULTS.
    prefs["always_on_top"] = True
    assert preferences.DEFAULTS["always_on_top"] is False


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
    preferences.save_preferences(path, {"always_on_top": True})
    prefs = preferences.load_preferences(path)
    assert prefs["always_on_top"] is True  # from file
    assert prefs["lights_on"] is True  # default still present
    assert "association_prompted" in prefs  # every default key present


def test_round_trip(tmp_path):
    path = tmp_path / "preferences.yaml"
    custom = preferences.default_preferences()
    custom["always_on_top"] = True
    custom["preview_levels"] = ["DEBUG", "INFO"]
    custom["window"] = {"x": 10, "y": 20, "w": 800, "h": 600}
    preferences.save_preferences(path, custom)
    assert preferences.load_preferences(path) == custom


def test_save_to_unwritable_path_does_not_raise(tmp_path):
    # A directory can't be written as a file; save must swallow the error.
    preferences.save_preferences(tmp_path, {"always_on_top": True})  # no exception


def test_level_name_int_round_trip():
    levels = {logging.INFO, logging.ERROR}
    names = preferences.levels_to_names(levels)
    assert names == ["INFO", "ERROR"]  # sorted by severity (20 < 40)
    assert preferences.names_to_levels(names) == levels


def test_names_to_levels_drops_unknown():
    assert preferences.names_to_levels(["INFO", "BOGUS"]) == {logging.INFO}
