"""Tests for the analyze-window pure helpers (no GUI required)."""

from __future__ import annotations

import zipfile

import pytest

from smacc import analyze


def test_format_duration_drops_leading_zero_units():
    assert analyze.format_duration(0) == "0s"
    assert analyze.format_duration(45) == "45s"
    assert analyze.format_duration(125) == "2m 5s"
    assert analyze.format_duration(3661) == "1h 1m 1s"


def test_find_log_in_dir_prefers_the_log_named_like_the_folder(tmp_path):
    folder = tmp_path / "smacc-20260101-000000"
    folder.mkdir()
    (folder / "other.log").write_text("x", encoding="utf-8")
    named = folder / "smacc-20260101-000000.log"
    named.write_text("x", encoding="utf-8")
    assert analyze.find_log_in_dir(folder) == named


def test_find_log_in_dir_returns_none_when_absent(tmp_path):
    assert analyze.find_log_in_dir(tmp_path) is None


def test_find_log_in_dir_recursive_finds_nested_log(tmp_path):
    nested = tmp_path / "sessions" / "smacc-x"
    nested.mkdir(parents=True)
    log = nested / "smacc-x.log"
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
