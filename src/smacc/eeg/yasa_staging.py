"""Automated sleep staging with YASA, as a read-only advisory overlay (#226).

An *optional* second opinion on the manual staging that :mod:`smacc.eeg.staging`
shipped (#182): YASA scores the whole night automatically and returns, per 30-s
epoch, its most-probable stage and the full class-probability distribution. SMACC
shows it alongside the human's hypnogram — never in place of it — so a rater can
spot the low-confidence epochs worth a second look. The manual hypnogram stays
authoritative; nothing here ever writes into it.

Two boundaries make this safe to ship:

* **YASA is lazy and optional.** :func:`run_yasa_staging` imports ``yasa`` inside
  the function, so importing this module never drags in YASA's heavy ML stack
  (lightgbm/numba/llvmlite/pandas). :func:`yasa_available` probes for the package
  without importing it, so the UI can hide the generator when it is absent. The
  *display* side reads only the sidecar (below) and needs no ``yasa`` at all — the
  frozen binary renders a saved overlay whether or not YASA is bundled.

* **A reserved sidecar namespace.** The automated hypnogram saves to
  ``night1.edf`` → ``night1.autostage.tsv`` + ``night1.autostage.json``,
  deliberately *outside* the manual ``.stages.*`` family. A per-rater manual
  hypnogram is ``night1.stages.<rater>.tsv``, so a rater — even one literally
  named "yasa" — can never collide with, or be mistaken for, the machine output.
  The JSON is authoritative (it carries the full probability matrix and the
  provenance a reader needs to trust or flag the result); the TSV is a
  BIDS-style ``onset``/``duration``/``stage`` hypnogram for interchange.

Pure functions and frozen dataclasses, no GUI — directly unit-testable with
``yasa`` mocked, mirroring :mod:`smacc.eeg.staging`.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime
from importlib.util import find_spec
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..config import VERSION

if TYPE_CHECKING:  # only for typing; the runtime import stays inside the function
    from .io import Recording

# YASA scores on a fixed 30-s epoch grid anchored at the data start; the epoch
# length is not configurable (the classifiers are trained on 30-s epochs). The
# display therefore maps YASA epochs by absolute onset, never by the manual
# grid's (re-anchorable) epoch index.
EPOCH_SECONDS = 30.0

# The AASM five-class vocabulary YASA predicts, in a FIXED order. This is both the
# column order of the per-epoch probability vector we store and the intended
# bottom-to-top stack order of the hypnodensity overlay, so it must never be
# reordered — matches :data:`smacc.eeg.staging.AASM`.stages.
AASM_STAGES = ("W", "N1", "N2", "N3", "R")

# YASA's probability-column labels normalized to SMACC's AASM tokens. yasa >= 0.7
# relabels the columns W→WAKE and R→REM (verified in SleepStaging.predict); older
# builds keep W/R. We map explicitly rather than assume identity — an unmapped
# column would drop a stage from the vector (leaving it a silent 0.0).
_YASA_TO_AASM = {
    "W": "W",
    "WAKE": "W",
    "N1": "N1",
    "N2": "N2",
    "N3": "N3",
    "R": "R",
    "REM": "R",
}

# Millisecond onsets (exact on the 30-s grid, mirroring staging.py); probabilities
# rounded so the JSON sidecar round-trips to equal floats.
_SECONDS_DECIMALS = 3
_PROBA_DECIMALS = 6

# Sidecar suffixes, appended via Path.with_suffix like staging.py's — a RESERVED
# family outside the manual ``.stages.*`` namespace (see the module docstring).
AUTOSTAGE_TSV_SUFFIX = ".autostage.tsv"
AUTOSTAGE_JSON_SUFFIX = ".autostage.json"

# The TSV is a plain BIDS-style hypnogram (identical columns to a manual
# ``.stages.tsv``, so the same tooling reads it); the probabilities live in JSON.
AUTOSTAGE_COLUMNS = ["onset", "duration", "stage"]

# JSON envelope version, so a future format change is detectable on read.
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ChannelRoles:
    """The channels handed to YASA: EEG (required), optional EOG and EMG.

    YASA picks the pretrained classifier that matches the roles supplied, so more
    channels means a better model — but EEG alone is a valid run.
    """

    eeg: str
    eog: str | None = None
    emg: str | None = None

    def __post_init__(self) -> None:
        if not self.eeg:
            raise ValueError("An EEG channel is required for automated staging")


@dataclass(frozen=True)
class AutoStageEpoch:
    """One 30-s epoch: onset/duration, YASA's winning stage, and its full
    probability vector aligned to :data:`AASM_STAGES` (the values sum to ~1).

    ``stage`` is the argmax class as an AASM token; ``proba`` is one float per
    stage in :data:`AASM_STAGES` order, so the hypnodensity overlay can stack the
    classes without re-deriving the mapping. Times/probabilities are rounded on
    construction so a JSON round-trip compares equal.
    """

    onset: float
    duration: float
    stage: str
    proba: tuple[float, ...]

    def __post_init__(self) -> None:
        if self.onset < 0:
            raise ValueError(f"Epoch onset must be >= 0 (got {self.onset})")
        if self.duration <= 0:
            raise ValueError(f"Epoch duration must be > 0 (got {self.duration})")
        if self.stage not in AASM_STAGES:
            raise ValueError(f"{self.stage!r} is not an AASM stage {AASM_STAGES}")
        if len(self.proba) != len(AASM_STAGES):
            raise ValueError(
                f"proba needs {len(AASM_STAGES)} values (got {len(self.proba)})"
            )
        object.__setattr__(self, "onset", round(self.onset, _SECONDS_DECIMALS))
        object.__setattr__(self, "duration", round(self.duration, _SECONDS_DECIMALS))
        object.__setattr__(
            self, "proba", tuple(round(float(p), _PROBA_DECIMALS) for p in self.proba)
        )

    @property
    def confidence(self) -> float:
        """The winning class's probability — the epoch's staging confidence."""
        return max(self.proba) if self.proba else 0.0


@dataclass(frozen=True)
class AutoStageHypnogram:
    """A whole-night automated staging plus the provenance to trust or flag it.

    ``epochs`` is the per-epoch result; ``channels``/``yasa_version`` and the
    source ``sfreq``/``duration`` are recorded so a later open can tell whether
    the sidecar still matches the recording (a stale overlay from different
    channels or a re-exported file should be flagged, not trusted silently).
    """

    epochs: tuple[AutoStageEpoch, ...]
    channels: ChannelRoles
    yasa_version: str
    source_sfreq: float
    source_duration: float


def yasa_available() -> bool:
    """True when the optional ``yasa`` package is importable.

    Probes with :func:`importlib.util.find_spec` so it never imports YASA's heavy
    tree — the UI calls it to decide whether to offer the generator at all.
    """
    return find_spec("yasa") is not None


def run_yasa_staging(
    recording: Recording,
    *,
    eeg: str,
    eog: str | None = None,
    emg: str | None = None,
) -> AutoStageHypnogram:
    """Run YASA over ``recording`` and return the automated hypnogram.

    Crops a *copy* of the recording to the chosen channels and preloads only
    those (YASA needs in-memory data and resamples to 100 Hz itself), so an
    overnight, many-channel file is never loaded whole. This is a whole-night
    compute of seconds-to-minutes — the caller runs it off the GUI thread.

    Raises:
        RuntimeError: if ``yasa`` is not installed (guard with
            :func:`yasa_available` first).
        ValueError: if a named channel is not in the recording.
    """
    if not yasa_available():
        raise RuntimeError("The 'yasa' package is not installed")
    import yasa  # noqa: PLC0415 -- lazy on purpose; keeps this module YASA-free

    # Dedupe so one channel can fill two roles (e.g. no separate EOG) without
    # MNE's pick() rejecting a duplicate name; the *names* still go to YASA below.
    picks = list(dict.fromkeys(c for c in (eeg, eog, emg) if c))
    missing = [c for c in picks if c not in recording.ch_names]
    if missing:
        raise ValueError(f"Channel(s) not in the recording: {missing}")
    # Copy → pick → load: only the 1-3 chosen channels reach memory.
    cropped = recording._raw.copy().pick(picks).load_data(verbose="error")
    staged = yasa.SleepStaging(cropped, eeg_name=eeg, eog_name=eog, emg_name=emg)
    epochs = _epochs_from(_probabilities(staged))
    return AutoStageHypnogram(
        epochs=tuple(epochs),
        channels=ChannelRoles(eeg, eog, emg),
        yasa_version=str(getattr(yasa, "__version__", "unknown")),
        source_sfreq=recording.sfreq,
        source_duration=recording.duration,
    )


def _probabilities(staged: Any) -> Any:
    """YASA's per-epoch class-probability DataFrame.

    yasa >= 0.7 returns a ``Hypnogram`` from ``predict()`` whose ``.proba`` holds
    the per-epoch probabilities (its columns relabelled WAKE/REM); older builds
    expose the same table via the now-deprecated ``predict_proba()``. Prefer the
    ``.proba`` path so we avoid the deprecation warning and never depend on
    ``predict()``'s return *shape* — the winning stage is derived from these
    probabilities, so the two can never disagree.
    """
    prediction = staged.predict()
    proba = getattr(prediction, "proba", None)
    return proba if proba is not None else staged.predict_proba()


def _epochs_from(proba: Any) -> list[AutoStageEpoch]:
    """Build the per-epoch list from YASA's probability table.

    Columns are class labels (WAKE/N1/N2/N3/REM on yasa >= 0.7, or W/N1/N2/N3/R on
    older builds); normalize them to AASM tokens, read each row's vector back in
    :data:`AASM_STAGES` order, and take the winning stage as the vector's argmax —
    so the scored stage always matches the probabilities the overlay draws (YASA's
    own ``predict()`` is likewise the argmax of these probabilities).
    """
    column_for: dict[str, Any] = {}
    for column in proba.columns:
        token = _YASA_TO_AASM.get(str(column).strip().upper())
        if token is not None:
            column_for[token] = column
    epochs: list[AutoStageEpoch] = []
    for index, (_epoch, row) in enumerate(proba.iterrows()):
        vector = tuple(
            float(row[column_for[s]]) if s in column_for else 0.0 for s in AASM_STAGES
        )
        stage = AASM_STAGES[vector.index(max(vector))]
        epochs.append(
            AutoStageEpoch(index * EPOCH_SECONDS, EPOCH_SECONDS, stage, vector)
        )
    return epochs


def epoch_at(epochs: list[AutoStageEpoch], seconds: float) -> AutoStageEpoch | None:
    """The automated epoch covering ``seconds`` (end-exclusive), or ``None``.

    Resolved by absolute time so the per-epoch readout stays correct even when the
    manual grid is re-anchored or uses a non-30-s epoch length.
    """
    for epoch in epochs:
        if epoch.onset <= seconds < epoch.onset + epoch.duration:
            return epoch
    return None


def autostage_sidecar_paths(source: str | Path) -> tuple[Path, Path]:
    """Return the (TSV, JSON) automated-staging sidecar paths for a recording.

    ``night1.edf`` → ``night1.autostage.tsv`` + ``night1.autostage.json`` — a
    reserved namespace outside the manual ``.stages.*`` family (see the module
    docstring), so nothing a rater writes can collide with it.
    """
    src = Path(source)
    return src.with_suffix(AUTOSTAGE_TSV_SUFFIX), src.with_suffix(AUTOSTAGE_JSON_SUFFIX)


def write_autostage_tsv(epochs: tuple[AutoStageEpoch, ...], path: str | Path) -> None:
    """Write the winning stage per epoch as a BIDS-style hypnogram TSV.

    Same ``onset``/``duration``/``stage`` columns as a manual ``.stages.tsv``, so
    the same tooling reads it; the per-class probabilities live in the JSON
    sidecar, not here.
    """
    with Path(path).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(AUTOSTAGE_COLUMNS)
        for epoch in epochs:
            writer.writerow(
                [
                    f"{epoch.onset:.{_SECONDS_DECIMALS}f}",
                    f"{epoch.duration:.{_SECONDS_DECIMALS}f}",
                    epoch.stage,
                ]
            )


def autostage_payload(
    hypnogram: AutoStageHypnogram,
    *,
    source_name: str,
    meas_date: datetime | None,
) -> dict[str, Any]:
    """Return the JSON-serializable payload for an automated hypnogram.

    Self-describing: ``Stages`` fixes the probability-vector order, ``Epochs``
    carries the full matrix, and the provenance block records which channels and
    YASA version produced it (so a later open can flag a stale overlay).
    """
    return {
        "kind": "smacc/eeg-autostage",
        "schema_version": SCHEMA_VERSION,
        "ScoringManual": "AASM",
        "Stages": list(AASM_STAGES),
        "EpochLength": EPOCH_SECONDS,
        "Epochs": [
            {
                "onset": epoch.onset,
                "duration": epoch.duration,
                "stage": epoch.stage,
                "proba": list(epoch.proba),
            }
            for epoch in hypnogram.epochs
        ],
        "Channels": {
            "eeg": hypnogram.channels.eeg,
            "eog": hypnogram.channels.eog,
            "emg": hypnogram.channels.emg,
        },
        "SourceFile": source_name,
        "SourceSampleRate": hypnogram.source_sfreq,
        "SourceDuration": hypnogram.source_duration,
        "MeasurementDate": meas_date.isoformat() if meas_date else None,
        "GeneratedBy": {
            "Name": "SMACC",
            "Version": VERSION,
            "YASA": hypnogram.yasa_version,
        },
    }


def write_autostage_json(
    path: str | Path,
    hypnogram: AutoStageHypnogram,
    *,
    source_name: str,
    meas_date: datetime | None,
) -> None:
    """Write the automated-staging JSON sidecar (the authoritative artifact)."""
    payload = autostage_payload(hypnogram, source_name=source_name, meas_date=meas_date)
    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_autostage_json(path: str | Path) -> AutoStageHypnogram:
    """Read an automated-staging JSON sidecar back into a hypnogram.

    Strict on shape so a mangled or foreign file is refused rather than
    half-applied, and a sidecar from a newer SMACC (higher ``schema_version``) is
    rejected with a clear message rather than silently misread — matching the
    settings/surveys readers. ``utf-8-sig`` tolerates a Notepad BOM.

    Raises:
        OSError: if the file can't be read.
        ValueError: on invalid JSON, a wrong ``kind``, a too-new schema, or an
            unparseable epoch.
    """
    text = Path(path).read_text(encoding="utf-8-sig")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("An autostage JSON sidecar must be a JSON object")
    if payload.get("kind") != "smacc/eeg-autostage":
        raise ValueError(
            f"Not a SMACC autostage sidecar (kind={payload.get('kind')!r})"
        )
    version = payload.get("schema_version")
    if isinstance(version, int) and version > SCHEMA_VERSION:
        raise ValueError(
            f"autostage sidecar schema_version {version} is newer than this SMACC "
            f"reads ({SCHEMA_VERSION}) — update SMACC to open it"
        )
    raw_epochs = payload.get("Epochs")
    if not isinstance(raw_epochs, list):
        raise ValueError("'Epochs' must be a list")
    epochs: list[AutoStageEpoch] = []
    for index, item in enumerate(raw_epochs):
        if not isinstance(item, dict):
            raise ValueError(f"Epoch {index} is not an object")
        try:
            epochs.append(
                AutoStageEpoch(
                    float(item["onset"]),
                    float(item["duration"]),
                    str(item["stage"]),
                    tuple(float(p) for p in item["proba"]),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Epoch {index}: {exc}") from exc
    channels = payload.get("Channels")
    if not isinstance(channels, dict) or not channels.get("eeg"):
        raise ValueError("'Channels' must record at least the EEG channel")
    generated = payload.get("GeneratedBy")
    generated = generated if isinstance(generated, dict) else {}
    return AutoStageHypnogram(
        epochs=tuple(epochs),
        channels=ChannelRoles(
            str(channels["eeg"]),
            _optional_str(channels.get("eog")),
            _optional_str(channels.get("emg")),
        ),
        yasa_version=str(generated.get("YASA", "unknown")),
        source_sfreq=float(payload.get("SourceSampleRate", 0.0)),
        source_duration=float(payload.get("SourceDuration", 0.0)),
    )


def _optional_str(value: Any) -> str | None:
    return str(value) if value else None
