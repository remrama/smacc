"""Biocalibration definitions and the run engine behind the Biocals window (#78).

Sleep studies open with *biocals* — scripted participant actions (eyes open/closed,
look left/right, …) whose known physiological signatures let analysts verify
channels against the EEG. Dream-engineering studies add lucidity-signal practice
(LRLR variants, fist clenches, sniffs). This module holds the protocol data and
the timing/marker state machine; the Qt window that renders it lives in
:mod:`smacc.panels.biocals`.

Three layers, all Qt-free and unit-testable:

* :class:`BiocalDef` — the app-defined table of biocals (label, task-window
  duration, spoken instruction, default port code). Like event labels, these stay
  app-defined so improvements reach old studies; only the *stack* below travels
  with a study.
* :class:`BiocalRow` — one row of a study's biocal stack: which biocal, whether
  it joins the played sequence, whether its voice plays, and its (tunable)
  duration. Rows may repeat a biocal (e.g. eyes-closed twice), so they are a
  list, not a set.
* :class:`BiocalRun` — the state machine for running one biocal or a sequence.
  The GUI feeds it presses/ticks and executes the :data:`Action` values it
  returns (emit a marker, start/stop the voice).

Marker timing: the start port code marks the *task window* opening — with the
voice enabled it fires when the announcement ends, matching the manual practice
of speaking the instruction first and marking when the participant complies.
So the trigger channel reads the same whether the voice or the experimenter
gives the instruction.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Event keys of the shared biocal control markers (registered in smacc.events).
# Cancel/complete are shared across biocals — the preceding start code (unique
# per biocal) identifies which biocal they close.
SEQUENCE_STARTED_EVENT = "BiocalSequenceStarted"
SEQUENCE_STOPPED_EVENT = "BiocalSequenceStopped"
CANCELLED_EVENT = "BiocalCancelled"
COMPLETED_EVENT = "BiocalCompleted"

# Voice recordings are WAVs named after the biocal key, looked up in the
# machine-level biocals folder (seeded from the bundled set on first run).
VOICE_SUFFIX = ".wav"

# Task-window bounds for a row's duration spinner (seconds).
MIN_DURATION_S = 1
MAX_DURATION_S = 600


@dataclass(frozen=True)
class BiocalDef:
    """One biocal: its identity, task window, spoken instruction, and start code.

    ``key`` is the stable short id persisted in a study's rows and doubling as
    the voice filename stem; ``event`` is its start marker's key in the event
    registry (the EventDef itself is generated from this table). ``standard``
    biocals (routine sleep-study calibrations) join the played sequence by
    default; the lucid-dreaming ones start unchecked.
    """

    key: str
    event: str
    label: str
    full_name: str
    duration_s: int
    phrase: str
    standard: bool
    code: int

    @property
    def filename(self) -> str:
        """The voice recording's filename (within the biocals folder)."""
        return self.key + VOICE_SUFFIX


# The app-defined biocal table (#78). Start codes occupy the contiguous 110-126
# band, clear of every other default event code; a study can retune any of them
# via the Markers window like any built-in event.
_BIOCALS: tuple[BiocalDef, ...] = (
    BiocalDef(
        "eyes_open",
        "BiocalEyesOpen",
        "Eyes Open",
        "Eyes open, still",
        30,
        "Please open your eyes, look straight ahead, and remain still for "
        "thirty seconds.",
        True,
        110,
    ),
    BiocalDef(
        "eyes_closed",
        "BiocalEyesClosed",
        "Eyes Closed",
        "Eyes closed, relax",
        30,
        "Please close your eyes and relax for thirty seconds.",
        True,
        111,
    ),
    BiocalDef(
        "look_lr",
        "BiocalLookLR",
        "Look L/R",
        "Look left and right",
        15,
        "Please open your eyes and look left, then right. Repeat three times.",
        True,
        112,
    ),
    BiocalDef(
        "look_ud",
        "BiocalLookUD",
        "Look U/D",
        "Look up and down",
        15,
        "Please look up, then down. Repeat three times.",
        True,
        113,
    ),
    BiocalDef(
        "blink",
        "BiocalBlink",
        "Blink",
        "Slow blinks",
        10,
        "Please blink your eyes slowly, five times.",
        True,
        114,
    ),
    BiocalDef(
        "clench_jaw",
        "BiocalClenchJaw",
        "Clench Jaw",
        "Clench jaw",
        10,
        "Please grit your teeth firmly, then release. Repeat three times.",
        True,
        115,
    ),
    BiocalDef(
        "flex_feet",
        "BiocalFlexFeet",
        "Flex Feet",
        "Flex feet",
        15,
        "Please flex your feet up and down several times.",
        True,
        116,
    ),
    BiocalDef(
        "hold_breath",
        "BiocalHoldBreath",
        "Hold Breath",
        "Hold breath",
        10,
        "Please take a deep breath and hold it for ten seconds.",
        True,
        117,
    ),
    BiocalDef(
        "breathe",
        "BiocalBreathe",
        "Breathe",
        "Breathe normally",
        30,
        "Please breathe normally for thirty seconds.",
        True,
        118,
    ),
    BiocalDef(
        "rest",
        "BiocalRest",
        "Rest",
        "Final rest baseline",
        60,
        "Please close your eyes and relax for one minute. We will begin shortly.",
        True,
        119,
    ),
    BiocalDef(
        "lrlr_open",
        "BiocalLRLROpen",
        "LRLR Open",
        "LRLR signal, eyes open",
        30,
        "Please open your eyes and move them left, right, left, right. Pause, "
        "then repeat three times.",
        False,
        120,
    ),
    BiocalDef(
        "lrlr_closed",
        "BiocalLRLRClosed",
        "LRLR Closed",
        "LRLR signal, eyes closed",
        30,
        "Please close your eyes and move them left, right, left, right. Pause, "
        "then repeat three times.",
        False,
        121,
    ),
    BiocalDef(
        "lrlr_slow",
        "BiocalLRLRSlow",
        "LRLR Slow",
        "LRLR signal, slow",
        15,
        "Please close your eyes and perform a single slow left, right, left, "
        "right signal.",
        False,
        122,
    ),
    BiocalDef(
        "fist_clench",
        "BiocalFistClench",
        "Fist Clench",
        "Fist clench signal",
        15,
        "Please clench your fist firmly, then release. Repeat three times.",
        False,
        123,
    ),
    BiocalDef(
        "fist_closed",
        "BiocalFistClosed",
        "Fist Closed",
        "Fist clench, eyes closed",
        10,
        "Please close your eyes and perform a single deliberate fist clench.",
        False,
        124,
    ),
    BiocalDef(
        "sniff_open",
        "BiocalSniffOpen",
        "Sniff Open",
        "Double sniff signal",
        30,
        "Please perform two heavy sniffs in sequence. Pause, then repeat three times.",
        False,
        125,
    ),
    BiocalDef(
        "sniff_closed",
        "BiocalSniffClosed",
        "Sniff Closed",
        "Double sniff, eyes closed",
        30,
        "Please close your eyes and perform two heavy sniffs in sequence. "
        "Pause, then repeat three times.",
        False,
        126,
    ),
)

# Lookup by key (defs are frozen, so sharing the instances is safe).
BIOCALS_BY_KEY: dict[str, BiocalDef] = {b.key: b for b in _BIOCALS}

# The default stack: every standard biocal in protocol order (eyes-closed
# repeats mid-stack, as a row, not a separate definition), then the
# lucid-dreaming signals. Standard rows join the sequence by default.
_DEFAULT_STACK: tuple[str, ...] = (
    "eyes_open",
    "eyes_closed",
    "look_lr",
    "look_ud",
    "blink",
    "eyes_closed",
    "clench_jaw",
    "flex_feet",
    "hold_breath",
    "breathe",
    "rest",
    "lrlr_open",
    "lrlr_closed",
    "lrlr_slow",
    "fist_clench",
    "fist_closed",
    "sniff_open",
    "sniff_closed",
)


def default_biocals() -> list[BiocalDef]:
    """Return the app-defined biocal table (a fresh list of shared frozen defs)."""
    return list(_BIOCALS)


@dataclass
class BiocalRow:
    """One row of a study's biocal stack (rows may repeat a biocal)."""

    key: str
    sequence: bool
    voice: bool
    duration_s: int


def default_rows() -> list[BiocalRow]:
    """Return the default stack: standard rows sequence-checked, all voiced."""
    rows: list[BiocalRow] = []
    for key in _DEFAULT_STACK:
        b = BIOCALS_BY_KEY[key]
        rows.append(
            BiocalRow(key, sequence=b.standard, voice=True, duration_s=b.duration_s)
        )
    return rows


def rows_to_list(rows: Iterable[BiocalRow]) -> list[dict[str, Any]]:
    """Serialize a biocal stack for the ``biocals`` block of a settings file."""
    return [
        {
            "biocal": r.key,
            "sequence": r.sequence,
            "voice": r.voice,
            "duration": r.duration_s,
        }
        for r in rows
    ]


def rows_from_list(loaded: Any) -> list[BiocalRow] | None:
    """Rebuild a biocal stack from a settings file (None when absent/malformed).

    Tolerant by design: a non-list yields ``None`` (the caller keeps its current
    stack), an unknown biocal key is dropped (e.g. a file from a newer SMACC),
    and a missing/invalid field falls back to that biocal's default. An empty
    list is respected — a study may deliberately clear the stack.
    """
    if not isinstance(loaded, list):
        return None
    rows: list[BiocalRow] = []
    for item in loaded:
        if not isinstance(item, dict):
            continue
        key = item.get("biocal")
        if not isinstance(key, str) or key not in BIOCALS_BY_KEY:
            continue
        b = BIOCALS_BY_KEY[key]
        duration = item.get("duration", b.duration_s)
        if isinstance(duration, bool) or not isinstance(duration, int | float):
            duration = b.duration_s
        duration = max(MIN_DURATION_S, min(int(duration), MAX_DURATION_S))
        rows.append(
            BiocalRow(
                key,
                sequence=bool(item.get("sequence", b.standard)),
                voice=bool(item.get("voice", True)),
                duration_s=duration,
            )
        )
    return rows


def missing_voice_files(
    directory: Path,
    defs: Sequence[BiocalDef] | None = None,
    fallback: Path | None = None,
) -> list[str]:
    """Return the (sorted) voice filenames absent from both dirs.

    A recording counts as present if it is in ``directory`` (a lab override) or
    in ``fallback`` (the bundled set, #122). Checked once at session start so the
    operator learns about a genuinely missing recording before the night begins;
    a biocal with a missing voice still runs, just unvoiced.
    """
    table = list(defs) if defs is not None else default_biocals()
    missing = []
    for b in table:
        if (directory / b.filename).is_file():
            continue
        if fallback is not None and (fallback / b.filename).is_file():
            continue
        missing.append(b.filename)
    return sorted(missing)


# ---------------------------------------------------------------------------
# The run engine
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EmitMarker:
    """Action: emit a registry event (``detail`` suffixes the log label)."""

    event: str
    detail: str | None = None


@dataclass(frozen=True)
class PlayVoice:
    """Action: start the voice recording for ``key`` (``label`` for the log)."""

    key: str
    label: str


@dataclass(frozen=True)
class StopVoice:
    """Action: stop any playing voice."""


Action = EmitMarker | PlayVoice | StopVoice


@dataclass(frozen=True)
class RunItem:
    """One biocal scheduled to run: a snapshot of its row taken at start time.

    Freezing the row's voice/duration at start means mid-run edits affect the
    *next* run, never the active one. ``token`` is an opaque handle (the GUI's
    row object) used only to map the active item back to its button.
    """

    token: Any
    key: str
    event: str
    label: str
    voice: bool
    duration_s: float


# Run phases: idle, the voice announcement, then the task window itself.
IDLE = "idle"
VOICE = "voice"
WINDOW = "window"


class BiocalRun:
    """State machine for running one biocal or a sequence of them (no Qt, no I/O).

    The GUI calls the input methods (button presses, the voice ending, timer
    ticks) and executes the returned :data:`Action` list in order; rendering
    reads the public state afterwards. Time comes from the injected ``now``
    callable (monotonic seconds), so the whole timing/marker matrix is testable
    with a fake clock.

    A sequence is just the same per-item path fed from a queue — exactly the
    issue's design: the full sequence reuses the individual events.
    """

    def __init__(self, now: Callable[[], float]) -> None:
        self._now = now
        self.item: RunItem | None = None
        self.phase = IDLE
        self.in_sequence = False
        self._queue: list[RunItem] = []
        self._deadline: float | None = None
        self._seq_total = 0
        self._seq_index = 0  # 1-based position of the active item

    # ----- state queries (for rendering) --------------------------------------

    @property
    def active(self) -> bool:
        """True while a biocal or sequence is underway (any phase)."""
        return self.item is not None or self.in_sequence

    def remaining(self) -> float | None:
        """Seconds left in the active task window (None outside one)."""
        if self.phase != WINDOW or self._deadline is None:
            return None
        return max(0.0, self._deadline - self._now())

    def sequence_progress(self) -> tuple[int, int] | None:
        """(position, total) of the active sequence item, or None outside one."""
        if not self.in_sequence:
            return None
        return self._seq_index, self._seq_total

    # ----- inputs --------------------------------------------------------------

    def start_single(self, item: RunItem) -> list[Action]:
        """Run one biocal on its own, cancelling whatever was active first."""
        actions = self.cancel_all() if self.active else []
        return actions + self._begin(item)

    def start_sequence(self, items: Sequence[RunItem]) -> list[Action]:
        """Run ``items`` in order, cancelling whatever was active first."""
        queued = list(items)
        actions = self.cancel_all() if self.active else []
        if not queued:
            return actions
        self.in_sequence = True
        self._seq_total = len(queued)
        self._seq_index = 0
        self._queue = queued
        n = len(queued)
        actions.append(
            EmitMarker(SEQUENCE_STARTED_EVENT, f"{n} biocal{'s' if n != 1 else ''}")
        )
        return actions + self._advance()

    def cancel_item(self) -> list[Action]:
        """Cancel the active biocal; a sequence skips ahead to its next item."""
        if self.item is None:
            return []
        actions: list[Action] = [StopVoice()] if self.phase == VOICE else []
        actions.append(EmitMarker(CANCELLED_EVENT, self.item.label))
        self._clear_item()
        return actions + self._advance()

    def cancel_all(self) -> list[Action]:
        """Cancel the active biocal and abort the rest of any sequence."""
        actions: list[Action] = []
        if self.item is not None:
            if self.phase == VOICE:
                actions.append(StopVoice())
            actions.append(EmitMarker(CANCELLED_EVENT, self.item.label))
            self._clear_item()
        if self.in_sequence:
            self._reset_sequence()
            actions.append(EmitMarker(SEQUENCE_STOPPED_EVENT, "cancelled"))
        return actions

    def voice_finished(self) -> list[Action]:
        """The announcement ended (or could not play): open the task window."""
        if self.phase != VOICE:
            return []
        return self._begin_window()

    def tick(self) -> list[Action]:
        """Poll for a task window that has run out; advances a sequence."""
        if (
            self.phase != WINDOW
            or self._deadline is None
            or self._now() < self._deadline
        ):
            return []
        item = self.item
        assert item is not None  # WINDOW phase always has an item
        self._clear_item()
        return [EmitMarker(COMPLETED_EVENT, item.label)] + self._advance()

    # ----- internals -----------------------------------------------------------

    def _begin(self, item: RunItem) -> list[Action]:
        """Start ``item``: announce it first when voiced, else open its window."""
        self.item = item
        if item.voice:
            self.phase = VOICE
            return [PlayVoice(item.key, item.label)]
        return self._begin_window()

    def _begin_window(self) -> list[Action]:
        """Open the task window: the start marker fires here, by design."""
        assert self.item is not None
        self.phase = WINDOW
        self._deadline = self._now() + self.item.duration_s
        return [EmitMarker(self.item.event)]

    def _advance(self) -> list[Action]:
        """Begin the next queued item, or close out a finished sequence."""
        if self._queue:
            self._seq_index += 1
            return self._begin(self._queue.pop(0))
        if self.in_sequence:
            self._reset_sequence()
            return [EmitMarker(SEQUENCE_STOPPED_EVENT, "completed")]
        return []

    def _clear_item(self) -> None:
        self.item = None
        self.phase = IDLE
        self._deadline = None

    def _reset_sequence(self) -> None:
        self.in_sequence = False
        self._queue = []
        self._seq_total = 0
        self._seq_index = 0
