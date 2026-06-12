"""Estimate the clock-skew offset that aligns a session log to an EEG recording (#125).

When the recording carries the same trigger codes SMACC sent (hardware TTL wired
into the amplifier), the log's marker events can be matched to the recording's
*embedded* events to estimate the constant offset that slides the log onto the
EEG — the manual drag/pair of #125b done automatically. This is opportunistic:
an LSL-only rig leaves no triggers in the file, so there is nothing to match and
the manual path stays primary.

Pure, no GUI and no MNE, so the algorithm is unit-testable. The hard part is not
the arithmetic but *not trusting a wrong fit*: an overnight log repeats cue codes
every few seconds, two PC clocks can disagree or jump (NTP, DST), and the wrong
log can be loaded entirely. The estimator therefore:

* anchors only on **rare** codes (a clapper, a dream report, a recording-start),
  never the periodic cue codes that would alias to a neighbour and fit tightly
  but wrongly;
* matches one-to-one (each embedded event consumed once);
* grades the result — :data:`GREEN` (apply silently), :data:`AMBER` (apply but
  flag), :data:`RED` (refuse; the deltas are too few, too scattered, or split
  into two clusters, i.e. a clock jump or the wrong log) — so the caller never
  silently applies a confident-but-wrong offset.

Inputs are ``(seconds, code)`` lists in **recording data-seconds**: the log
events placed at offset 0 against the recording origin (so a correct fit has the
two streams already roughly coincident), the embedded events at their own
data-seconds. The returned ``offset`` is what to add to the log placement.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median

# Alignment quality tiers.
GREEN = "green"  # confident — apply silently
AMBER = "amber"  # low-confidence — apply but flag as unverified
RED = "red"  # unreliable or contradictory — refuse, fall back to manual

# A code anchors the fit only if it occurs at most this many times in the
# overlap window on *each* side — i.e. it is rare enough to pair unambiguously.
# Periodic cue codes (dozens of firings) are excluded from anchoring and only
# admitted to the refine pass, where the fixed coarse offset prevents aliasing.
_ANCHOR_MAX_COUNT = 2
# Anchor nearest-neighbour search half-window around the meas_date prior. Widened
# once if every anchor sits beyond it (a large but consistent clock skew).
_CAPTURE_SECONDS = 90.0
_CAPTURE_SECONDS_WIDE = 300.0
# Refine half-window once the coarse offset is fixed: << the seconds-scale cue
# spacing, so a periodic code can't wrap onto the wrong firing.
_REFINE_SECONDS = 0.5

# Codes excluded from matching entirely: 0 (a return-to-baseline / non-event) and
# 255 (the incrementing-band clamp collision — many distinct reports pile onto it,
# so it is not a unique anchor; see events.runtime_code).
_EXCLUDED_CODES = frozenset({0, 255})

# Tier thresholds.
_GREEN_MIN_ANCHORS = 3
_GREEN_MIN_FRACTION = 0.6
_GREEN_MAX_MAD = 0.25
_AMBER_MIN_FRACTION = 0.3
_AMBER_MAX_MAD = 1.0


@dataclass(frozen=True)
class Alignment:
    """The estimated offset and the evidence behind it.

    ``offset`` is seconds to add to the log placement; ``tier`` is
    :data:`GREEN`/:data:`AMBER`/:data:`RED`. The rest is the evidence a caller
    shows or logs: how many anchor and total matches, the matched fraction, the
    residual spread (median absolute deviation), whether the deltas split into
    two clusters (a clock jump or the wrong log), and a one-line ``reason``.
    """

    offset: float
    tier: str
    n_anchor: int
    n_matched: int
    match_fraction: float
    residual_mad: float
    bimodal: bool
    reason: str


def _in_window(events: list[tuple[float, int]], lo: float, hi: float):
    """Events whose time falls in ``[lo, hi]`` and whose code is matchable."""
    return [(t, c) for t, c in events if c not in _EXCLUDED_CODES and lo <= t <= hi]


def _counts(events: list[tuple[float, int]]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for _t, code in events:
        counts[code] = counts.get(code, 0) + 1
    return counts


def _match_one_to_one(
    log_secs: list[float], emb_secs: list[float], tol: float
) -> list[float]:
    """Greedy one-to-one match within ``tol``; return ``emb - log`` per pair.

    Candidate pairs are taken smallest-gap first, each log and embedded time
    consumed at most once — so duplicate-code events can't double-assign and
    inflate the match count.
    """
    pairs = sorted(
        (abs(e - lg), i, j)
        for i, lg in enumerate(log_secs)
        for j, e in enumerate(emb_secs)
        if abs(e - lg) <= tol
    )
    used_log: set[int] = set()
    used_emb: set[int] = set()
    deltas: list[float] = []
    for _gap, i, j in pairs:
        if i in used_log or j in used_emb:
            continue
        used_log.add(i)
        used_emb.add(j)
        deltas.append(emb_secs[j] - log_secs[i])
    return deltas


def _mad(values: list[float], center: float) -> float:
    """Median absolute deviation of ``values`` about ``center``."""
    return median([abs(v - center) for v in values]) if values else 0.0


def _is_bimodal(deltas: list[float]) -> bool:
    """True if the sorted deltas split into two clusters with a wide gap between.

    A clock step (NTP), a DST rollback, or the wrong log produces two groups of
    matches an offset apart; a single constant offset must not be medianed across
    them. Split at the widest gap and compare it to the spread *within* the two
    sides (not the overall spread, which the split itself inflates and would
    mask): a clean jump leaves each side tight, so the gap dwarfs ``6·MAD`` of
    the tighter-bounded cluster. Needs real support (≥2) on both sides.
    """
    if len(deltas) < 4:
        return False
    ordered = sorted(deltas)
    gaps = [(ordered[i + 1] - ordered[i], i) for i in range(len(ordered) - 1)]
    widest, split = max(gaps)
    left, right = ordered[: split + 1], ordered[split + 1 :]
    if len(left) < 2 or len(right) < 2:
        return False
    within = max(_mad(left, median(left)), _mad(right, median(right)))
    return widest > max(1.0, 6.0 * within)


def estimate_offset(
    log_events: list[tuple[float, int]],
    embedded_events: list[tuple[float, int]],
    *,
    duration: float,
) -> Alignment:
    """Estimate the clock-skew offset aligning the log to the embedded events.

    ``log_events`` and ``embedded_events`` are ``(data_seconds, code)`` with the
    log already placed against the recording origin (offset 0). ``duration`` is
    the recording length. Returns an :class:`Alignment`; a :data:`RED` tier means
    no offset should be applied automatically (``offset`` is 0.0 there).
    """
    if not embedded_events:
        return Alignment(0.0, RED, 0, 0, 0.0, 0.0, False, "no embedded triggers")

    # Coarse pass: anchor only on codes that are rare on both sides, searching a
    # capture window around the prior. The window is widened once for a large
    # skew — including the case where the narrow window catches nothing on a side
    # because every event sits beyond it, so an empty narrow window must retry the
    # wide one (not refuse) before concluding the log truly does not overlap.
    log_in: list[tuple[float, int]] = []
    emb_in: list[tuple[float, int]] = []
    anchor_deltas: list[float] = []
    any_in_window = False
    for capture in (_CAPTURE_SECONDS, _CAPTURE_SECONDS_WIDE):
        log_in = _in_window(log_events, -capture, duration + capture)
        emb_in = _in_window(embedded_events, -capture, duration + capture)
        if not log_in or not emb_in:
            continue
        any_in_window = True
        log_counts = _counts(log_in)
        emb_counts = _counts(emb_in)
        anchor_codes = {
            code
            for code in log_counts
            if log_counts[code] <= _ANCHOR_MAX_COUNT
            and emb_counts.get(code, 0) <= _ANCHOR_MAX_COUNT
            and code in emb_counts
        }
        anchor_deltas = []
        for code in anchor_codes:
            log_secs = [t for t, c in log_in if c == code]
            emb_secs = [t for t, c in emb_in if c == code]
            anchor_deltas.extend(_match_one_to_one(log_secs, emb_secs, capture))
        if anchor_deltas:
            break

    if not any_in_window:
        return Alignment(0.0, RED, 0, 0, 0.0, 0.0, False, "log does not overlap")
    n_anchor = len(anchor_deltas)
    if n_anchor == 0:
        return Alignment(
            0.0, RED, 0, 0, 0.0, 0.0, False, "no rare anchor codes matched"
        )

    r0 = median(anchor_deltas)
    # Refine: with the coarse offset fixed, match each code one-to-one in a tight
    # window — *per code*, so a sparse code never pairs with an unrelated code
    # that merely coincides in time (which would skew the offset and inflate the
    # match count). The r0 shift brings true same-code pairs within ±0.5 s.
    refine: list[float] = []
    emb_by_code: dict[int, list[float]] = {}
    for time, code in emb_in:
        emb_by_code.setdefault(code, []).append(time)
    log_by_code: dict[int, list[float]] = {}
    for time, code in log_in:
        log_by_code.setdefault(code, []).append(time + r0)
    for code, log_secs in log_by_code.items():
        if code in emb_by_code:
            refine.extend(
                _match_one_to_one(log_secs, emb_by_code[code], _REFINE_SECONDS)
            )
    residuals = refine if refine else [0.0]
    offset = r0 + median(residuals)
    mad = _mad(residuals, median(residuals))
    n_matched = len(refine)
    denominator = min(len(log_in), len(emb_in))
    match_fraction = n_matched / denominator if denominator else 0.0
    bimodal = _is_bimodal(anchor_deltas)

    tier, reason = _grade(n_anchor, match_fraction, mad, bimodal)
    if tier == RED:
        return Alignment(
            0.0, RED, n_anchor, n_matched, match_fraction, mad, bimodal, reason
        )
    return Alignment(
        offset, tier, n_anchor, n_matched, match_fraction, mad, bimodal, reason
    )


def _grade(
    n_anchor: int, match_fraction: float, mad: float, bimodal: bool
) -> tuple[str, str]:
    """Map the evidence to a tier and a one-line reason."""
    if bimodal:
        return RED, "matches split into two clusters (clock jump, DST, or wrong log)"
    if mad > _AMBER_MAX_MAD or match_fraction < _AMBER_MIN_FRACTION:
        return RED, "too few or too scattered matches"
    if (
        n_anchor >= _GREEN_MIN_ANCHORS
        and match_fraction >= _GREEN_MIN_FRACTION
        and mad <= _GREEN_MAX_MAD
    ):
        return GREEN, "aligned on embedded trigger codes"
    return AMBER, "low-confidence alignment — verify before trusting marker times"
