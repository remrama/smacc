"""Tests for the BIDS events exporter (no GUI required)."""

from smacc import bids

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
