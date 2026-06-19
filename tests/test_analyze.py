"""Tests for the analyze window — its pure helpers and the annotator handoff."""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import pytest

from smacc import analyze, eeg


def test_format_duration_drops_leading_zero_units():
    assert analyze.format_duration(0) == "0s"
    assert analyze.format_duration(45) == "45s"
    assert analyze.format_duration(125) == "2m 5s"
    assert analyze.format_duration(3661) == "1h 1m 1s"


def test_find_log_in_dir_prefers_session_log(tmp_path):
    folder = tmp_path / "smacc-20260101-000000"
    folder.mkdir()
    (folder / "other.log").write_text("x", encoding="utf-8")
    named = folder / "session.log"
    named.write_text("x", encoding="utf-8")
    assert analyze.find_log_in_dir(folder) == named


def test_find_log_in_dir_returns_none_when_absent(tmp_path):
    assert analyze.find_log_in_dir(tmp_path) is None


def test_find_log_in_dir_recursive_finds_nested_log(tmp_path):
    nested = tmp_path / "sessions" / "smacc-x"
    nested.mkdir(parents=True)
    log = nested / "session.log"
    log.write_text("x", encoding="utf-8")
    assert analyze.find_log_in_dir(tmp_path, recursive=True) == log
    assert analyze.find_log_in_dir(tmp_path) is None  # not at the top level


def test_extract_zip_round_trips(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.log").write_text("hello", encoding="utf-8")
    zip_path = tmp_path / "bundle.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(src / "a.log", "a.log")
    dest = tmp_path / "out"
    dest.mkdir()
    analyze.extract_zip(zip_path, dest)
    assert (dest / "a.log").read_text(encoding="utf-8") == "hello"


def test_extract_zip_rejects_path_traversal(tmp_path):
    zip_path = tmp_path / "evil.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("../escape.txt", "nope")  # would escape dest
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(ValueError):
        analyze.extract_zip(zip_path, dest)
    assert not (tmp_path / "escape.txt").exists()


# ----- the EEG Annotator handoff (#125d) ------------------------------------

A_LOG = (
    "2026-06-05 22:00:00.000-0500, INFO, Opened SMACC v0.0.7\n"
    "2026-06-05 22:00:05.000-0500, INFO, Lights off - portcode 47\n"
)


@pytest.fixture
def analyze_window(qtbot, tmp_path, monkeypatch):
    """An AnalyzeWindow with isolated prefs."""
    monkeypatch.setattr(analyze, "preferences_path", tmp_path / "prefs.yaml")
    win = analyze.AnalyzeWindow()
    qtbot.addWidget(win)
    return win


def test_window_shows_itself_on_construction(analyze_window):
    # The launcher hides itself in _open_tool and relies on the tool showing
    # itself (#249); a window that builds but never shows reads to a user as
    # "the Analyzer crashed on opening."
    assert analyze_window.isVisible()


def test_open_in_annotator_launches_with_the_log(analyze_window, tmp_path, monkeypatch):
    calls: list[list[str] | None] = []
    monkeypatch.setattr(eeg, "launch", lambda args=None: calls.append(args) or True)
    log = tmp_path / "session.log"
    log.write_text(A_LOG, encoding="utf-8")
    analyze_window._load_log(log, log.parent)
    assert analyze_window.annotateButton.isEnabled()
    analyze_window.open_in_annotator()
    assert calls == [["--log", str(log)]]


def test_annotate_button_disabled_until_a_session_loads(analyze_window, tmp_path):
    # The handoff has nothing to hand off until a session is loaded; the EEG
    # Annotator itself is always present (it ships inside the one SMACC binary).
    assert not analyze_window.annotateButton.isEnabled()
    log = tmp_path / "session.log"
    log.write_text(A_LOG, encoding="utf-8")
    analyze_window._load_log(log, log.parent)
    assert analyze_window.annotateButton.isEnabled()


def test_handoff_copies_a_zip_extracted_log_out_of_temp(
    analyze_window, tmp_path, monkeypatch
):
    # A zip-extracted log lives under a temp dir Analyze deletes on close; the
    # detached annotator reads it later, so the handoff must pass a copy that
    # survives that cleanup, not the temp path.
    launched: list[list[str] | None] = []
    monkeypatch.setattr(eeg, "launch", lambda args=None: launched.append(args) or True)
    temp = tmp_path / "smacc-analyze-xyz"
    temp.mkdir()
    log = temp / "session.log"
    log.write_text(A_LOG, encoding="utf-8")
    analyze_window._load_log(log, temp)
    analyze_window._temp_dirs.append(temp)  # as _load_zip records it
    analyze_window.open_in_annotator()
    passed = Path(launched[0][1])  # the --log value
    assert passed != log  # a copy, not the temp path
    assert passed.read_text(encoding="utf-8") == A_LOG
    shutil.rmtree(temp, ignore_errors=True)  # Analyze's cleanup
    assert passed.is_file()  # the handed-off copy survives it
    shutil.rmtree(passed.parent, ignore_errors=True)


def test_handoff_passes_a_real_log_path_through_unchanged(
    analyze_window, tmp_path, monkeypatch
):
    launched: list[list[str] | None] = []
    monkeypatch.setattr(eeg, "launch", lambda args=None: launched.append(args) or True)
    log = tmp_path / "session.log"
    log.write_text(A_LOG, encoding="utf-8")
    analyze_window._load_log(log, log.parent)  # not under a temp dir
    analyze_window.open_in_annotator()
    assert launched[0] == ["--log", str(log)]  # passed through, no copy
