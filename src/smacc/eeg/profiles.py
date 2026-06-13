"""Saveable display ("view") profiles for the EEG Annotator (#177).

A view profile is a named, shareable *montage*: which channels to show and in
what order, the per-channel-type display filter and amplitude, and the
window/epoch lengths. It is a standalone JSON file — deliberately not stored
inside the recording or in the operator's preferences — so a montage can be
reused across nights and handed to a colleague.

The model carries no absolutes that are specific to one recording: channels are
named (resolved against whatever file is open, missing ones skipped), and the
epoch *anchor* is left out (it is a per-recording choice, unlike epoch length).

Pure dataclasses + JSON I/O, no GUI and no MNE — directly unit-testable, like
:mod:`smacc.eeg.annotations`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from ..config import VERSION
from .dsp import FilterSpec

# JSON envelope: a stable kind + schema version so a stray file is rejected
# rather than half-applied, and a future format change is detectable.
KIND = "smacc/eeg-view-profile"
SCHEMA_VERSION = 1

# Profiles live as standalone files; this suffix makes them recognizable and
# keeps the open/save dialogs filterable.
PROFILE_SUFFIX = ".smacc-view.json"
FILE_FILTER = "SMACC view profile (*.smacc-view.json);;All files (*)"


@dataclass(frozen=True)
class ViewProfile:
    """A reusable display montage for the trace view.

    ``channels`` is the ordered list of visible channel *names*; empty means
    "show all channels in file order". ``base_*`` apply to any channel type
    without an entry in the ``type_*`` overrides; ``type_*`` are keyed by MNE
    channel type ("eeg", "eog", "emg", …).
    """

    channels: tuple[str, ...] = ()
    base_scale_uv: float = 100.0
    type_scales: dict[str, float] = field(default_factory=dict)
    base_filter: FilterSpec = FilterSpec()
    type_filters: dict[str, FilterSpec] = field(default_factory=dict)
    window_seconds: float = 30.0
    epoch_seconds: float = 30.0


def _spec_to_dict(spec: FilterSpec) -> dict[str, float | None]:
    return {"highpass": spec.highpass, "lowpass": spec.lowpass, "notch": spec.notch}


def _spec_from_dict(payload: Any) -> FilterSpec:
    if not isinstance(payload, dict):
        raise ValueError(f"Filter must be an object, got {type(payload).__name__}")
    try:
        return FilterSpec(
            highpass=payload.get("highpass"),
            lowpass=payload.get("lowpass"),
            notch=payload.get("notch"),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid filter {payload!r}: {exc}") from exc


def profile_payload(profile: ViewProfile) -> dict[str, Any]:
    """Return the JSON-serializable envelope for ``profile``."""
    return {
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "channels": list(profile.channels),
        "base_scale_uv": profile.base_scale_uv,
        "type_scales": dict(profile.type_scales),
        "base_filter": _spec_to_dict(profile.base_filter),
        "type_filters": {
            ch_type: _spec_to_dict(spec)
            for ch_type, spec in profile.type_filters.items()
        },
        "window_seconds": profile.window_seconds,
        "epoch_seconds": profile.epoch_seconds,
        "generated_by": {"name": "SMACC", "version": VERSION},
    }


def write_view_profile(profile: ViewProfile, path: str | Path) -> None:
    """Write ``profile`` to ``path`` as JSON."""
    Path(path).write_text(
        json.dumps(profile_payload(profile), indent=2), encoding="utf-8"
    )


def read_view_profile(path: str | Path) -> ViewProfile:
    """Read a view profile back, raising on a file that is not one.

    Raises:
        OSError: if the file can't be read.
        ValueError: on a wrong/missing ``kind`` or an unparseable field — better
            to refuse than to silently apply a half-understood montage.
    """
    text = Path(path).read_text(encoding="utf-8-sig")  # tolerate a Notepad BOM
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Not valid JSON: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("kind") != KIND:
        raise ValueError(f"Not a SMACC view profile (kind={payload.get('kind')!r})")
    base = ViewProfile()
    channels = payload.get("channels", [])
    if not isinstance(channels, list) or not all(isinstance(c, str) for c in channels):
        raise ValueError("'channels' must be a list of channel names")
    type_scales = payload.get("type_scales", {})
    if not isinstance(type_scales, dict):
        raise ValueError("'type_scales' must be an object")
    type_filters_raw = payload.get("type_filters", {})
    if not isinstance(type_filters_raw, dict):
        raise ValueError("'type_filters' must be an object")
    return replace(
        base,
        channels=tuple(channels),
        base_scale_uv=float(payload.get("base_scale_uv", base.base_scale_uv)),
        type_scales={k: float(v) for k, v in type_scales.items()},
        base_filter=_spec_from_dict(payload.get("base_filter", {})),
        type_filters={k: _spec_from_dict(v) for k, v in type_filters_raw.items()},
        window_seconds=float(payload.get("window_seconds", base.window_seconds)),
        epoch_seconds=float(payload.get("epoch_seconds", base.epoch_seconds)),
    )
