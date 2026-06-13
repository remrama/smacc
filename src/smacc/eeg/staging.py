"""The sleep-staging model and its TSV/JSON hypnogram sidecar (#182).

A *hypnogram* is a partition of the recording into fixed-length epochs, each
assigned exactly one stage from a closed vocabulary (Wake/N1/N2/N3/REM). That is
a different shape from :mod:`smacc.eeg.annotations`, whose marks are overlapping
free-text spans: a stage epoch always has a positive duration and there is
exactly one stage per slot, so stages live in their own model and their own
sidecar rather than crowding the event list. Scoring two raters of one night
then writes two files and a κ falls straight out — the inter-rater-reliability
workflow staging exists for.

Stages save to a sidecar next to the recording — ``night1.edf`` →
``night1.stages.tsv`` + ``night1.stages.json`` — keyed by rater id exactly like
the annotation sidecar (``night1.stages.alice.tsv``), and the recording is never
touched. The TSV is sparse (only scored epochs get a row; an absent row reads as
unscored) with ``onset``/``duration``/``stage`` columns — the same shape MNE and
BIDS use for a hypnogram-as-events, so the file doubles as interchange. The JSON
records which scoring manual produced it (AASM vs R&K), the epoch grid, and
provenance, so a ``.stages.tsv`` is self-describing.

The scoring vocabulary is data, not code: :class:`StagingVocabulary` bundles the
stages, their hotkeys, and their hypnogram colours, so swapping AASM for
Rechtschaffen & Kales (which adds S3/S4 and a Movement-Time epoch) is a config
choice. Pure functions and frozen dataclasses, no GUI and no MNE — directly
unit-testable, mirroring :mod:`smacc.eeg.annotations`.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..config import VERSION
from .annotations import sanitize_rater_id

# Shown for an epoch with no stage yet. Display-only: the sparse sidecar never
# writes it (an absent row already means "unscored"), and the model forbids it
# as a real stage so it can never be mistaken for one.
UNSCORED = "?"

STAGE_COLUMNS = ["onset", "duration", "stage"]

# Sidecar suffixes appended to the source's stem via Path.with_suffix, so
# "night1.edf" maps to "night1.stages.tsv" (mirrors annotations.py).
STAGES_TSV_SUFFIX = ".stages.tsv"
STAGES_JSON_SUFFIX = ".stages.json"
STAGES_AUTOSAVE_SUFFIX = ".stages.autosave.tsv"

# Onsets/durations carry millisecond precision, exact for every epoch boundary
# at the rates sleep labs record (mirrors annotations.py).
_SECONDS_DECIMALS = 3

# Human labels for every stage token any shipped vocabulary uses; written into
# the JSON sidecar's BIDS-style "Levels" map so a bare ``.stages.tsv`` is
# self-describing without the reader knowing which manual produced it.
STAGE_LABELS = {
    "W": "Wake",
    "N1": "NREM stage 1",
    "N2": "NREM stage 2",
    "N3": "NREM stage 3 (slow-wave sleep)",
    "R": "REM sleep",
    "S1": "NREM stage 1 (R&K)",
    "S2": "NREM stage 2 (R&K)",
    "S3": "NREM stage 3 (R&K)",
    "S4": "NREM stage 4 (R&K)",
    "MT": "Movement time (R&K)",
}


@dataclass(frozen=True)
class StagingVocabulary:
    """A sleep-scoring vocabulary: its stages, hotkeys, and hypnogram colours.

    The single source of truth a staging session reads through, so swapping AASM
    for R&K is a data change, not a code change. ``name`` is written to the
    sidecar as the scoring manual; ``stages`` is the ordered partition
    vocabulary; ``hotkeys`` maps a single upper-case character to the stage it
    scores — plain characters, never Qt key codes, so this module stays GUI-free
    like :mod:`smacc.eeg.annotations`; ``colors`` is an RGB per stage for the
    hypnogram band and overview strip.
    """

    name: str
    stages: tuple[str, ...]
    hotkeys: dict[str, str]
    colors: dict[str, tuple[int, int, int]]

    def __post_init__(self) -> None:
        if not self.stages:
            raise ValueError("A staging vocabulary needs at least one stage")
        if UNSCORED in self.stages:
            raise ValueError(f"{UNSCORED!r} is the unscored sentinel, not a stage")
        unknown = sorted({s for s in self.hotkeys.values() if s not in self.stages})
        if unknown:
            raise ValueError(f"Hotkeys map to stages not in the vocabulary: {unknown}")
        missing = [s for s in self.stages if s not in self.colors]
        if missing:
            raise ValueError(f"Stages missing a colour: {missing}")

    def stage_for_key(self, char: str) -> str | None:
        """The stage a typed character scores, or ``None`` if it scores none."""
        return self.hotkeys.get(char.upper())


# AASM (2007+): the current clinical standard — five stages, no Movement epoch
# (a movement is an event annotation laid over the majority stage, not a stage).
AASM = StagingVocabulary(
    name="AASM",
    stages=("W", "N1", "N2", "N3", "R"),
    hotkeys={"W": "W", "1": "N1", "2": "N2", "3": "N3", "R": "R"},
    colors={
        "W": (242, 201, 76),  # amber — awake
        "N1": (130, 197, 222),  # light blue
        "N2": (74, 144, 200),  # blue
        "N3": (44, 80, 158),  # deep blue — slow-wave sleep
        "R": (224, 96, 120),  # rose — REM
    },
)

# Rechtschaffen & Kales (1968): S1–S4 instead of N1–N3, and a distinct Movement
# Time (MT) epoch for gross movement obscuring the stage — a legitimate partition
# member here (it is *not* one under AASM). MT is keyed off the digits so it
# never collides with the window's M (point-mark) key.
RK = StagingVocabulary(
    name="R&K-1968",
    stages=("W", "S1", "S2", "S3", "S4", "R", "MT"),
    hotkeys={"W": "W", "1": "S1", "2": "S2", "3": "S3", "4": "S4", "R": "R", "5": "MT"},
    colors={
        "W": (242, 201, 76),
        "S1": (130, 197, 222),
        "S2": (74, 144, 200),
        "S3": (52, 96, 170),
        "S4": (36, 64, 130),
        "R": (224, 96, 120),
        "MT": (140, 140, 140),  # grey — unscorable movement
    },
)

VOCABULARIES = {v.name: v for v in (AASM, RK)}
DEFAULT_VOCABULARY = AASM


def vocabulary_by_name(name: str | None) -> StagingVocabulary:
    """Look up a vocabulary by its ``name``; the AASM default for ``None``/unknown.

    Used to resolve a saved preference or a sidecar's ``ScoringManual`` back to a
    vocabulary; an unrecognized name falls back rather than failing, so a file
    from a future/foreign manual still opens (its stages read as free tokens).
    """
    if name is None:
        return DEFAULT_VOCABULARY
    return VOCABULARIES.get(name, DEFAULT_VOCABULARY)


@dataclass(frozen=True, order=True)
class StageEpoch:
    """One scored epoch: seconds from data start, seconds long, and its stage.

    A member of the hypnogram partition — unlike an
    :class:`~smacc.eeg.annotations.Annotation` it always has a positive duration,
    and ``set_stage`` keeps exactly one per slot. Field order gives the natural
    sort (onset, then duration, then stage) via ``order=True``; the stage is
    stripped and the times are rounded to millisecond precision on construction.
    """

    onset: float
    duration: float
    stage: str

    def __post_init__(self) -> None:
        if self.onset < 0:
            raise ValueError(f"Stage onset must be >= 0 (got {self.onset})")
        if self.duration <= 0:
            raise ValueError(f"Stage duration must be > 0 (got {self.duration})")
        stage = self.stage.strip()
        if not stage:
            raise ValueError("Stage must not be empty")
        # Frozen dataclass: normalized fields go through object.__setattr__.
        object.__setattr__(self, "stage", stage)
        object.__setattr__(self, "onset", round(self.onset, _SECONDS_DECIMALS))
        object.__setattr__(self, "duration", round(self.duration, _SECONDS_DECIMALS))


def epoch_bounds(
    anchor: float, epoch_seconds: float, seconds: float
) -> tuple[float, float]:
    """Return ``(onset, duration)`` of the epoch containing ``seconds`` on the grid.

    The grid runs ``anchor + k·epoch_seconds`` for integer ``k`` — the same grid
    the view draws (#173) — so scoring always lands on a boundary-aligned span
    and re-anchoring is well defined. ``onset`` may be negative when ``seconds``
    sits before the anchor; the caller scores only within the recording.
    """
    if epoch_seconds <= 0:
        raise ValueError(f"epoch_seconds must be > 0 (got {epoch_seconds})")
    k = math.floor((seconds - anchor) / epoch_seconds)
    onset = anchor + k * epoch_seconds
    return round(onset, _SECONDS_DECIMALS), round(epoch_seconds, _SECONDS_DECIMALS)


def set_stage(epochs: list[StageEpoch], epoch: StageEpoch) -> list[StageEpoch]:
    """Return a new sorted list with ``epoch`` scored, replacing the slot at its onset.

    Insert-or-replace by onset: epochs come off one locked grid, so a matching
    rounded onset is the same slot. This keeps the partition sorted and
    one-stage-per-slot, and re-scoring an epoch overwrites its prior stage. The
    input list is left untouched.
    """
    out = [e for e in epochs if e.onset != epoch.onset]
    out.append(epoch)
    return sorted(out)


def clear_stage(epochs: list[StageEpoch], onset: float) -> list[StageEpoch]:
    """Return a new list with the epoch at ``onset`` removed (back to unscored)."""
    target = round(onset, _SECONDS_DECIMALS)
    return [e for e in epochs if e.onset != target]


def stage_at(epochs: list[StageEpoch], seconds: float) -> str | None:
    """The stage covering ``seconds``, or ``None`` where nothing is scored.

    The end boundary is exclusive (``onset <= seconds < onset + duration``), so a
    time exactly on an epoch boundary belongs to the epoch that starts there.
    """
    for epoch in epochs:
        if epoch.onset <= seconds < epoch.onset + epoch.duration:
            return epoch.stage
    return None


def stages_sidecar_paths(source: str | Path) -> tuple[Path, Path]:
    """Return the (TSV, JSON) hypnogram sidecar paths for a source recording.

    The source's final suffix is replaced (``night1.edf`` →
    ``night1.stages.tsv``), matching :func:`smacc.eeg.annotations.sidecar_paths`
    so a recording's stages and annotations sit side by side.
    """
    src = Path(source)
    return src.with_suffix(STAGES_TSV_SUFFIX), src.with_suffix(STAGES_JSON_SUFFIX)


def rater_stages_paths(source: str | Path, rater_id: str) -> tuple[Path, Path]:
    """Return the (TSV, JSON) hypnogram sidecar paths for one rater's staging.

    The rater id is woven into the stem (``night1.edf`` →
    ``night1.stages.alice.tsv``) so each rater of one recording writes a
    different path and cross-rater clobbering is structurally impossible — the
    inter-rater-reliability workflow. The id is sanitized to a filename-safe
    token first (shared with the annotation sidecars).
    """
    rater = sanitize_rater_id(rater_id)
    src = Path(source)
    return (
        src.with_suffix(f".stages.{rater}.tsv"),
        src.with_suffix(f".stages.{rater}.json"),
    )


def stages_autosave_path(source: str | Path) -> Path:
    """Return the crash-recovery autosave path for a hypnogram (``…stages.autosave.tsv``).

    Kept distinct from the canonical sidecar so an in-progress autosave is never
    mistaken for, and never overwrites, a deliberate save.
    """
    return Path(source).with_suffix(STAGES_AUTOSAVE_SUFFIX)


def rater_stages_autosave_path(source: str | Path, rater_id: str) -> Path:
    """Return the crash-recovery autosave path for one rater's staging."""
    rater = sanitize_rater_id(rater_id)
    return Path(source).with_suffix(f".stages.{rater}.autosave.tsv")


def write_stages_tsv(epochs: list[StageEpoch], path: str | Path) -> None:
    """Write ``epochs`` (sorted) to ``path`` as a tab-separated hypnogram file."""
    with Path(path).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(STAGE_COLUMNS)
        for epoch in sorted(epochs):
            writer.writerow(
                [
                    f"{epoch.onset:.{_SECONDS_DECIMALS}f}",
                    f"{epoch.duration:.{_SECONDS_DECIMALS}f}",
                    epoch.stage,
                ]
            )


def read_stages_tsv(path: str | Path) -> list[StageEpoch]:
    """Read a hypnogram sidecar TSV back into a sorted list of stage epochs.

    Strict on shape so a half-clobbered or hand-mangled file surfaces as an error
    instead of silently losing epochs: the header must match
    :data:`STAGE_COLUMNS` exactly and every row must parse. ``utf-8-sig`` so a
    sidecar re-saved in Notepad (with a BOM) still reads.

    Raises:
        OSError: if the file can't be read.
        ValueError: on a wrong header or an unparseable row (with its line number).
    """
    with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream, delimiter="\t")
        header = next(reader, None)
        if header != STAGE_COLUMNS:
            raise ValueError(
                f"Not a stages TSV (header {header!r}, expected {STAGE_COLUMNS!r})"
            )
        epochs: list[StageEpoch] = []
        for line_number, row in enumerate(reader, start=2):
            if not row:  # a trailing blank line is not an error
                continue
            if len(row) != len(STAGE_COLUMNS):
                raise ValueError(
                    f"Line {line_number}: expected {len(STAGE_COLUMNS)} "
                    f"columns, got {len(row)}"
                )
            try:
                epoch = StageEpoch(float(row[0]), float(row[1]), row[2])
            except ValueError as exc:
                raise ValueError(f"Line {line_number}: {exc}") from exc
            epochs.append(epoch)
    return sorted(epochs)


def read_stages_json(path: str | Path) -> dict[str, object]:
    """Read a hypnogram JSON sidecar back into its payload dict.

    Lets a resume reconcile the live session with the manual and epoch grid the
    file was scored on (``ScoringManual``/``EpochLength``/``Anchor``) instead of
    the operator's defaults — so an R&K file does not open under AASM. ``utf-8-sig``
    tolerates a Notepad BOM.

    Raises:
        OSError: if the file can't be read.
        ValueError: on invalid JSON or a non-object payload.
    """
    text = Path(path).read_text(encoding="utf-8-sig")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("A stages JSON sidecar must be a JSON object")
    return payload


def stages_sidecar(
    source_name: str,
    meas_date: datetime | None,
    *,
    vocabulary: StagingVocabulary,
    epoch_seconds: float,
    anchor: float,
    rater_id: str | None = None,
) -> dict[str, object]:
    """Return the JSON sidecar payload documenting the columns, grid, and provenance.

    ``ScoringManual`` names the vocabulary so a reader knows whether ``S2`` or
    ``N2`` was meant; ``EpochLength``/``Anchor`` record the grid the stages were
    scored on (so an absolute-onset row can be mapped back to an epoch index);
    ``MeasurementDate`` recovers clock time from the data-relative onsets;
    ``Rater`` attributes a per-rater file (``null`` for a single-rater review).
    """
    return {
        "onset": {
            "Description": "Epoch onset relative to the start of the recording's data.",
            "Units": "second",
        },
        "duration": {
            "Description": "Epoch length.",
            "Units": "second",
        },
        "stage": {
            "Description": "Sleep stage scored for the epoch.",
            "Levels": {s: STAGE_LABELS.get(s, s) for s in vocabulary.stages},
        },
        "ScoringManual": vocabulary.name,
        "EpochLength": epoch_seconds,
        "Anchor": anchor,
        "SourceFile": source_name,
        "MeasurementDate": meas_date.isoformat() if meas_date else None,
        "Rater": rater_id,
        "GeneratedBy": {"Name": "SMACC", "Version": VERSION},
    }


def write_stages_json(
    path: str | Path,
    *,
    source_name: str,
    meas_date: datetime | None,
    vocabulary: StagingVocabulary,
    epoch_seconds: float,
    anchor: float,
    rater_id: str | None = None,
) -> None:
    """Write the hypnogram JSON sidecar to ``path``."""
    payload = stages_sidecar(
        source_name,
        meas_date,
        vocabulary=vocabulary,
        epoch_seconds=epoch_seconds,
        anchor=anchor,
        rater_id=rater_id,
    )
    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
