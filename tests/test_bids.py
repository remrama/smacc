"""Tests for the BIDS events exporter (no GUI required)."""

from smacc import bids, settings

SAMPLE_LOG = """2026-06-05 22:00:00.000, INFO, Opened SMACC v0.0.7
2026-06-05 22:00:05.500, INFO, Lights off - portcode 47
2026-06-05 22:30:10.250, INFO, Note [saw a light] - portcode 201
2026-06-05 22:45:00.000, INFO, Program closed
"""


def test_log_to_events_extracts_only_portcode_lines():
    events = bids.log_to_events(SAMPLE_LOG)
    assert len(events) == 2  # the two "- portcode N" lines, not open/close
    assert [e["value"] for e in events] == [47, 201]
    assert [e["trial_type"] for e in events] == ["Lights off", "Note [saw a light]"]


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
    log = tmp_path / "smacc-20260605-220000.log"
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


def test_write_events_json_sidecar(tmp_path):
    path = tmp_path / "sub-001_ses-001_events.json"
    bids.write_events_json(path)
    import json

    sidecar = json.loads(path.read_text(encoding="utf-8"))
    assert set(sidecar) == set(bids.EVENT_COLUMNS)


# ----- embedded settings block ----------------------------------------------

PAYLOAD = {"kind": "smacc/settings", "schema_version": 3, "settings": {"v": 0.1}}


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
    initial = {"kind": "smacc/settings", "schema_version": 3, "settings": {"v": 0.1}}
    final = {"kind": "smacc/settings", "schema_version": 3, "settings": {"v": 0.9}}
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
