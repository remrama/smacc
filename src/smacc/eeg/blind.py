"""Blind-rater presets for the EEG annotator (#181).

Objective signal scoring uses blind judges, and labs differ on how blind: a
fully naive scroll-through, a review that may see dream-report markers but not
detected signals, or one shown only that *a* signal exists and asked to classify
it. This module is the pure core of that: a :class:`BlindConfig` (which labels a
rater may see, which are blanked, the quick-mark palette) and :func:`apply_blind`,
a single rule the window runs **before any annotation is shown** so a rater can
never glimpse what is meant to be hidden.

The three presets are just named ``(visible_labels, signal_labels)`` pairs over
the annotation's free-text ``description`` — no annotation-category schema is
needed (the shipped model has none). Matching is normalized and prefix-based, so
``DreamReportStarted``/``Dream report 1`` and ``SignalObserved: LRLR`` all match
their configured stem despite increments and detail suffixes.

A config can be saved as a standalone ``<study>.smacc-blind.json`` — the same
envelope pattern as :mod:`smacc.eeg.profiles` — so a coordinator defines the
blinding once and hands it out. Pure dataclasses + JSON I/O, no GUI and no MNE.

Note: blinding is *procedural integrity*, not a security boundary. The guarantee
is that the app never renders a hidden label; a rater with filesystem access can
always read the source recording or the coordinator's sidecar directly.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import VERSION
from .annotations import Annotation

# JSON envelope: a stable kind + schema version so a stray file is rejected
# rather than half-applied (mirrors smacc.eeg.profiles).
KIND = "smacc/eeg-blind-config"
SCHEMA_VERSION = 1

BLIND_SUFFIX = ".smacc-blind.json"
FILE_FILTER = "SMACC blind config (*.smacc-blind.json);;All files (*)"

# Built-in presets (canonical names; the window shows friendlier labels).
PRESET_NAIVE = "naive"  # hide every mark
PRESET_REPORTS = "reports"  # show only dream-report markers
PRESET_CLASSIFY = "classify"  # show signal positions, blank their labels
PRESET_CUSTOM = "custom"  # an explicit visible/signal pairing from a file
PRESET_NAMES = (PRESET_NAIVE, PRESET_REPORTS, PRESET_CLASSIFY)

# Defaults seeding the report/signal allow-lists. Matched as normalized prefixes
# (see _matches), so these catch the key form, the human label, and increment or
# detail suffixes. SignalObserved is SMACC's lucidity-signal marker (events.py);
# DreamReport* are the dream-report markers. Labs extend these in the config —
# adding more is pure data, no code change.
DEFAULT_SIGNAL_LABELS = ("SignalObserved",)
DEFAULT_REPORT_LABELS = ("DreamReport",)

# Stand-in shown for a blanked signal in classify-only. Configurable; never empty
# (the annotation model rejects empty descriptions, so a literal blank is out).
DEFAULT_PLACEHOLDER = "?"


@dataclass(frozen=True)
class BlindConfig:
    """A blinding rule: which labels a rater sees, which are blanked, the palette.

    ``visible_labels`` are shown verbatim; ``signal_labels`` are shown at their
    original time but with the label replaced by ``classify_placeholder`` (the
    "a signal is here — classify it" case); everything else is dropped. ``preset``
    is a human tag for the UI. ``palette`` optionally overrides the operator's
    quick-mark buttons so a coordinator ships the classification vocabulary too.
    """

    preset: str = PRESET_CUSTOM
    visible_labels: tuple[str, ...] = ()
    signal_labels: tuple[str, ...] = ()
    palette: tuple[str, ...] = ()
    classify_placeholder: str = DEFAULT_PLACEHOLDER

    def __post_init__(self) -> None:
        if not self.classify_placeholder.strip():
            raise ValueError("classify_placeholder must not be empty")


def _normalize(text: str) -> str:
    """Lower-case and strip non-alphanumerics, for tolerant label matching."""
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _matches(description: str, patterns: tuple[str, ...]) -> bool:
    """True if ``description`` normalized starts with any pattern normalized.

    Prefix (not equality) so a configured ``SignalObserved`` matches
    ``SignalObserved: LRLR`` and ``DreamReport`` matches ``DreamReportStarted-2``.
    """
    norm = _normalize(description)
    return any(norm.startswith(p) for p in (_normalize(x) for x in patterns) if p)


def apply_blind(annotations: list[Annotation], config: BlindConfig) -> list[Annotation]:
    """Return the rater-visible annotations under ``config`` (input untouched).

    The one rule behind every preset: a mark whose label is in
    ``visible_labels`` is kept verbatim; one in ``signal_labels`` is kept at its
    time with the label blanked to ``classify_placeholder``; anything else is
    dropped. Naive is the empty/empty case (everything dropped); reports-visible
    fills ``visible_labels``; classify-only fills ``signal_labels``.
    """
    out: list[Annotation] = []
    for a in annotations:
        if _matches(a.description, config.visible_labels):
            out.append(a)
        elif _matches(a.description, config.signal_labels):
            out.append(Annotation(a.onset, a.duration, config.classify_placeholder))
        # else: hidden from the rater
    return sorted(out)


def preset_config(
    preset: str,
    *,
    signal_labels: tuple[str, ...] = DEFAULT_SIGNAL_LABELS,
    report_labels: tuple[str, ...] = DEFAULT_REPORT_LABELS,
    palette: tuple[str, ...] = (),
    placeholder: str = DEFAULT_PLACEHOLDER,
) -> BlindConfig:
    """Build a :class:`BlindConfig` for a built-in preset.

    Raises:
        ValueError: for an unknown preset name.
    """
    if preset == PRESET_NAIVE:
        return BlindConfig(PRESET_NAIVE, (), (), palette, placeholder)
    if preset == PRESET_REPORTS:
        return BlindConfig(
            PRESET_REPORTS, tuple(report_labels), (), palette, placeholder
        )
    if preset == PRESET_CLASSIFY:
        return BlindConfig(
            PRESET_CLASSIFY, (), tuple(signal_labels), palette, placeholder
        )
    raise ValueError(
        f"Unknown blind preset {preset!r} (known: {', '.join(PRESET_NAMES)})"
    )


def blind_payload(config: BlindConfig) -> dict[str, Any]:
    """Return the JSON-serializable envelope for ``config``."""
    return {
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "preset": config.preset,
        "visible_labels": list(config.visible_labels),
        "signal_labels": list(config.signal_labels),
        "palette": list(config.palette),
        "classify_placeholder": config.classify_placeholder,
        "generated_by": {"name": "SMACC", "version": VERSION},
    }


def write_blind_config(config: BlindConfig, path: str | Path) -> None:
    """Write ``config`` to ``path`` as JSON."""
    Path(path).write_text(json.dumps(blind_payload(config), indent=2), encoding="utf-8")


def _str_tuple(payload: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(payload, list) or not all(isinstance(s, str) for s in payload):
        raise ValueError(f"{field_name!r} must be a list of strings")
    return tuple(payload)


def read_blind_config(path: str | Path) -> BlindConfig:
    """Read a blind config back, raising on a file that is not one.

    Raises:
        OSError: if the file can't be read.
        ValueError: on a wrong/missing ``kind`` or an unparseable field — better
            to refuse than to silently apply a half-understood blinding.
    """
    text = Path(path).read_text(encoding="utf-8-sig")  # tolerate a Notepad BOM
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Not valid JSON: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("kind") != KIND:
        raise ValueError(f"Not a SMACC blind config (kind={payload.get('kind')!r})")
    placeholder = payload.get("classify_placeholder", DEFAULT_PLACEHOLDER)
    if not isinstance(placeholder, str):
        raise ValueError("'classify_placeholder' must be a string")
    try:
        return BlindConfig(
            preset=str(payload.get("preset", PRESET_CUSTOM)),
            visible_labels=_str_tuple(
                payload.get("visible_labels", []), "visible_labels"
            ),
            signal_labels=_str_tuple(payload.get("signal_labels", []), "signal_labels"),
            palette=_str_tuple(payload.get("palette", []), "palette"),
            classify_placeholder=placeholder,
        )
    except ValueError as exc:
        raise ValueError(f"Invalid blind config: {exc}") from exc


def resolve_blind(spec: str) -> BlindConfig:
    """Resolve a ``--blind`` value: a built-in preset name, or a config file path.

    Raises:
        OSError: if a config-file path can't be read.
        ValueError: for an unknown preset or an invalid config file.
    """
    if spec in PRESET_NAMES:
        return preset_config(spec)
    return read_blind_config(spec)
