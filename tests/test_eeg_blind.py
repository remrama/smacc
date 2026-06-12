"""Tests for the blind-rater presets and config file (#181, no GUI)."""

from __future__ import annotations

import json

import pytest

from smacc.eeg import blind
from smacc.eeg.annotations import Annotation


def _marks() -> list[Annotation]:
    return [
        Annotation(10.0, 0.0, "SignalObserved"),
        Annotation(20.0, 0.0, "DreamReportStarted"),
        Annotation(30.0, 0.0, "Cue started: Piano"),
        Annotation(40.0, 0.0, "Arousal"),
    ]


# ----- the filter -----------------------------------------------------------


def test_naive_hides_every_mark():
    assert blind.apply_blind(_marks(), blind.preset_config(blind.PRESET_NAIVE)) == []


def test_reports_visible_keeps_only_report_marks():
    out = blind.apply_blind(_marks(), blind.preset_config(blind.PRESET_REPORTS))
    assert [a.description for a in out] == ["DreamReportStarted"]


def test_classify_only_blanks_signals_and_drops_the_rest():
    out = blind.apply_blind(_marks(), blind.preset_config(blind.PRESET_CLASSIFY))
    # Only the signal survives, at its time, with the label blanked.
    assert out == [Annotation(10.0, 0.0, "?")]


def test_classify_placeholder_is_configurable():
    config = blind.BlindConfig(
        preset="custom",
        signal_labels=("SignalObserved",),
        classify_placeholder="(classify)",
    )
    assert blind.apply_blind(_marks(), config) == [Annotation(10.0, 0.0, "(classify)")]


def test_matching_is_prefix_and_normalized():
    # Increment suffixes, detail tags, and the spaced human label all match.
    marks = [
        Annotation(1.0, 0.0, "DreamReportStarted-2"),
        Annotation(2.0, 0.0, "Dream report started"),
        Annotation(3.0, 0.0, "SignalObserved: LRLR conf 3"),
    ]
    config = blind.BlindConfig(
        preset="custom",
        visible_labels=("DreamReport",),
        signal_labels=("SignalObserved",),
    )
    out = blind.apply_blind(marks, config)
    assert [a.description for a in out] == [
        "DreamReportStarted-2",
        "Dream report started",
        "?",
    ]


def test_apply_blind_leaves_the_input_untouched():
    marks = _marks()
    blind.apply_blind(marks, blind.preset_config(blind.PRESET_NAIVE))
    assert len(marks) == 4  # pure: caller's list unchanged


def test_preset_config_rejects_an_unknown_preset():
    with pytest.raises(ValueError, match="Unknown blind preset"):
        blind.preset_config("bogus")


def test_blind_config_rejects_an_empty_placeholder():
    with pytest.raises(ValueError, match="placeholder"):
        blind.BlindConfig(preset="custom", classify_placeholder="   ")


# ----- config file round-trip -----------------------------------------------


def test_config_round_trip_preserves_fields(tmp_path):
    config = blind.BlindConfig(
        preset="classify",
        signal_labels=("SignalObserved", "Sniff"),
        palette=("LRLR", "Sniff"),
        classify_placeholder="?",
    )
    path = tmp_path / "study.smacc-blind.json"
    blind.write_blind_config(config, path)
    assert blind.read_blind_config(path) == config


def test_config_envelope_has_kind_and_version(tmp_path):
    path = tmp_path / "x.smacc-blind.json"
    blind.write_blind_config(blind.preset_config(blind.PRESET_NAIVE), path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["kind"] == blind.KIND
    assert payload["schema_version"] == blind.SCHEMA_VERSION


def test_read_rejects_a_foreign_file(tmp_path):
    path = tmp_path / "x.json"
    path.write_text('{"kind": "something-else"}', encoding="utf-8")
    with pytest.raises(ValueError, match="Not a SMACC blind config"):
        blind.read_blind_config(path)


def test_read_rejects_non_string_labels(tmp_path):
    path = tmp_path / "x.smacc-blind.json"
    path.write_text(
        json.dumps({"kind": blind.KIND, "schema_version": 1, "signal_labels": [1, 2]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="signal_labels"):
        blind.read_blind_config(path)


def test_read_tolerates_a_notepad_bom(tmp_path):
    path = tmp_path / "x.smacc-blind.json"
    payload = blind.blind_payload(blind.preset_config(blind.PRESET_NAIVE))
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps(payload).encode("utf-8"))
    assert blind.read_blind_config(path).preset == "naive"


# ----- resolve (CLI --blind) ------------------------------------------------


def test_resolve_blind_accepts_preset_names():
    assert blind.resolve_blind("naive").preset == "naive"
    assert blind.resolve_blind("classify").signal_labels == blind.DEFAULT_SIGNAL_LABELS


def test_resolve_blind_reads_a_config_path(tmp_path):
    path = tmp_path / "study.smacc-blind.json"
    blind.write_blind_config(blind.preset_config(blind.PRESET_REPORTS), path)
    assert blind.resolve_blind(str(path)).preset == "reports"


def test_resolve_blind_rejects_an_unknown_spec():
    with pytest.raises((ValueError, OSError)):
        blind.resolve_blind("not-a-preset-or-file")
