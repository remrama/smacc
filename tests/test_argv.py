"""Tests for launch-with-a-file argument picking (no GUI required)."""

import os
import sys

from smacc.__main__ import (
    _FFMPEG_QUIET_RULE,
    _quiet_qt_multimedia_logging,
    main,
    pick_settings_path,
)
from smacc.config import VERSION


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


def test_version_flag_exits_before_any_window(monkeypatch, capsys):
    # The release workflow's smoke test: --version must return (exit code 0)
    # without constructing a QApplication or touching the SMACC directory.
    monkeypatch.setattr(sys, "argv", ["SMACC.exe", "--version"])
    main()  # returns instead of entering the Qt event loop
    assert f"SMACC {VERSION}" in capsys.readouterr().out


def test_eeg_flag_routes_to_the_annotator(monkeypatch):
    # `SMACC --eeg …` is the single binary run in Annotator mode: main() hands
    # off to the EEG entry point with the routing flag stripped, so the
    # Annotator sees only its own arguments.
    import smacc.eeg.__main__ as eeg_main_mod

    seen: dict[str, list[str]] = {}
    monkeypatch.setattr(eeg_main_mod, "main", lambda: seen.update(argv=list(sys.argv)))
    monkeypatch.setattr(sys, "argv", ["SMACC.exe", "--eeg", "--log", "night1.log"])
    main()
    assert seen["argv"] == ["SMACC.exe", "--log", "night1.log"]


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
