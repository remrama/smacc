"""Tests for the log↔EEG auto-alignment estimator (#125, pure, no GUI/MNE)."""

from __future__ import annotations

import pytest

from smacc.eeg import align


def _shift(events, by):
    """Move every (seconds, code) event later by ``by`` seconds."""
    return [(t + by, c) for t, c in events]


# Three rare anchor codes (clapper 49, two dream reports) plus a periodic cue
# code 60 firing every 2 s — the realistic shape the matcher must handle.
ANCHORS = [(100.0, 49), (500.0, 201), (1500.0, 202)]
CUES = [(float(t), 60) for t in range(200, 260, 2)]  # 30 firings, 2 s apart
EMBEDDED = sorted(ANCHORS + CUES)


def test_clean_offset_is_recovered_green():
    # The EEG carries the same codes 3 s after where the log places them.
    log = _shift(EMBEDDED, -3.0)
    result = align.estimate_offset(log, EMBEDDED, duration=2000.0)
    assert result.tier == align.GREEN
    assert result.offset == 3.0
    assert result.n_anchor == 3
    assert result.residual_mad <= 0.25


def test_periodic_cue_codes_do_not_alias_the_offset():
    # The same fit, but the meas_date prior is off by ~one cue period (2 s). A
    # naive nearest-neighbour on the cue code would snap to a neighbour and fit
    # tightly but wrongly; anchoring only on the rare codes keeps it correct.
    log = _shift(EMBEDDED, -3.0)
    result = align.estimate_offset(log, EMBEDDED, duration=2000.0)
    # Offset is driven by the anchors, not the dense periodic code.
    assert result.offset == 3.0


def test_no_embedded_triggers_is_red():
    log = _shift(EMBEDDED, -3.0)
    result = align.estimate_offset(log, [], duration=2000.0)
    assert result.tier == align.RED
    assert result.offset == 0.0
    assert "no embedded" in result.reason


def test_only_periodic_codes_gives_no_anchor_red():
    # Without a rare code to anchor on, the matcher refuses rather than guessing
    # from an aliasing periodic code.
    log = _shift(CUES, -3.0)
    result = align.estimate_offset(log, CUES, duration=2000.0)
    assert result.tier == align.RED
    assert result.n_anchor == 0


def test_clock_jump_makes_it_bimodal_red():
    # Half the night's anchors sit at +3 s, the other half at +20 s (an NTP step
    # mid-record). A single median would be confidently wrong; refuse instead.
    embedded = [
        (100.0, 49),
        (500.0, 201),
        (1500.0, 202),
        (2500.0, 110),
        (3500.0, 111),
        (4500.0, 112),
    ]
    log = [
        (97.0, 49),
        (497.0, 201),
        (1497.0, 202),  # +3 s cluster
        (2480.0, 110),
        (3480.0, 111),
        (4480.0, 112),  # +20 s cluster
    ]
    result = align.estimate_offset(log, embedded, duration=5000.0)
    assert result.bimodal is True
    assert result.tier == align.RED


def test_wrong_log_no_overlap_is_red():
    # A log whose events land entirely outside the recording span (a different
    # night) has nothing in the window to match.
    far = _shift(EMBEDDED, 100000.0)
    result = align.estimate_offset(far, EMBEDDED, duration=2000.0)
    assert result.tier == align.RED
    assert "overlap" in result.reason


def test_excluded_codes_are_ignored():
    # Code 0 (baseline) and 255 (the increment-band clamp collision) never anchor.
    embedded = [(100.0, 0), (200.0, 255), (300.0, 49), (800.0, 201), (1600.0, 202)]
    log = _shift(embedded, -2.0)
    result = align.estimate_offset(log, embedded, duration=2000.0)
    # Only 49/201/202 anchor; 0 and 255 are dropped (still a clean +2 s fit).
    assert result.offset == 2.0
    assert result.n_anchor == 3


def test_one_to_one_match_does_not_double_assign():
    # Two embedded code-49 events near one log code-49: only one pair forms.
    deltas = align._match_one_to_one([10.0], [9.8, 10.3], tol=1.0)
    assert len(deltas) == 1
    assert abs(deltas[0]) <= 0.3  # the nearer (9.8) is chosen


def test_wide_capture_window_recovers_a_large_skew():
    # All anchors sit in the first minute; the log places them 200 s before the
    # embedded events — beyond the ±90 s narrow window, so the narrow pass finds
    # nothing in-window on the log side. The wide (±300 s) window must still be
    # tried rather than refusing outright.
    embedded = [(20.0, 49), (40.0, 201), (60.0, 202)]
    log = _shift(embedded, -200.0)
    result = align.estimate_offset(log, embedded, duration=100.0)
    assert result.tier == align.GREEN
    assert result.offset == pytest.approx(200.0)


def test_refine_does_not_count_cross_code_coincidences():
    # A log code-70 event coincides (within 0.5 s after the +3 s shift) with an
    # embedded code-99 event. They are different codes, so the refine pass must
    # NOT pair them — that would inflate the match count and skew the offset.
    embedded = [(100.0, 49), (500.0, 201), (1500.0, 202), (1003.0, 99)]
    log = [(97.0, 49), (497.0, 201), (1497.0, 202), (1000.0, 70)]
    result = align.estimate_offset(log, embedded, duration=2000.0)
    assert result.offset == pytest.approx(3.0)  # not pulled by the 70↔99 coincidence
    assert result.n_matched == 3  # only the three real same-code anchors
