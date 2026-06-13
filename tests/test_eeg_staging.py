"""Tests for the EEG sleep-staging model and its hypnogram sidecars (#182, no GUI)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from smacc.config import VERSION
from smacc.eeg import staging

# ----- the vocabulary -------------------------------------------------------


def test_aasm_default_has_the_five_standard_stages_and_no_movement():
    # AASM scores a movement as an event annotation over the majority stage, so
    # the partition vocabulary is exactly W/N1/N2/N3/R — no Movement stage.
    assert staging.AASM.stages == ("W", "N1", "N2", "N3", "R")
    assert "MT" not in staging.AASM.stages
    assert staging.DEFAULT_VOCABULARY is staging.AASM


def test_rk_vocabulary_adds_s_stages_and_a_movement_token():
    # R&K (1968) had S1-S4 and a distinct Movement-Time epoch class.
    assert staging.RK.stages == ("W", "S1", "S2", "S3", "S4", "R", "MT")


def test_stage_for_key_is_case_insensitive_and_misses_cleanly():
    assert staging.AASM.stage_for_key("2") == "N2"
    assert staging.AASM.stage_for_key("w") == "W"
    assert staging.AASM.stage_for_key("R") == "R"
    assert staging.AASM.stage_for_key("9") is None  # 4-9 are inert under AASM


def test_rk_movement_key_avoids_the_window_mark_key():
    # The window binds M to a point mark; R&K's MT must not steal it, so MT is
    # keyed off a digit, not "M".
    assert "M" not in staging.RK.hotkeys
    assert staging.RK.stage_for_key("5") == "MT"


def test_vocabulary_rejects_unscored_sentinel_as_a_stage():
    with pytest.raises(ValueError, match="sentinel"):
        staging.StagingVocabulary(
            "bad", (staging.UNSCORED,), {}, {staging.UNSCORED: (0, 0, 0)}
        )


def test_vocabulary_rejects_hotkey_to_unknown_stage():
    with pytest.raises(ValueError, match="not in the vocabulary"):
        staging.StagingVocabulary("bad", ("W",), {"X": "REM"}, {"W": (0, 0, 0)})


def test_vocabulary_rejects_stage_without_a_colour():
    with pytest.raises(ValueError, match="colour"):
        staging.StagingVocabulary("bad", ("W", "N1"), {}, {"W": (0, 0, 0)})


def test_vocabulary_by_name_resolves_known_and_falls_back():
    assert staging.vocabulary_by_name("R&K-1968") is staging.RK
    assert staging.vocabulary_by_name(None) is staging.DEFAULT_VOCABULARY
    assert staging.vocabulary_by_name("Martian-2099") is staging.DEFAULT_VOCABULARY


# ----- the epoch model ------------------------------------------------------


def test_stage_epoch_rejects_nonpositive_duration_and_negative_onset():
    # A partition epoch is a span, never a point — unlike a free annotation.
    with pytest.raises(ValueError, match="duration"):
        staging.StageEpoch(0.0, 0.0, "N2")
    with pytest.raises(ValueError, match="onset"):
        staging.StageEpoch(-1.0, 30.0, "N2")


def test_stage_epoch_rejects_empty_stage_and_strips_whitespace():
    with pytest.raises(ValueError, match="empty"):
        staging.StageEpoch(0.0, 30.0, "   ")
    assert staging.StageEpoch(0.0, 30.0, "  N2 ").stage == "N2"


def test_stage_epoch_rounds_times_to_milliseconds():
    e = staging.StageEpoch(1.23456, 30.00049, "N2")
    assert e.onset == 1.235
    assert e.duration == 30.0


def test_stage_epochs_sort_by_onset():
    later = staging.StageEpoch(30.0, 30.0, "N1")
    earlier = staging.StageEpoch(0.0, 30.0, "W")
    assert sorted([later, earlier]) == [earlier, later]


def test_epoch_bounds_aligns_to_the_grid_from_a_zero_anchor():
    assert staging.epoch_bounds(0.0, 30.0, 0.0) == (0.0, 30.0)
    assert staging.epoch_bounds(0.0, 30.0, 75.0) == (60.0, 30.0)  # 3rd epoch
    # A time exactly on a boundary belongs to the epoch that starts there.
    assert staging.epoch_bounds(0.0, 30.0, 30.0) == (30.0, 30.0)


def test_epoch_bounds_honours_a_nonzero_anchor():
    # Anchoring on a feature (#173) back/front-fills the grid from that point.
    assert staging.epoch_bounds(5.0, 30.0, 40.0) == (35.0, 30.0)
    assert staging.epoch_bounds(5.0, 30.0, 5.0) == (5.0, 30.0)


def test_epoch_bounds_rejects_nonpositive_epoch_length():
    with pytest.raises(ValueError, match="epoch_seconds"):
        staging.epoch_bounds(0.0, 0.0, 10.0)


# ----- partition operations -------------------------------------------------


def test_set_stage_inserts_in_sorted_order_and_leaves_input_untouched():
    first = staging.StageEpoch(30.0, 30.0, "N2")
    existing = [first]
    out = staging.set_stage(existing, staging.StageEpoch(0.0, 30.0, "W"))
    assert [e.stage for e in out] == ["W", "N2"]
    assert existing == [first]  # pure: caller's list unchanged


def test_set_stage_replaces_the_slot_at_the_same_onset():
    epochs = [staging.StageEpoch(0.0, 30.0, "N1")]
    out = staging.set_stage(epochs, staging.StageEpoch(0.0, 30.0, "N2"))
    assert out == [staging.StageEpoch(0.0, 30.0, "N2")]  # one slot, overwritten


def test_clear_stage_removes_only_the_named_slot():
    epochs = [
        staging.StageEpoch(0.0, 30.0, "W"),
        staging.StageEpoch(30.0, 30.0, "N1"),
    ]
    out = staging.clear_stage(epochs, 30.0)
    assert out == [staging.StageEpoch(0.0, 30.0, "W")]


def test_stage_at_returns_the_covering_stage_with_exclusive_end():
    epochs = [
        staging.StageEpoch(0.0, 30.0, "W"),
        staging.StageEpoch(30.0, 30.0, "N1"),
    ]
    assert staging.stage_at(epochs, 15.0) == "W"
    assert staging.stage_at(epochs, 30.0) == "N1"  # boundary belongs to next epoch
    assert staging.stage_at(epochs, 90.0) is None  # past the scored range


# ----- sidecar paths --------------------------------------------------------


def test_sidecar_paths_sit_beside_the_recording():
    tsv, js = staging.stages_sidecar_paths("/data/night1.edf")
    assert tsv == Path("/data/night1.stages.tsv")
    assert js == Path("/data/night1.stages.json")


def test_rater_paths_weave_in_a_sanitized_id():
    tsv, js = staging.rater_stages_paths("night1.edf", "Alice Smith")
    assert tsv.name == "night1.stages.Alice_Smith.tsv"
    assert js.name == "night1.stages.Alice_Smith.json"


def test_autosave_paths_are_distinct_from_the_sidecar():
    assert (
        staging.stages_autosave_path("night1.edf").name == "night1.stages.autosave.tsv"
    )
    assert (
        staging.rater_stages_autosave_path("night1.edf", "bob").name
        == "night1.stages.bob.autosave.tsv"
    )


# ----- TSV round-trip -------------------------------------------------------


def test_tsv_round_trips_epochs(tmp_path: Path):
    epochs = [
        staging.StageEpoch(0.0, 30.0, "W"),
        staging.StageEpoch(30.0, 30.0, "N1"),
        staging.StageEpoch(60.0, 30.0, "N2"),
    ]
    path = tmp_path / "night1.stages.tsv"
    staging.write_stages_tsv(epochs, path)
    assert staging.read_stages_tsv(path) == epochs


def test_tsv_is_sparse_only_scored_epochs_get_a_row(tmp_path: Path):
    path = tmp_path / "night1.stages.tsv"
    staging.write_stages_tsv([staging.StageEpoch(60.0, 30.0, "N2")], path)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "onset\tduration\tstage"
    assert len(lines) == 2  # header + the one scored epoch, no unscored rows


def test_read_rejects_a_wrong_header(tmp_path: Path):
    path = tmp_path / "bad.tsv"
    path.write_text("onset\tstage\n0.0\tN2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Not a stages TSV"):
        staging.read_stages_tsv(path)


def test_read_reports_the_line_of_a_bad_row(tmp_path: Path):
    path = tmp_path / "bad.tsv"
    path.write_text("onset\tduration\tstage\n0.0\t-5.0\tN2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Line 2"):
        staging.read_stages_tsv(path)


def test_read_tolerates_a_notepad_bom(tmp_path: Path):
    path = tmp_path / "night1.stages.tsv"
    path.write_text("onset\tduration\tstage\n0.000\t30.000\tN2\n", encoding="utf-8-sig")
    assert staging.read_stages_tsv(path) == [staging.StageEpoch(0.0, 30.0, "N2")]


# ----- JSON sidecar ---------------------------------------------------------


def test_json_sidecar_records_manual_grid_and_provenance(tmp_path: Path):
    path = tmp_path / "night1.stages.json"
    staging.write_stages_json(
        path,
        source_name="night1.edf",
        meas_date=datetime(2026, 6, 5, 22, 0, tzinfo=UTC),
        vocabulary=staging.AASM,
        epoch_seconds=30.0,
        anchor=0.0,
        rater_id="alice",
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["ScoringManual"] == "AASM"
    assert payload["EpochLength"] == 30.0
    assert payload["Anchor"] == 0.0
    assert payload["Rater"] == "alice"
    assert payload["SourceFile"] == "night1.edf"
    assert payload["MeasurementDate"] == "2026-06-05T22:00:00+00:00"
    assert payload["GeneratedBy"] == {"Name": "SMACC", "Version": VERSION}
    # The stage column documents its allowed levels, so a bare TSV is readable.
    assert payload["stage"]["Levels"]["N3"].startswith("NREM stage 3")


def test_json_sidecar_rater_is_null_for_a_single_rater_review(tmp_path: Path):
    path = tmp_path / "night1.stages.json"
    staging.write_stages_json(
        path,
        source_name="night1.edf",
        meas_date=None,
        vocabulary=staging.RK,
        epoch_seconds=20.0,
        anchor=2.5,
        rater_id=None,
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["Rater"] is None
    assert payload["MeasurementDate"] is None
    assert payload["ScoringManual"] == "R&K-1968"
    assert "MT" in payload["stage"]["Levels"]
