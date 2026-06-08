"""Tests for the per-run session-folder helper (no LSL/GUI needed)."""

from datetime import datetime

from smacc.session import make_session_dir


def test_make_session_dir_uses_timestamp_stem(tmp_path):
    now = datetime(2026, 6, 7, 22, 30, 15)
    session_dir = make_session_dir(tmp_path, now)
    assert session_dir.name == "smacc-20260607-223015"
    assert session_dir.is_dir()
    assert session_dir.parent == tmp_path
    # The log filename keeps the smacc- prefix and .log extension (issue #40).
    log_path = session_dir / f"{session_dir.name}.log"
    assert log_path.name.startswith("smacc-")
    assert log_path.suffix == ".log"


def test_make_session_dir_resolves_same_second_collision(tmp_path):
    now = datetime(2026, 6, 7, 22, 30, 15)
    first = make_session_dir(tmp_path, now)
    second = make_session_dir(tmp_path, now)
    third = make_session_dir(tmp_path, now)
    assert first.name == "smacc-20260607-223015"
    assert second.name == "smacc-20260607-223015-2"
    assert third.name == "smacc-20260607-223015-3"
    assert len({first, second, third}) == 3
