"""Tests for the session-folder helper and emit_event routing (no LSL/GUI needed)."""

import logging
from dataclasses import replace
from datetime import datetime

from smacc import events, triggers
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


# ----- design-mode sessions (study designer) --------------------------------


def test_design_session_creates_no_run_artifacts(tmp_path):
    # Design mode writes nothing — it doesn't even create the data directory.
    sess = SmaccSession(tmp_path / "s", design=True)
    assert sess.design is True
    assert sess.can_record is False
    assert sess.session_dir is None
    assert sess.log_path is None
    assert sess.outlet is None
    assert not (tmp_path / "s").exists()  # no run folder (or data dir) created
    sess.close()  # safe no-op: nothing to release


def test_design_session_emit_event_is_safe_without_outlet(tmp_path):
    sess = SmaccSession(tmp_path / "s", design=True)
    sess.emit_event("REMDetected")  # triggers, but no outlet to push to
    assert sess.outlet is None  # still no outlet; no crash


def test_design_logger_does_not_accumulate_handlers(tmp_path):
    # Each new session clears the shared logger first, so handlers never pile up
    # across the many sessions the launcher can open in one process.
    SmaccSession(tmp_path / "a", design=True)
    SmaccSession(tmp_path / "b", design=True)
    assert len(logging.getLogger("smacc").handlers) == 1


# ----- emit_event routing ---------------------------------------------------


class _FakeOutlet:
    """Stand-in for the LSL outlet that records pushed marker samples + timestamps."""

    def __init__(self):
        self.samples = []
        self.timestamps = []

    def push_sample(self, sample, timestamp=None):
        self.samples.append(sample)
        self.timestamps.append(timestamp)


class _FakeTrigger:
    """Stand-in for a hardware trigger transport that records sent codes.

    ``fail`` makes :meth:`send` raise, to exercise the fail-safe in emit_event.
    """

    def __init__(self, fail=False):
        self.sent = []
        self.closed = False
        self._fail = fail

    def send(self, code):
        if self._fail:
            raise OSError("port gone")
        self.sent.append(code)

    def close(self):
        self.closed = True


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
    sess.recording_start_time = None
    sess.outlet = _FakeOutlet()
    sess.trigger_out = None  # no hardware transport unless a test sets one
    sess.design = False
    sess.trigger_config = triggers.TriggerConfig()
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
    sess.emit_event("REMDetected")  # default lsl=True, ttl=True, preview=True
    assert sess.outlet.samples == [["41"]]
    assert records == [("REM detected - portcode 41", True)]


def test_emit_event_not_routed_still_logs_to_file():
    sess, records = _stub_session()
    sess.events["REMDetected"] = replace(
        sess.events["REMDetected"], lsl=False, ttl=False
    )
    sess.emit_event("REMDetected")
    assert sess.outlet.samples == []  # not sent to the marker stream
    assert records == [("REM detected", True)]  # logged to file, without a portcode


def test_emit_event_lsl_off_skips_the_stream_but_keeps_the_code():
    # A TTL-only event never reaches the LSL outlet, but it is still a routed
    # marker, so its log line keeps the "- portcode N" suffix for the BIDS parser.
    sess, records = _stub_session()
    sess.events["REMDetected"] = replace(sess.events["REMDetected"], lsl=False)
    sess.emit_event("REMDetected")
    assert sess.outlet.samples == []
    assert records == [("REM detected - portcode 41", True)]


def test_emit_event_files_but_hides_from_preview():
    sess, records = _stub_session()
    # TriggerInitialization defaults to unrouted (lsl=False, ttl=False) and
    # preview=False: it's written to the log file but kept out of the live preview.
    sess.emit_event("TriggerInitialization")
    assert sess.outlet.samples == []
    assert records == [("SMACC initialized", False)]


def test_emit_event_detail_suffix():
    sess, records = _stub_session()
    sess.emit_event("CueStarted", detail="Cue 1")
    assert sess.outlet.samples == [["60"]]
    assert sess.outlet.timestamps == [None]  # no offset -> default "now" timestamp
    assert records == [("Cue started: Cue 1 - portcode 60", True)]


def test_emit_event_onset_offset_marks_at_estimated_onset():
    # A stimulus marker with an onset offset (the output buffer latency) is stamped
    # at the estimated onset, and the raw software-trigger instant is kept separately.
    sess, records = _stub_session()
    sess.emit_event("CueStarted", detail="Cue 1", onset_offset=0.02)
    # The LSL marker carries the code with an explicit timestamp (not the "now"
    # sentinel), so it lands at the estimated sound onset.
    assert sess.outlet.samples == [["60"]]
    assert sess.outlet.timestamps[0] is not None
    # The canonical portcode line is still logged verbatim (INFO) — it is what the
    # BIDS parser reads, and it carries the onset timestamp in the log.
    assert ("Cue started: Cue 1 - portcode 60", True) in records
    # The raw trigger instant + the correction ride a separate line, deliberately not
    # a "- portcode N" line, so BIDS counts the event exactly once (at its onset).
    raw_lines = [m for m, _ in records if "software trigger at" in m]
    assert len(raw_lines) == 1
    assert "+20.0 ms" in raw_lines[0]
    assert "portcode 60" not in raw_lines[0]


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


# ----- hardware trigger output (#28) ----------------------------------------


def test_emit_event_sends_code_to_hardware_transport():
    sess, _ = _stub_session()
    sess.trigger_out = _FakeTrigger()
    sess.emit_event("REMDetected")
    assert sess.outlet.samples == [["41"]]  # LSL still fires
    assert sess.trigger_out.sent == [41]  # and the same code goes to hardware


def test_emit_event_not_routed_skips_hardware():
    sess, _ = _stub_session()
    sess.trigger_out = _FakeTrigger()
    sess.events["REMDetected"] = replace(
        sess.events["REMDetected"], lsl=False, ttl=False
    )
    sess.emit_event("REMDetected")
    assert sess.trigger_out.sent == []  # an unrouted event drives neither path


def test_emit_event_routes_each_transport_independently():
    sess, _ = _stub_session()
    sess.trigger_out = _FakeTrigger()
    # LSL-only: the stream fires, the hardware line stays quiet.
    sess.events["REMDetected"] = replace(sess.events["REMDetected"], ttl=False)
    sess.emit_event("REMDetected")
    assert sess.outlet.samples == [["41"]]
    assert sess.trigger_out.sent == []
    # TTL-only: the hardware line fires, the stream stays quiet.
    sess.events["Clapper"] = replace(sess.events["Clapper"], lsl=False)
    sess.emit_event("Clapper")
    assert sess.outlet.samples == [["41"]]  # unchanged
    assert sess.trigger_out.sent == [49]


def test_emit_event_hardware_failure_disables_transport_and_keeps_lsl():
    sess, records = _stub_session()
    sess.trigger_out = _FakeTrigger(fail=True)
    sess.emit_event("REMDetected")
    assert sess.outlet.samples == [["41"]]  # LSL is unaffected by a hardware fault
    assert sess.trigger_out is None  # transport dropped after the failure
    assert any("Hardware trigger failed" in m for m, _ in records)
    # A later event still logs and pushes LSL without raising.
    sess.emit_event("SignalObserved")
    assert sess.outlet.samples == [["41"], ["45"]]


def test_set_trigger_output_disabled_or_design_opens_nothing():
    sess, _ = _stub_session()
    assert sess.set_trigger_output(triggers.TriggerConfig(enabled=False)) is None
    assert sess.trigger_out is None
    sess.design = True
    cfg = triggers.TriggerConfig(enabled=True, port="COM3")
    assert sess.set_trigger_output(cfg) is None  # design mode never opens hardware
    assert sess.trigger_out is None


def test_set_trigger_output_opens_closes_previous_and_logs(monkeypatch):
    sess, records = _stub_session()
    old = _FakeTrigger()
    sess.trigger_out = old
    new = _FakeTrigger()
    monkeypatch.setattr(triggers, "open_trigger", lambda cfg: new)
    cfg = triggers.TriggerConfig(enabled=True, port="COM3")
    assert sess.set_trigger_output(cfg) is None
    assert old.closed is True  # the previous transport is released first
    assert sess.trigger_out is new
    assert any("Hardware trigger ready" in m for m, _ in records)


def test_set_trigger_output_returns_error_message(monkeypatch):
    sess, _ = _stub_session()

    def boom(cfg):
        raise triggers.TriggerError("no such port")

    monkeypatch.setattr(triggers, "open_trigger", boom)
    err = sess.set_trigger_output(triggers.TriggerConfig(enabled=True, port="X"))
    assert err == "no such port"
    assert sess.trigger_out is None


def test_test_trigger_sends_init_code_and_restores(monkeypatch):
    sess, _ = _stub_session()
    opened = []

    def fake_open(cfg):
        out = _FakeTrigger()
        opened.append(out)
        return out

    monkeypatch.setattr(triggers, "open_trigger", fake_open)
    result = sess.test_trigger(triggers.TriggerConfig(enabled=True, port="COM3"))
    assert result is None
    assert opened[0].sent == [100]  # TriggerInitialization's code
    assert opened[0].closed is True
    # trigger_config is disabled (the stub default), so nothing is left open.
    assert sess.trigger_out is None


def test_test_trigger_reports_failure(monkeypatch):
    sess, _ = _stub_session()

    def boom(cfg):
        raise triggers.TriggerError("driver missing")

    monkeypatch.setattr(triggers, "open_trigger", boom)
    assert sess.test_trigger(triggers.TriggerConfig(enabled=True)) == "driver missing"


# ----- recording-start reference clock (#60) --------------------------------


def test_elapsed_since_recording_is_none_until_marked():
    sess, _ = _stub_session()
    assert sess.elapsed_since_recording() is None


def test_mark_recording_start_stamps_clock_and_emits_marker():
    sess, records = _stub_session()
    sess.mark_recording_start()
    assert sess.recording_start_time is not None
    # Once marked, the elapsed time is a (non-negative) duration, not None.
    assert sess.elapsed_since_recording() is not None
    # The marker routes through emit_event: triggered with code 51 and logged.
    assert sess.outlet.samples == [["51"]]
    assert records == [("Start recording - portcode 51", True)]


# ----- log levels: preview-noise demotion (DEBUG vs INFO) --------------------


def _level_capturing_session():
    """A bare session whose logger records ``(levelno, message)`` per line.

    Only the logging helpers are exercised, so the rest of the session can stay
    unconfigured aside from the interaction gate (set per-test).
    """
    sess = SmaccSession.__new__(SmaccSession)
    logger = logging.getLogger("smacc-test-levels")
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    records: list[tuple[int, str]] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append((record.levelno, record.getMessage()))

    logger.addHandler(_Capture())
    sess.logger = logger
    return sess, records


def test_log_debug_msg_logs_at_debug_level():
    sess, records = _level_capturing_session()
    sess.log_debug_msg("quiet line")
    assert records == [(logging.DEBUG, "quiet line")]


def test_log_interaction_defaults_to_info():
    sess, records = _level_capturing_session()
    sess.log_interactions = True
    sess.log_interaction("an interaction")
    assert records == [(logging.INFO, "an interaction")]


def test_log_interaction_debug_demotes_to_debug():
    sess, records = _level_capturing_session()
    sess.log_interactions = True
    sess.log_interaction("a noisy interaction", debug=True)
    # Demoted lines still get logged (and so reach the file), just at DEBUG, so
    # the INFO-gated live preview leaves them out.
    assert records == [(logging.DEBUG, "a noisy interaction")]


def test_log_interaction_debug_still_respects_the_gate():
    sess, records = _level_capturing_session()
    sess.log_interactions = False  # programmatic setup / study load
    sess.log_interaction("a noisy interaction", debug=True)
    assert records == []  # gated off entirely, regardless of level
