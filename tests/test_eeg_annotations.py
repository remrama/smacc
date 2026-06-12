"""Tests for the EEG annotation model and its TSV/JSON sidecars (#136, no GUI)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from smacc.config import VERSION
from smacc.eeg import annotations as ann

# ----- the model ------------------------------------------------------------


def test_annotation_normalizes_whitespace_in_description():
    # Tabs/newlines would corrupt the TSV (no escaping convention exists), so
    # construction collapses them rather than letting the writer corrupt a file.
    a = ann.Annotation(1.0, 0.5, "  saw\ta\nlight \r\n twice  ")
    assert a.description == "saw a light twice"


def test_annotation_rejects_empty_description():
    with pytest.raises(ValueError, match="empty"):
        ann.Annotation(1.0, 0.5, "   \t\n ")


def test_annotation_rejects_negative_onset_and_duration():
    with pytest.raises(ValueError, match="onset"):
        ann.Annotation(-0.001, 0.0, "x")
    with pytest.raises(ValueError, match="duration"):
        ann.Annotation(0.0, -1.0, "x")


def test_annotation_rounds_to_millisecond_precision():
    a = ann.Annotation(1.23456789, 0.0005, "x")
    assert a.onset == 1.235
    assert a.duration == 0.001  # rounds, not truncates


def test_insert_keeps_sort_order_and_leaves_input_untouched():
    first = ann.Annotation(5.0, 1.0, "later")
    existing = [first]
    out = ann.insert(existing, ann.Annotation(2.0, 0.0, "earlier"))
    assert [a.description for a in out] == ["earlier", "later"]
    assert existing == [first]  # pure: caller's list unchanged


def test_replace_resorts_when_an_edit_moves_the_onset():
    items = [ann.Annotation(1.0, 0.0, "a"), ann.Annotation(2.0, 0.0, "b")]
    out = ann.replace(items, 0, ann.Annotation(9.0, 0.0, "a-moved"))
    assert [a.description for a in out] == ["b", "a-moved"]


def test_remove_drops_by_index():
    items = [ann.Annotation(1.0, 0.0, "a"), ann.Annotation(2.0, 0.0, "b")]
    assert [a.description for a in ann.remove(items, 0)] == ["b"]


def test_overlapping_annotations_are_allowed():
    # An arousal marked inside a REM period must coexist; only order matters.
    items = ann.insert(
        [ann.Annotation(10.0, 300.0, "REM period")],
        ann.Annotation(20.0, 5.0, "Arousal"),
    )
    assert len(items) == 2


# ----- sidecar paths --------------------------------------------------------


def test_sidecar_paths_replace_the_recording_suffix():
    tsv, js = ann.sidecar_paths(Path("C:/data/night1.edf"))
    assert tsv.name == "night1.annotations.tsv"
    assert js.name == "night1.annotations.json"


def test_sidecar_paths_keep_bids_style_stems_intact():
    # Deliberately NOT *_events.tsv: opening a file inside a real BIDS dataset
    # must never clobber the dataset's own events sidecar.
    tsv, _ = ann.sidecar_paths(Path("sub-01_task-sleep_eeg.vhdr"))
    assert tsv.name == "sub-01_task-sleep_eeg.annotations.tsv"


# ----- rater-keyed sidecars (#181) ------------------------------------------


def test_sanitize_rater_id_keeps_safe_tokens():
    assert ann.sanitize_rater_id("alice") == "alice"
    assert ann.sanitize_rater_id("rater_1") == "rater_1"
    assert ann.sanitize_rater_id("RM-2") == "RM-2"


def test_sanitize_rater_id_collapses_unsafe_runs_and_trims():
    # The id becomes part of a filename, so spaces/punctuation collapse to a
    # single underscore and the ends are trimmed.
    assert ann.sanitize_rater_id("  rater one!! ") == "rater_one"
    assert ann.sanitize_rater_id("a@@@b") == "a_b"
    assert ann.sanitize_rater_id("rater.01") == "rater_01"  # no dots in the suffix


def test_sanitize_rater_id_rejects_an_empty_token():
    # A blank id must fail loudly rather than silently fall back to the plain
    # single-rater sidecar (which would mix two reviewers' marks).
    for raw in ("", "   ", "!!!", "__"):
        with pytest.raises(ValueError, match="filename-safe"):
            ann.sanitize_rater_id(raw)


def test_rater_sidecar_paths_weave_the_id_into_the_stem():
    tsv, js = ann.rater_sidecar_paths(Path("C:/data/night1.edf"), "alice")
    assert tsv.name == "night1.annotations.alice.tsv"
    assert js.name == "night1.annotations.alice.json"


def test_rater_sidecar_paths_sanitize_the_id():
    tsv, _ = ann.rater_sidecar_paths(Path("night1.edf"), "Rater One")
    assert tsv.name == "night1.annotations.Rater_One.tsv"


def test_rater_paths_differ_per_rater_so_they_cannot_clobber():
    a, _ = ann.rater_sidecar_paths(Path("night1.edf"), "alice")
    b, _ = ann.rater_sidecar_paths(Path("night1.edf"), "bob")
    plain, _ = ann.sidecar_paths(Path("night1.edf"))
    assert len({a, b, plain}) == 3


def test_rater_autosave_path_is_distinct_from_the_sidecar():
    auto = ann.rater_autosave_path(Path("night1.edf"), "alice")
    tsv, _ = ann.rater_sidecar_paths(Path("night1.edf"), "alice")
    assert auto.name == "night1.annotations.alice.autosave.tsv"
    assert auto != tsv


# ----- TSV round-trip -------------------------------------------------------


def test_tsv_round_trip_preserves_annotations(tmp_path):
    items = [
        ann.Annotation(0.0, 0.0, "Lights off"),
        ann.Annotation(12.345, 4.0, "LRLR"),
        ann.Annotation(12.345, 0.5, "Arousal"),  # same onset, shorter: sorts first
    ]
    path = tmp_path / "night1.annotations.tsv"
    ann.write_annotations_tsv(items, path)
    assert ann.read_annotations_tsv(path) == sorted(items)


def test_tsv_is_tab_separated_with_header(tmp_path):
    path = tmp_path / "x.tsv"
    ann.write_annotations_tsv([ann.Annotation(1.5, 0.0, "mark")], path)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "onset\tduration\tdescription"
    assert lines[1] == "1.500\t0.000\tmark"


def test_read_rejects_a_foreign_header(tmp_path):
    path = tmp_path / "x.tsv"
    path.write_text("onset\tduration\ttrial_type\n1.0\t0.0\tmark\n", encoding="utf-8")
    with pytest.raises(ValueError, match="header"):
        ann.read_annotations_tsv(path)


def test_read_reports_the_bad_line_number(tmp_path):
    path = tmp_path / "x.tsv"
    path.write_text(
        "onset\tduration\tdescription\n1.0\t0.0\tok\noops\t0.0\tbad\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Line 3"):
        ann.read_annotations_tsv(path)


def test_read_rejects_a_short_row(tmp_path):
    path = tmp_path / "x.tsv"
    path.write_text("onset\tduration\tdescription\n1.0\t0.0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Line 2"):
        ann.read_annotations_tsv(path)


def test_read_tolerates_a_trailing_blank_line(tmp_path):
    path = tmp_path / "x.tsv"
    path.write_text(
        "onset\tduration\tdescription\n1.0\t0.0\tmark\n\n", encoding="utf-8"
    )
    assert len(ann.read_annotations_tsv(path)) == 1


def test_read_missing_file_raises_oserror(tmp_path):
    with pytest.raises(OSError):
        ann.read_annotations_tsv(tmp_path / "absent.tsv")


def test_round_trip_preserves_double_quotes(tmp_path):
    # The one real escaping case: csv.writer wraps a quoted label and doubles
    # the quotes, and only csv.reader undoes it — a "simplification" to manual
    # tab-joining would silently corrupt every label with a quote in it.
    quoted = ann.Annotation(1.0, 0.5, 'saw a "light" twice')
    path = tmp_path / "x.tsv"
    ann.write_annotations_tsv([quoted], path)
    assert '"saw a ""light"" twice"' in path.read_text(encoding="utf-8")
    assert ann.read_annotations_tsv(path) == [quoted]


def test_round_trip_preserves_unicode(tmp_path):
    item = ann.Annotation(1.0, 0.0, "señal lúcida — ασπίδα")
    path = tmp_path / "x.tsv"
    ann.write_annotations_tsv([item], path)
    assert ann.read_annotations_tsv(path) == [item]


def test_read_accepts_a_hand_edited_windows_file(tmp_path):
    # A sidecar opened and resaved in Notepad gains CRLF endings and a UTF-8
    # BOM; a reviewer's hand-tweaked label must not brick the file.
    path = tmp_path / "x.tsv"
    path.write_bytes(b"\xef\xbb\xbfonset\tduration\tdescription\r\n1.0\t0.0\tmark\r\n")
    assert ann.read_annotations_tsv(path) == [ann.Annotation(1.0, 0.0, "mark")]


# ----- JSON sidecar ---------------------------------------------------------


def test_json_sidecar_documents_columns_and_provenance(tmp_path):
    path = tmp_path / "night1.annotations.json"
    when = datetime(2026, 6, 5, 22, 0, 0, tzinfo=UTC)
    ann.write_annotations_json(path, source_name="night1.edf", meas_date=when)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert set(ann.ANNOTATION_COLUMNS) <= set(payload)
    assert payload["SourceFile"] == "night1.edf"
    assert payload["MeasurementDate"] == when.isoformat()
    assert payload["GeneratedBy"] == {"Name": "SMACC", "Version": VERSION}


def test_json_sidecar_handles_a_missing_meas_date(tmp_path):
    path = tmp_path / "x.json"
    ann.write_annotations_json(path, source_name="x.fif", meas_date=None)
    assert json.loads(path.read_text(encoding="utf-8"))["MeasurementDate"] is None


def test_json_sidecar_records_the_rater_when_set(tmp_path):
    path = tmp_path / "night1.annotations.alice.json"
    ann.write_annotations_json(
        path, source_name="night1.edf", meas_date=None, rater_id="alice"
    )
    assert json.loads(path.read_text(encoding="utf-8"))["Rater"] == "alice"


def test_json_sidecar_rater_is_null_for_a_single_rater_review(tmp_path):
    path = tmp_path / "night1.annotations.json"
    ann.write_annotations_json(path, source_name="night1.edf", meas_date=None)
    assert json.loads(path.read_text(encoding="utf-8"))["Rater"] is None
