"""The annotation model and its TSV/JSON sidecar files (#136).

An annotation is a labeled span of recording time: ``onset`` and ``duration``
in seconds from the start of the *data* (not clock time), plus a free-text
``description``. Overlapping annotations are simply allowed — BIDS events
permit them and a reviewer marking an arousal inside a REM period needs them —
so the only collection invariant is sort order.

Annotations save to a sidecar next to the source recording — ``night1.edf`` →
``night1.annotations.tsv`` + ``night1.annotations.json`` — and the source file
is never touched. The columns (``onset``/``duration``/``description``) follow
MNE-BIDS conventions, but the name is deliberately *not* BIDS's ``_events.tsv``:
opening a file inside a real BIDS dataset must never clobber the dataset's own
events file. The JSON sidecar documents the columns and records provenance
(source file, measurement date, app version).

Pure functions and frozen dataclasses, no GUI and no MNE — directly
unit-testable, mirroring :mod:`smacc.bids`.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import VERSION

ANNOTATION_COLUMNS = ["onset", "duration", "description"]

# Sidecar suffixes appended to the source's stem (via Path.with_suffix, so
# "night1.edf" maps to "night1.annotations.tsv" — see sidecar_paths).
TSV_SUFFIX = ".annotations.tsv"
JSON_SUFFIX = ".annotations.json"

# Crash-recovery autosave, kept distinct from the canonical sidecar so autosave
# can never clobber a deliberate save ("night1.edf" → the .autosave.tsv).
AUTOSAVE_SUFFIX = ".annotations.autosave.tsv"

# A rater id becomes part of a sidecar's filename ("night1.annotations.<id>.tsv"),
# so it is reduced to a filesystem-safe token: anything outside this class
# collapses to a single underscore (see sanitize_rater_id).
_RATER_ID_UNSAFE = re.compile(r"[^A-Za-z0-9_-]+")

# Onsets/durations are written with millisecond precision: finer than any human
# click on a plot, and exact for every sample at the rates sleep labs record.
_SECONDS_DECIMALS = 3


@dataclass(frozen=True, order=True)
class Annotation:
    """One labeled span: seconds from data start, seconds long, and its label.

    Field order gives the natural sort (onset, then duration, then label) via
    ``order=True``. Construction normalizes the description's whitespace —
    tabs/newlines would corrupt the TSV, and there is no BIDS escaping
    convention to hide behind — and rejects an empty label outright (an
    unlabeled span is meaningless to the next reader of the sidecar).
    """

    onset: float
    duration: float
    description: str

    def __post_init__(self) -> None:
        if self.onset < 0:
            raise ValueError(f"Annotation onset must be >= 0 (got {self.onset})")
        if self.duration < 0:
            raise ValueError(f"Annotation duration must be >= 0 (got {self.duration})")
        # Frozen dataclass: normalized fields go through object.__setattr__.
        normalized = " ".join(self.description.split())
        if not normalized:
            raise ValueError("Annotation description must not be empty")
        object.__setattr__(self, "description", normalized)
        object.__setattr__(self, "onset", round(self.onset, _SECONDS_DECIMALS))
        object.__setattr__(self, "duration", round(self.duration, _SECONDS_DECIMALS))


def insert(annotations: list[Annotation], annotation: Annotation) -> list[Annotation]:
    """Return a new sorted list with ``annotation`` added (input left untouched)."""
    return sorted([*annotations, annotation])


def remove(annotations: list[Annotation], index: int) -> list[Annotation]:
    """Return a new list without the annotation at ``index`` (of the sorted list)."""
    out = list(annotations)
    del out[index]
    return out


def replace(
    annotations: list[Annotation], index: int, annotation: Annotation
) -> list[Annotation]:
    """Return a new sorted list with ``index`` swapped for ``annotation``.

    Re-sorts because an edited onset may move the entry — the caller should
    re-locate the annotation by value, not assume it kept its row.
    """
    out = list(annotations)
    del out[index]
    return insert(out, annotation)


def sidecar_paths(source: str | Path) -> tuple[Path, Path]:
    """Return the (TSV, JSON) sidecar paths for a source recording.

    The source's final suffix is replaced (``night1.edf`` →
    ``night1.annotations.tsv``), so a BrainVision triplet opened via its
    ``.vhdr`` gets one obvious sidecar pair. The JSON's ``SourceFile`` field
    records which recording the pair belongs to.
    """
    src = Path(source)
    return src.with_suffix(TSV_SUFFIX), src.with_suffix(JSON_SUFFIX)


def autosave_path(source: str | Path) -> Path:
    """Return the crash-recovery autosave path for a source recording.

    Deliberately separate from :func:`sidecar_paths` (``night1.edf`` →
    ``night1.annotations.autosave.tsv``) so an in-progress autosave is never
    mistaken for, and never overwrites, the reviewer's deliberate sidecar.
    """
    return Path(source).with_suffix(AUTOSAVE_SUFFIX)


def sanitize_rater_id(raw: str) -> str:
    """Reduce a rater id to a filesystem-safe token (alnum, dash, underscore).

    The rater id *is* the sidecar's path selector
    (``night1.annotations.<id>.tsv``), so any run of other characters collapses
    to a single underscore and the ends are trimmed. Raises ``ValueError`` when
    nothing usable remains — silently yielding an empty token would route a
    rater's marks to the plain single-rater sidecar and mix two reviewers' work.
    """
    token = _RATER_ID_UNSAFE.sub("_", str(raw).strip()).strip("_-")
    if not token:
        raise ValueError(f"Rater id {raw!r} has no filename-safe characters")
    return token


def rater_sidecar_paths(source: str | Path, rater_id: str) -> tuple[Path, Path]:
    """Return the (TSV, JSON) sidecar paths for one rater's review.

    Mirrors :func:`sidecar_paths` with the rater id woven into the stem
    (``night1.edf`` → ``night1.annotations.alice.tsv``), so each rater of one
    recording writes a different path and cross-rater clobbering is structurally
    impossible. The id is sanitized to a safe filename token first.
    """
    rater = sanitize_rater_id(rater_id)
    src = Path(source)
    return (
        src.with_suffix(f".annotations.{rater}.tsv"),
        src.with_suffix(f".annotations.{rater}.json"),
    )


def rater_autosave_path(source: str | Path, rater_id: str) -> Path:
    """Return the crash-recovery autosave path for one rater's review.

    The rater-keyed counterpart of :func:`autosave_path` (``night1.edf`` →
    ``night1.annotations.alice.autosave.tsv``), so a rater's recovery file is
    kept apart both from the canonical per-rater sidecar and from other raters.
    """
    rater = sanitize_rater_id(rater_id)
    return Path(source).with_suffix(f".annotations.{rater}.autosave.tsv")


def write_annotations_tsv(annotations: list[Annotation], path: str | Path) -> None:
    """Write ``annotations`` (sorted) to ``path`` as a tab-separated values file."""
    with Path(path).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(ANNOTATION_COLUMNS)
        for ann in sorted(annotations):
            writer.writerow(
                [
                    f"{ann.onset:.{_SECONDS_DECIMALS}f}",
                    f"{ann.duration:.{_SECONDS_DECIMALS}f}",
                    ann.description,
                ]
            )


def read_annotations_tsv(path: str | Path) -> list[Annotation]:
    """Read a sidecar TSV back into a sorted list of annotations.

    Strict on shape so a half-clobbered or hand-mangled file surfaces as an
    error instead of silently losing rows: the header must match
    :data:`ANNOTATION_COLUMNS` exactly and every row must parse.

    Raises:
        OSError: if the file can't be read.
        ValueError: on a wrong header or an unparseable row (with its line number).
    """
    # utf-8-sig: a sidecar tweaked in Notepad comes back with a BOM, which
    # plain utf-8 would smuggle into the first header cell and fail the strict
    # header check. Writing stays plain utf-8 (no BOM).
    with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream, delimiter="\t")
        header = next(reader, None)
        if header != ANNOTATION_COLUMNS:
            raise ValueError(
                f"Not an annotations TSV (header {header!r}, "
                f"expected {ANNOTATION_COLUMNS!r})"
            )
        annotations: list[Annotation] = []
        for line_number, row in enumerate(reader, start=2):
            if not row:  # a trailing blank line is not an error
                continue
            if len(row) != len(ANNOTATION_COLUMNS):
                raise ValueError(
                    f"Line {line_number}: expected {len(ANNOTATION_COLUMNS)} "
                    f"columns, got {len(row)}"
                )
            try:
                annotation = Annotation(float(row[0]), float(row[1]), row[2])
            except ValueError as exc:
                raise ValueError(f"Line {line_number}: {exc}") from exc
            annotations.append(annotation)
    return sorted(annotations)


def annotations_sidecar(
    source_name: str, meas_date: datetime | None, rater_id: str | None = None
) -> dict[str, Any]:
    """Return the JSON sidecar payload documenting the TSV columns and provenance.

    ``MeasurementDate`` (the recording's absolute start, when the file carries
    one) is what lets a reader reconstruct clock time from the data-relative
    onsets; ``null`` when the format/anonymization dropped it. ``Rater`` names
    the reviewer when this is a per-rater sidecar, and is ``null`` for an
    ordinary single-rater review — so downstream analysis can attribute and
    compare marks across raters by reading one stable field.
    """
    return {
        "onset": {
            "Description": "Annotation onset relative to the start of the "
            "recording's data.",
            "Units": "second",
        },
        "duration": {
            "Description": "Annotation duration; 0 for an instantaneous mark.",
            "Units": "second",
        },
        "description": {"Description": "Annotation label as entered by the reviewer."},
        "SourceFile": source_name,
        "MeasurementDate": meas_date.isoformat() if meas_date else None,
        "Rater": rater_id,
        "GeneratedBy": {"Name": "SMACC", "Version": VERSION},
    }


def write_annotations_json(
    path: str | Path,
    *,
    source_name: str,
    meas_date: datetime | None,
    rater_id: str | None = None,
) -> None:
    """Write the JSON sidecar to ``path``."""
    payload = annotations_sidecar(source_name, meas_date, rater_id)
    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
