"""Tests for launch-with-a-file argument picking (no GUI required)."""

import os

from smacc.__main__ import (
    _FFMPEG_QUIET_RULE,
    _quiet_qt_multimedia_logging,
    pick_settings_path,
)


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


# ----- Qt-multimedia logging rule (quiet the FFmpeg startup banner) ----------


def test_quiet_qt_multimedia_sets_rule_when_unset(monkeypatch):
    monkeypatch.delenv("QT_LOGGING_RULES", raising=False)
    _quiet_qt_multimedia_logging()
    assert os.environ["QT_LOGGING_RULES"] == _FFMPEG_QUIET_RULE


def test_quiet_qt_multimedia_appends_to_existing_rules(monkeypatch):
    monkeypatch.setenv("QT_LOGGING_RULES", "qt.qpa.*=true")
    _quiet_qt_multimedia_logging()
    # The developer's existing rule is preserved; ours is appended after it.
    assert os.environ["QT_LOGGING_RULES"] == f"qt.qpa.*=true;{_FFMPEG_QUIET_RULE}"


def test_quiet_qt_multimedia_is_idempotent(monkeypatch):
    monkeypatch.setenv("QT_LOGGING_RULES", _FFMPEG_QUIET_RULE)
    _quiet_qt_multimedia_logging()
    # Already present -> not duplicated.
    assert os.environ["QT_LOGGING_RULES"] == _FFMPEG_QUIET_RULE
