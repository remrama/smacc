"""Tests for the session-folder helper and emit_event routing (no LSL/GUI needed)."""

import logging
from dataclasses import replace
from datetime import datetime

from smacc import events
from smacc.session import SmaccSession, make_session_dir


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


# ----- emit_event routing ---------------------------------------------------


class _FakeOutlet:
    """Stand-in for the LSL outlet that records pushed marker samples."""

    def __init__(self):
        self.samples = []

    def push_sample(self, sample):
        self.samples.append(sample)


def _stub_session():
    """A SmaccSession wired to fakes so emit_event runs without LSL/file/GUI."""
    sess = SmaccSession.__new__(SmaccSession)
    sess.events = {e.key: e for e in events.default_events()}
    sess.event_code_safe_max = events.DEFAULT_SAFE_MAX
    sess.log_interactions = True
    sess.outlet = _FakeOutlet()
    logger = logging.getLogger("smacc-test-emit")
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    messages: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            messages.append(record.getMessage())

    logger.addHandler(_Capture())
    sess.logger = logger
    return sess, messages


def test_emit_event_triggers_and_logs_with_code():
    sess, messages = _stub_session()
    sess.emit_event("REMDetected")  # default trigger=True
    assert sess.outlet.samples == [["41"]]
    assert messages == ["REM detected - portcode 41"]


def test_emit_event_log_only_when_not_triggered():
    sess, messages = _stub_session()
    sess.events["REMDetected"] = replace(
        sess.events["REMDetected"], trigger=False, log=True
    )
    sess.emit_event("REMDetected")
    assert sess.outlet.samples == []  # not sent to the marker stream
    assert messages == ["REM detected"]  # logged, but without a portcode


def test_emit_event_silent_when_neither_trigger_nor_log():
    sess, messages = _stub_session()
    # TriggerInitialization defaults to trigger=False, log=False -> a no-op.
    sess.emit_event("TriggerInitialization")
    assert sess.outlet.samples == []
    assert messages == []


def test_emit_event_detail_suffix():
    sess, messages = _stub_session()
    sess.emit_event("CueStarted", detail="Cue 1")
    assert sess.outlet.samples == [["60"]]
    assert messages == ["Cue started: Cue 1 - portcode 60"]


def test_emit_event_dream_increment():
    sess, _ = _stub_session()
    for ordinal in (1, 2, 3):
        sess.emit_event("DreamReportStarted", ordinal=ordinal)
    assert sess.outlet.samples == [["201"], ["202"], ["203"]]


def test_emit_event_unknown_key_warns_without_crashing():
    sess, messages = _stub_session()
    sess.emit_event("Nonexistent")  # should warn, not raise
    assert sess.outlet.samples == []
    assert any("Unknown event" in m for m in messages)
