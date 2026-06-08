"""Tests for the session-folder helper and emit_event routing (no LSL/GUI needed)."""

import logging
from dataclasses import replace
from datetime import datetime

from smacc import events
from smacc.session import SmaccSession, make_session_dir
from smacc.study import Study


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


# ----- design-mode sessions (study designer) --------------------------------


def test_design_session_creates_no_run_artifacts(tmp_path):
    # Design mode doesn't touch sessions/, so a bare Study (no dirs) is enough.
    sess = SmaccSession(Study(tmp_path / "s"), design=True)
    assert sess.design is True
    assert sess.can_record is False
    assert sess.session_dir is None
    assert sess.log_path is None
    assert sess.outlet is None
    assert not (tmp_path / "s" / "sessions").exists()  # no run folder created
    sess.close()  # safe no-op: nothing to release


def test_design_session_emit_event_is_safe_without_outlet(tmp_path):
    sess = SmaccSession(Study(tmp_path / "s"), design=True)
    sess.emit_event("REMDetected")  # triggers, but no outlet to push to
    assert sess.outlet is None  # still no outlet; no crash


def test_design_logger_does_not_accumulate_handlers(tmp_path):
    # Each new session clears the shared logger first, so handlers never pile up
    # across the many sessions the launcher can open in one process.
    SmaccSession(Study(tmp_path / "a"), design=True)
    SmaccSession(Study(tmp_path / "b"), design=True)
    assert len(logging.getLogger("smacc").handlers) == 1


# ----- emit_event routing ---------------------------------------------------


class _FakeOutlet:
    """Stand-in for the LSL outlet that records pushed marker samples."""

    def __init__(self):
        self.samples = []

    def push_sample(self, sample):
        self.samples.append(sample)


def _stub_session():
    """A SmaccSession wired to fakes so emit_event runs without LSL/file/GUI.

    Returns ``(session, records)`` where ``records`` collects ``(message,
    preview)`` for each logged line (preview = the smacc_preview attribute).
    """
    sess = SmaccSession.__new__(SmaccSession)
    sess.events = {e.key: e for e in events.default_events()}
    sess.event_code_safe_max = events.DEFAULT_SAFE_MAX
    sess.log_interactions = True
    sess._event_counts = {}
    sess.outlet = _FakeOutlet()
    logger = logging.getLogger("smacc-test-emit")
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    records: list[tuple[str, bool]] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(
                (record.getMessage(), getattr(record, "smacc_preview", True))
            )

    logger.addHandler(_Capture())
    sess.logger = logger
    return sess, records


def test_emit_event_triggers_and_logs_with_code():
    sess, records = _stub_session()
    sess.emit_event("REMDetected")  # default trigger=True, preview=True
    assert sess.outlet.samples == [["41"]]
    assert records == [("REM detected - portcode 41", True)]


def test_emit_event_not_triggered_still_logs_to_file():
    sess, records = _stub_session()
    sess.events["REMDetected"] = replace(sess.events["REMDetected"], trigger=False)
    sess.emit_event("REMDetected")
    assert sess.outlet.samples == []  # not sent to the marker stream
    assert records == [("REM detected", True)]  # logged to file, without a portcode


def test_emit_event_files_but_hides_from_preview():
    sess, records = _stub_session()
    # TriggerInitialization defaults to trigger=False, preview=False: it's written
    # to the log file but kept out of the live preview.
    sess.emit_event("TriggerInitialization")
    assert sess.outlet.samples == []
    assert records == [("SMACC initialized", False)]


def test_emit_event_detail_suffix():
    sess, records = _stub_session()
    sess.emit_event("CueStarted", detail="Cue 1")
    assert sess.outlet.samples == [["60"]]
    assert records == [("Cue started: Cue 1 - portcode 60", True)]


def test_emit_event_dream_increment_auto_counts():
    sess, _ = _stub_session()
    for _ in range(3):
        sess.emit_event("DreamReportStarted")  # no manual ordinal needed
    assert sess.outlet.samples == [["201"], ["202"], ["203"]]


def test_emit_event_increment_works_for_any_event():
    sess, _ = _stub_session()
    sess.events["SurveyOpened"] = replace(sess.events["SurveyOpened"], increment=True)
    sess.emit_event("SurveyOpened")
    sess.emit_event("SurveyOpened")
    assert sess.outlet.samples == [["67"], ["68"]]  # base 67 advances per firing


def test_emit_event_unknown_key_warns_without_crashing():
    sess, records = _stub_session()
    sess.emit_event("Nonexistent")  # should warn, not raise
    assert sess.outlet.samples == []
    assert any("Unknown event" in m for m, _ in records)
