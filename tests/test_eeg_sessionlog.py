"""Tests for the session-log overlay model (#125, no GUI, no MNE)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from smacc.eeg import sessionlog as sl

# A small but representative night: an open line, a marker, two dream reports
# (the second's recording-start untimed-style line), a survey, and a soft DEBUG
# line — covering every entry kind the overlay distinguishes.
SAMPLE_LOG = """2026-06-05 22:00:00.000-0500, INFO, Opened SMACC v0.0.7
2026-06-05 22:05:00.000-0500, INFO, Lights off - portcode 47
2026-06-05 22:30:00.000-0500, DEBUG, Cue volume set to 0.40
2026-06-05 22:31:00.000-0500, INFO, Dream report started: report-01, t+00:26:00 - portcode 201
2026-06-05 22:32:00.000-0500, INFO, Survey opened: DLQ - portcode 67
2026-06-05 23:10:00.000-0500, INFO, Dream report started: report-02, t+01:05:00 - portcode 202
"""


def _entry(entries, code):
    return next(e for e in entries if e.code == code)


# ----- parsing & classification ---------------------------------------------


def test_parse_session_log_returns_every_parseable_line():
    entries = sl.parse_session_log(SAMPLE_LOG)
    assert len(entries) == 6  # incl. the open line and the DEBUG soft line
    assert [e.level for e in entries].count("DEBUG") == 1


def test_non_marker_lines_are_other_with_no_code():
    entries = sl.parse_session_log(SAMPLE_LOG)
    opened = entries[0]
    assert opened.kind == sl.OTHER
    assert opened.code is None and opened.label is None and opened.report_number is None


def test_marker_line_carries_label_and_code():
    lights = _entry(sl.parse_session_log(SAMPLE_LOG), 47)
    assert lights.kind == sl.MARKER
    assert lights.label == "Lights off"
    assert lights.code == 47


def test_dream_reports_classified_and_numbered_from_the_line():
    entries = sl.parse_session_log(SAMPLE_LOG)
    reports = [e for e in entries if e.kind == sl.REPORT]
    assert [e.report_number for e in reports] == [1, 2]
    assert [e.code for e in reports] == [201, 202]


def test_survey_line_classified():
    survey = _entry(sl.parse_session_log(SAMPLE_LOG), 67)
    assert survey.kind == sl.SURVEY


def test_report_number_falls_back_to_order_for_old_logs():
    # An older log whose dream-report lines carry no "report-NN" token still
    # numbers the reports by their order, matching report-01.wav / report-02.wav.
    old = (
        "2026-06-05 22:00:00.000, INFO, Opened SMACC\n"
        "2026-06-05 22:31:00.000, INFO, Dream report started: t+00:31:00 - portcode 201\n"
        "2026-06-05 23:10:00.000, INFO, Dream report started: t+01:10:00 - portcode 202\n"
    )
    reports = [e for e in sl.parse_session_log(old) if e.kind == sl.REPORT]
    assert [e.report_number for e in reports] == [1, 2]


# ----- placement math -------------------------------------------------------


def test_seconds_at_places_relative_to_origin():
    entries = sl.parse_session_log(SAMPLE_LOG)
    origin = entries[0].timestamp  # the open line, 22:00:00
    lights = _entry(entries, 47)  # 22:05:00, five minutes later
    assert sl.seconds_at(lights, origin) == 300.0


def test_seconds_at_applies_the_offset():
    entries = sl.parse_session_log(SAMPLE_LOG)
    origin = entries[0].timestamp
    lights = _entry(entries, 47)
    assert sl.seconds_at(lights, origin, offset=12.5) == 312.5


def test_seconds_at_compares_wall_clock_readings_across_awareness():
    # A naive origin (an EDF wall-clock meas_date) vs an offset-aware log entry:
    # both are read as their wall-clock face value, so placement matches the
    # naive case and the subtraction never raises on mixed awareness.
    entries = sl.parse_session_log(SAMPLE_LOG)
    aware_lights = _entry(entries, 47)  # 22:05:00-0500
    naive_origin = datetime(2026, 6, 5, 22, 0, 0)  # 22:00, no tzinfo
    assert sl.seconds_at(aware_lights, naive_origin) == 300.0


def test_wall_clock_naive_strips_without_converting_zones():
    aware = datetime(2026, 6, 5, 22, 0, 0, tzinfo=timezone(timedelta(hours=-5)))
    stripped = sl.wall_clock_naive(aware)
    assert stripped == datetime(2026, 6, 5, 22, 0, 0)  # 22:00 as written, not 03:00Z
    assert stripped.tzinfo is None


# ----- span / artifacts / standalone provider -------------------------------


def test_log_span_returns_first_and_last_timestamps():
    entries = sl.parse_session_log(SAMPLE_LOG)
    span = sl.log_span(entries)
    assert span == (entries[0].timestamp, entries[-1].timestamp)
    assert sl.log_span([]) is None


def test_report_wav_resolves_existing_file(tmp_path):
    (tmp_path / "report-02.wav").write_bytes(b"RIFF")
    entries = sl.parse_session_log(SAMPLE_LOG)
    report2 = _entry(entries, 202)
    assert sl.report_wav(report2, tmp_path) == tmp_path / "report-02.wav"
    # report-01.wav was not written, so it resolves to None (missing file).
    report1 = _entry(entries, 201)
    assert sl.report_wav(report1, tmp_path) is None


def test_report_wav_none_for_non_report_entry(tmp_path):
    (tmp_path / "report-01.wav").write_bytes(b"RIFF")
    lights = _entry(sl.parse_session_log(SAMPLE_LOG), 47)
    assert sl.report_wav(lights, tmp_path) is None


def test_log_timeline_is_a_zero_channel_provider():
    entries = sl.parse_session_log(SAMPLE_LOG)
    timeline = sl.LogTimeline(entries)
    assert timeline.ch_names == []
    assert timeline.ch_types == []
    # 22:00:00 -> 23:10:00 is 70 minutes of span.
    assert timeline.duration == 70 * 60
    assert timeline.meas_date == entries[0].timestamp
    times, data = timeline.get_slice(0.0, 30.0)
    assert times.size == 0
    assert data.shape == (0, 0)


def test_log_timeline_empty_log():
    timeline = sl.LogTimeline([])
    assert timeline.duration == 0.0
    assert timeline.meas_date is None
