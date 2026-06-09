"""The configurable event-marker registry: codes, labels, and per-event routing.

SMACC marks experiment events (a cue played, a dream report, observed REM, …) by
pushing a numeric *portcode* to its marker stream and writing a matching log line.
Those codes used to live as hardcoded dicts in :mod:`smacc.config`; this module
makes them a single editable registry a study can tune, persist in its ``.smacc``
file, and recover from any session log.

Each :class:`EventDef` carries:

* ``code`` — the 8-bit portcode (``1..255``) sent on a trigger.
* ``trigger`` — whether to push the code to the marker stream.
* ``preview`` — whether the event shows in the live log preview. Everything is
  written to the session log file regardless; this flag only gates the on-screen
  viewer.
* ``category`` — ``"manual"`` (the auto-built event-grid buttons), ``"control"``
  (panel/lightswitch driven), or ``"system"`` (startup/init; not shown in the grid).
* ``increment`` — when set, successive firings use an increasing code (``code``,
  ``code + 1``, …) so each occurrence is individually findable in the trigger
  channel (e.g. the dream-report start).

Pure data and helpers, no Qt — directly unit-testable.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, fields, replace
from typing import Any

# 8-bit parallel/serial trigger byte: the universally safe portcode range.
CODE_MIN = 1
CODE_MAX = 255
# Default soft ceiling; a study can lower it to match older trigger hardware.
DEFAULT_SAFE_MAX = 255


@dataclass
class EventDef:
    """One marker event: its code, label, routing flags, and category."""

    key: str
    label: str
    code: int
    trigger: bool = True
    preview: bool = True
    category: str = "control"
    tooltip: str = ""
    increment: bool = False
    builtin: bool = True  # False for user-added custom events


# The fields a study may override (keyed by ``key``); labels/tooltips/categories
# stay app-defined so improvements to them reach old studies on load.
_PERSIST_FIELDS = ("key", "code", "trigger", "preview", "increment")
_FIELD_NAMES = {f.name for f in fields(EventDef)}


def default_events() -> list[EventDef]:
    """Return a fresh copy of the built-in event definitions (safe to mutate).

    Dream-report *starts* occupy a reserved 201+ band (they increment), so the
    other control codes sit in a compact low band that leaves that band clear.
    """
    return [
        # --- Manual / observational: the auto-built event-grid buttons --------
        EventDef(
            "RecordingStarted",
            "Start recording",
            51,
            category="manual",
            tooltip=(
                "Mark the start of the EEG recording; sets the reference clock "
                "for dream-report timestamps"
            ),
        ),
        EventDef(
            "TLRTrainingStart",
            "TLR training start",
            43,
            category="manual",
            tooltip="Mark the start of Targeted Lucidity Reactivation training",
        ),
        EventDef(
            "TLRTrainingEnd",
            "TLR training end",
            44,
            category="manual",
            tooltip="Mark the end of Targeted Lucidity Reactivation training",
        ),
        EventDef(
            "TechInRoom",
            "Tech in room",
            42,
            category="manual",
            tooltip="Mark the entry of an experimenter/technician in the bedroom",
        ),
        EventDef(
            "SleepOnset",
            "Sleep onset",
            46,
            category="manual",
            tooltip="Mark observed sleep onset",
        ),
        EventDef(
            "REMDetected",
            "REM detected",
            41,
            category="manual",
            tooltip="Mark observed REM",
        ),
        EventDef(
            "LRLRDetected",
            "LRLR detected",
            45,
            category="manual",
            tooltip="Mark an observed left-right-left-right lucid signal",
        ),
        EventDef(
            "Clapper",
            "Clapper",
            49,
            category="manual",
            tooltip="Synchronize a marker with EEG",
        ),
        EventDef(
            "Note",
            "Note",
            50,
            category="manual",
            tooltip="Mark a note and enter free text",
        ),
        # --- Lights: driven by the lightswitch toggle, not the grid -----------
        EventDef("LightsOff", "Lights off", 47),
        EventDef("LightsOn", "Lights on", 48),
        # --- Control: panel-driven --------------------------------------------
        EventDef("CueStarted", "Cue started", 60),
        EventDef("CueStopped", "Cue stopped", 61),
        EventDef("NoiseStarted", "Noise started", 62),
        EventDef("NoiseStopped", "Noise stopped", 63),
        EventDef("IntercomStarted", "Intercom started", 64),
        EventDef("IntercomStopped", "Intercom stopped", 65),
        EventDef("VisualStarted", "Visual stimulation", 66),
        EventDef("SurveyOpened", "Survey opened", 67),
        # --- System -----------------------------------------------------------
        EventDef(
            "TriggerInitialization",
            "SMACC initialized",
            100,
            trigger=False,
            preview=False,
            category="system",
            tooltip="Optional connection-test marker sent once at startup",
        ),
        # --- Dream reports: the start increments so each report is unique ------
        EventDef("DreamReportStopped", "Dream report stopped", 200),
        EventDef("DreamReportStarted", "Dream report started", 201, increment=True),
    ]


def events_to_list(events: Iterable[EventDef]) -> list[dict[str, Any]]:
    """Serialize the registry for a study file.

    A built-in event persists only the editable subset (code + routing flags,
    keyed by ``key``), so the ``.smacc`` stays readable and label/tooltip
    improvements reach old studies. A custom (user-added) event persists its full
    definition so it can be reconstructed on load.
    """
    out: list[dict[str, Any]] = []
    for e in events:
        if e.builtin:
            out.append({name: getattr(e, name) for name in _PERSIST_FIELDS})
        else:
            out.append(
                {
                    "key": e.key,
                    "label": e.label,
                    "code": e.code,
                    "trigger": e.trigger,
                    "preview": e.preview,
                    "category": e.category,
                    "tooltip": e.tooltip,
                    "increment": e.increment,
                    "builtin": False,
                }
            )
    return out


# A built-in entry only ever overrides these (its label/category/tooltip stay
# app-defined); a hand-edited file can't rewrite them onto a built-in.
_BUILTIN_OVERRIDE_FIELDS = ("code", "trigger", "preview", "increment")


def _builtin_overrides(item: dict) -> dict[str, Any]:
    """Coerce the overridable fields from a saved built-in entry."""
    out: dict[str, Any] = {}
    for name in _BUILTIN_OVERRIDE_FIELDS:
        if name not in item:
            continue
        value = item[name]
        if name == "code":
            try:
                value = int(value)
            except (TypeError, ValueError):
                continue
        else:
            value = bool(value)
        out[name] = value
    return out


def _custom_from_dict(key: str, item: dict) -> EventDef | None:
    """Reconstruct a custom EventDef from a saved full definition (or None)."""
    try:
        code = int(item["code"])
    except (TypeError, ValueError, KeyError):
        return None
    return EventDef(
        key=key,
        label=str(item.get("label") or key),
        code=code,
        trigger=bool(item.get("trigger", True)),
        preview=bool(item.get("preview", True)),
        category=str(item.get("category") or "manual"),
        tooltip=str(item.get("tooltip") or ""),
        increment=bool(item.get("increment", False)),
        builtin=False,
    )


def merge_event_codes(loaded: Any) -> list[EventDef]:
    """Return the default registry with saved overrides + custom events applied.

    Mirrors the merge-over-DEFAULTS approach in :mod:`smacc.preferences`: a study
    with no ``event_codes`` yields the full defaults; a study that overrides only a
    few built-in codes keeps the rest; saved custom events (``builtin: false``) are
    appended after the built-ins. Default ordering is preserved.
    """
    defaults = {e.key: e for e in default_events()}
    custom: list[EventDef] = []
    seen_custom: set[str] = set()
    if isinstance(loaded, list):
        for item in loaded:
            if not isinstance(item, dict):
                continue
            key = item.get("key")
            if not isinstance(key, str):
                continue
            if key in defaults:
                defaults[key] = replace(defaults[key], **_builtin_overrides(item))
            elif item.get("builtin") is False and key not in seen_custom:
                event = _custom_from_dict(key, item)
                if event is not None:
                    custom.append(event)
                    seen_custom.add(key)
    return list(defaults.values()) + custom


def make_custom_event(
    label: str,
    code: int,
    existing_keys: Iterable[str],
    *,
    tooltip: str = "",
    increment: bool = False,
    trigger: bool = True,
    preview: bool = True,
) -> EventDef:
    """Build a custom (button) event with a unique key derived from ``label``."""
    base = "custom" + (re.sub(r"[^A-Za-z0-9]+", "", label.title()) or "Event")
    existing = set(existing_keys)
    key = base
    suffix = 2
    while key in existing:
        key = f"{base}{suffix}"
        suffix += 1
    return EventDef(
        key=key,
        label=label,
        code=code,
        trigger=trigger,
        preview=preview,
        category="manual",
        tooltip=tooltip,
        increment=increment,
        builtin=False,
    )


def validate_events(
    events: Iterable[EventDef], safe_max: int = DEFAULT_SAFE_MAX
) -> tuple[list[str], list[str]]:
    """Return ``(errors, warnings)`` for a registry.

    Hard errors (block saving): a code outside ``1..255``, a duplicate code among
    *triggerable* events (they would collide on the marker channel), or a
    duplicate key. Soft warnings (allowed, but surfaced): a code above
    ``safe_max`` (older hardware), or an incrementing event whose band
    (``code..255``) overlaps another triggerable code.
    """
    events = list(events)
    errors: list[str] = []
    warnings: list[str] = []
    seen_keys: set[str] = set()
    trig_codes: dict[int, str] = {}  # code -> label, for triggerable events only
    for e in events:
        if e.key in seen_keys:
            errors.append(f"Duplicate event key {e.key!r}.")
        seen_keys.add(e.key)
        if not (e.label and str(e.label).strip()):
            errors.append(f"Event {e.key!r}: a label is required.")
        if isinstance(e.code, bool) or not isinstance(e.code, int):
            errors.append(f"{e.label}: code must be a whole number.")
            continue
        if not (CODE_MIN <= e.code <= CODE_MAX):
            errors.append(f"{e.label}: code {e.code} is outside {CODE_MIN}–{CODE_MAX}.")
            continue
        if e.code > safe_max:
            warnings.append(
                f"{e.label}: code {e.code} is above the safe max {safe_max}."
            )
        if e.trigger:
            if e.code in trig_codes:
                errors.append(
                    f"{e.label}: code {e.code} duplicates {trig_codes[e.code]!r}."
                )
            else:
                trig_codes[e.code] = e.label
    for e in events:
        if (
            e.increment
            and e.trigger
            and isinstance(e.code, int)
            and not isinstance(e.code, bool)
        ):
            for code, label in trig_codes.items():
                if label != e.label and e.code <= code <= CODE_MAX:
                    warnings.append(
                        f"{e.label}: incrementing codes {e.code}–{CODE_MAX} "
                        f"overlap {label!r} (code {code})."
                    )
    return errors, warnings


def runtime_code(event: EventDef, ordinal: int | None = None) -> int:
    """Return the code to send for this firing.

    For an incrementing event the 1-based ``ordinal`` shifts the code: ``code``
    for the 1st firing, ``code + 1`` for the 2nd, … clamped to ``255`` so SMACC
    never emits an out-of-range byte. Non-incrementing events ignore ``ordinal``.
    """
    if event.increment and ordinal and ordinal > 1:
        return min(event.code + (ordinal - 1), CODE_MAX)
    return event.code
