"""Tests for launch-with-a-file argument picking (no GUI required)."""

from smacc.__main__ import pick_settings_path


def test_no_positional_returns_none():
    assert pick_settings_path(["SMACC.exe"]) is None


def test_picks_smacc_file():
    assert pick_settings_path(["SMACC.exe", "study.smacc"]) == "study.smacc"


def test_rejects_yaml_and_yml():
    # Only .smacc is a study file now; .yaml/.yml are not opened on launch.
    assert pick_settings_path(["SMACC.exe", "a.yaml"]) is None
    assert pick_settings_path(["SMACC.exe", "a.yml"]) is None


def test_ignores_flags_and_other_files():
    args = ["SMACC.exe", "--debug", "notes.txt", "study.smacc"]
    assert pick_settings_path(args) == "study.smacc"


def test_last_study_file_wins():
    assert pick_settings_path(["SMACC.exe", "a.smacc", "b.smacc"]) == "b.smacc"
