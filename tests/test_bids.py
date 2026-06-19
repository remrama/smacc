"""Tests for the BIDS events exporter (no GUI required)."""

import csv
from datetime import datetime, timedelta, timezone

from smacc import bids, settings

SAMPLE_LOG = """2026-06-05 22:00:00.000, INFO, Opened SMACC v0.0.7
2026-06-05 22:00:05.500, INFO, Lights off - portcode 47
2026-06-05 22:30:10.250, INFO, Note [saw a light] - portcode 201
2026-06-05 22:45:00.000, INFO, Program closed
"""

# The same session as SAMPLE_LOG, written by a newer SMACC that stamps each
# line with the machine's UTC offset (#215).
AWARE_LOG = """2026-06-05 22:00:00.000-0500, INFO, Opened SMACC v0.0.7
2026-06-05 22:00:05.500-0500, INFO, Lights off - portcode 47
2026-06-05 22:30:10.250-0500, INFO, Note [saw a light] - portcode 201
2026-06-05 22:45:00.000-0500, INFO, Program closed
"""


def test_parse_timestamp_reads_naive_and_offset_aware():
    naive = bids.parse_timestamp("2026-06-05 22:00:00.000")
    assert naive == datetime(2026, 6, 5, 22, 0, 0)
    assert naive.tzinfo is None
    aware = bids.parse_timestamp("2026-06-05 22:00:00.000-0500")
    assert aware.tzinfo is not None
    assert aware.utcoffset() == timedelta(hours=-5)
    assert aware == datetime(2026, 6, 5, 22, 0, 0, tzinfo=timezone(timedelta(hours=-5)))


def test_parse_timestamp_rejects_non_timestamps():
    assert bids.parse_timestamp("Program closed") is None
    assert bids.parse_timestamp("") is None


def test_parse_marker_splits_label_and_code():
    assert bids.parse_marker("Lights off - portcode 47") == ("Lights off", 47)
    assert bids.parse_marker("Cue started: Piano - portcode 60") == (
        "Cue started: Piano",
        60,
    )


def test_parse_marker_rejects_non_marker_lines():
    assert bids.parse_marker("Opened SMACC v0.0.7") is None
    assert bids.parse_marker("Cue volume set to 0.40") is None


def test_log_to_events_handles_offset_aware_timestamps():
    # A new offset-aware log yields the same data-relative onsets as the old
    # naive one: onsets are deltas within one log, so the offset cancels out.
    assert bids.log_to_events(AWARE_LOG) == bids.log_to_events(SAMPLE_LOG)


def test_log_to_events_extracts_only_portcode_lines():
    events = bids.log_to_events(SAMPLE_LOG)
    assert len(events) == 2  # the two "- portcode N" lines, not open/close
    assert [e["value"] for e in events] == [47, 201]
    assert [e["trial_type"] for e in events] == ["Lights off", "Note [saw a light]"]


def test_onset_corrected_cue_counts_once_at_the_info_line():
    # A cue/noise marker is logged twice: a DEBUG line keeping the raw software-trigger
    # instant, and the canonical INFO "- portcode N" line stamped at the estimated
    # onset. Only the INFO line is a portcode line, so BIDS counts the cue once — and
    # at its onset (the INFO timestamp), not the raw trigger instant.
    log = (
        "2026-06-05 22:00:00.000, INFO, Opened SMACC v0.0.7\n"
        "2026-06-05 22:00:09.978, DEBUG, Cue started: Piano: software trigger at "
        "22:00:09.978, marker advanced +22.0 ms to estimated onset (output latency)\n"
        "2026-06-05 22:00:10.000, INFO, Cue started: Piano - portcode 60\n"
    )
    events = bids.log_to_events(log)
    assert len(events) == 1
    assert events[0]["value"] == 60
    assert events[0]["trial_type"] == "Cue started: Piano"
    assert events[0]["onset"] == 10.0  # the corrected INFO time, not the raw 9.978


def test_onset_is_relative_to_first_log_entry():
    events = bids.log_to_events(SAMPLE_LOG)
    # First event is 5.5s after the "Opened SMACC" line at 22:00:00.000.
    assert events[0]["onset"] == 5.5
    assert events[1]["onset"] == 1810.25


def test_events_have_required_bids_columns():
    events = bids.log_to_events(SAMPLE_LOG)
    for ev in events:
        assert set(ev) == set(bids.EVENT_COLUMNS)
        assert ev["duration"] == "n/a"


def test_empty_log_yields_no_events():
    assert bids.log_to_events("") == []


def test_summarize_log_counts_events_and_spans_duration():
    s = bids.summarize_log(SAMPLE_LOG)
    assert s["event_count"] == 2
    assert s["duration_seconds"] == 2700.0  # 22:00:00 -> 22:45:00
    assert s["subject"] == ""  # SAMPLE_LOG has no settings block
    assert s["session"] == ""


def test_summarize_log_reads_subject_session_from_block():
    payload = settings.build_payload(
        {}, {"subject": "07", "session": "02", "notes": ""}
    )
    block = bids.format_settings_block(payload, "initial")
    log = (
        "2026-06-05 22:00:00.000, INFO, Opened SMACC\n"
        + block
        + "2026-06-05 22:00:10.000, INFO, REM detected - portcode 41\n"
    )
    s = bids.summarize_log(log)
    assert s["subject"] == "07"
    assert s["session"] == "02"
    assert s["event_count"] == 1
    assert s["duration_seconds"] == 10.0  # block lines are skipped by the parser


def test_summarize_log_empty():
    assert bids.summarize_log("") == {
        "event_count": 0,
        "duration_seconds": 0.0,
        "subject": "",
        "session": "",
    }


def test_convert_log_file_writes_tsv_and_sidecar(tmp_path):
    log = tmp_path / "session.log"
    log.write_text(SAMPLE_LOG, encoding="utf-8")
    out = tmp_path / "events.tsv"
    count = bids.convert_log_file(log, out)
    assert count == 2  # returns the event count
    assert out.is_file()
    assert out.with_suffix(".json").is_file()  # sidecar beside the tsv
    header, *rows = out.read_text(encoding="utf-8").splitlines()
    assert header.split("\t") == bids.EVENT_COLUMNS
    assert len(rows) == 2


INCREMENT_LOG = """2026-06-05 22:00:00.000, INFO, Opened SMACC v0.0.7
2026-06-05 22:01:00.000, INFO, Noise volume set to 0.30
2026-06-05 22:02:00.000, INFO, Dream report started - portcode 201
2026-06-05 22:05:00.000, INFO, Dream report stopped - portcode 200
2026-06-05 22:40:00.000, INFO, Dream report started - portcode 202
2026-06-05 22:43:00.000, INFO, Dream report stopped - portcode 200
"""


def test_incrementing_dream_codes_and_soft_logs():
    events = bids.log_to_events(INCREMENT_LOG)
    # The soft "Noise volume set to" line has no portcode, so it's not an event.
    assert len(events) == 4  # 2 starts + 2 stops only
    assert all("set to" not in e["trial_type"] for e in events)
    started = [e["value"] for e in events if e["trial_type"] == "Dream report started"]
    assert started == [201, 202]  # distinct, incrementing codes per report


def test_write_events_tsv_round_trip(tmp_path):
    events = bids.log_to_events(SAMPLE_LOG)
    path = tmp_path / "sub-001_ses-001_events.tsv"
    bids.write_events_tsv(events, path)
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert lines[0] == "onset\tduration\ttrial_type\tvalue"
    assert lines[1].split("\t") == ["5.5", "n/a", "Lights off", "47"]
    assert len(lines) == 3  # header + 2 events


def test_write_events_tsv_quotes_user_text(tmp_path):
    path = tmp_path / "events.tsv"
    events = [
        {
            "onset": 1.25,
            "duration": "n/a",
            "trial_type": "Note: tab\tand newline\ninside",
            "value": 50,
        }
    ]
    bids.write_events_tsv(events, path)
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.reader(stream, delimiter="\t"))
    assert rows == [
        bids.EVENT_COLUMNS,
        ["1.25", "n/a", "Note: tab\tand newline\ninside", "50"],
    ]


def test_write_events_json_sidecar(tmp_path):
    path = tmp_path / "sub-001_ses-001_events.json"
    bids.write_events_json(path)
    import json

    sidecar = json.loads(path.read_text(encoding="utf-8"))
    assert set(sidecar) == set(bids.EVENT_COLUMNS)


# ----- embedded settings block ----------------------------------------------

PAYLOAD = {"kind": "smacc/settings", "schema_version": 1, "settings": {"v": 0.1}}


def test_settings_block_is_ignored_by_event_parsing():
    # A fully-commented settings block (initial + final) must not perturb event
    # extraction or the onset origin (the first timestamped log line).
    log = (
        bids.format_settings_block(PAYLOAD, "initial")
        + SAMPLE_LOG
        + bids.format_settings_block(PAYLOAD, "final")
    )
    events = bids.log_to_events(log)
    assert [e["value"] for e in events] == [47, 201]
    assert events[0]["onset"] == 5.5


def test_extract_settings_initial_and_final():
    initial = {"kind": "smacc/settings", "schema_version": 1, "settings": {"v": 0.1}}
    final = {"kind": "smacc/settings", "schema_version": 1, "settings": {"v": 0.9}}
    log = (
        bids.format_settings_block(initial, "initial")
        + SAMPLE_LOG
        + bids.format_settings_block(final, "final")
    )
    assert bids.extract_settings_from_log(log, "initial") == initial
    assert bids.extract_settings_from_log(log, "final") == final


def test_extract_settings_missing_block_returns_none():
    log = bids.format_settings_block(PAYLOAD, "initial") + SAMPLE_LOG
    assert bids.extract_settings_from_log(log, "final") is None  # crashed session
    assert bids.extract_settings_from_log("no blocks here", "initial") is None


def test_extract_then_parse_round_trips():
    payload = settings.build_payload({"noise_color": "pink"}, {"subject": "001"})
    log = bids.format_settings_block(payload, "initial") + SAMPLE_LOG
    extracted = bids.extract_settings_from_log(log, "initial")
    state, metadata = settings.parse_settings_mapping(extracted)
    assert state == {"noise_color": "pink"}
    assert metadata == {"subject": "001"}
