"""The configurable event-marker registry: codes, labels, and per-event routing.

SMACC marks experiment events (a cue played, a dream report, observed REM, …) by
pushing a numeric *portcode* to its marker stream and writing a matching log line.
Those codes used to live as hardcoded dicts in :mod:`smacc.config`; this module
makes them a single editable registry a study can tune, persist in its ``.smacc``
file, and recover from any session log.

Each :class:`EventDef` carries:

* ``code`` — the 8-bit portcode (``1..255``) sent on a trigger.
* ``trigger`` — whether to push the code to the marker stream.
* ``log`` — whether to write a log line. A *triggered* event is always logged (a
  sent marker must stay traceable), so this flag only matters when ``trigger`` is
  off.
* ``category`` — ``"manual"`` (the auto-built event-grid buttons), ``"control"``
  (panel/lightswitch driven), or ``"system"`` (startup/init; not shown in the grid).
* ``increment`` — when set (the dream-report start), successive firings use an
  increasing code (``code``, ``code + 1``, …) so each report is individually
  findable in the trigger channel.

Pure data and helpers, no Qt — directly unit-testable.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, fields, replace
from typing import Any

# 8-bit parallel/serial trigger byte: the universally safe portcode range.
CODE_MIN = 1
CODE_MAX = 255
# Default soft ceiling; a study can lower it to match older trigger hardware.
DEFAULT_SAFE_MAX = 255

# Only these events meaningfully take an ``ordinal`` at emit time, so only they
# expose the "increment" toggle in the editor.
INCREMENTABLE_KEYS = frozenset({"DreamReportStarted"})


@dataclass
class EventDef:
    """One marker event: its code, label, routing flags, and category."""

    key: str
    label: str
    code: int
    trigger: bool = True
    log: bool = True
    category: str = "control"
    tooltip: str = ""
    increment: bool = False


# The fields a study may override (keyed by ``key``); labels/tooltips/categories
# stay app-defined so improvements to them reach old studies on load.
_PERSIST_FIELDS = ("key", "code", "trigger", "log", "increment")
_FIELD_NAMES = {f.name for f in fields(EventDef)}


def default_events() -> list[EventDef]:
    """Return a fresh copy of the built-in event definitions (safe to mutate).

    Dream-report *starts* occupy a reserved 201+ band (they increment), so the
    other control codes sit in a compact low band that leaves that band clear.
    """
    return [
        # --- Manual / observational: the auto-built event-grid buttons --------
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
            log=False,
            category="system",
            tooltip="Optional connection-test marker sent once at startup",
        ),
        # --- Dream reports: the start increments so each report is unique ------
        EventDef("DreamReportStopped", "Dream report stopped", 200),
        EventDef("DreamReportStarted", "Dream report started", 201, increment=True),
    ]


def events_to_list(events: Iterable[EventDef]) -> list[dict[str, Any]]:
    """Serialize to the compact, user-editable subset persisted in a study file.

    Only the fields a study can change (the code and routing flags, keyed by
    ``key``) are written, so the ``.smacc`` stays readable and label/tooltip
    improvements apply to old studies automatically.
    """
    return [{name: getattr(e, name) for name in _PERSIST_FIELDS} for e in events]


def merge_event_codes(loaded: Any) -> list[EventDef]:
    """Return the default registry with any saved per-event overrides applied.

    Mirrors the merge-over-DEFAULTS approach in :mod:`smacc.preferences`: a study
    with no ``event_codes`` (older schema) yields the full defaults, and a study
    that overrides only a few codes keeps the rest. Saved entries for keys SMACC
    no longer defines are ignored; default ordering is preserved.
    """
    defaults = {e.key: e for e in default_events()}
    if isinstance(loaded, list):
        for item in loaded:
            if not isinstance(item, dict):
                continue
            key = item.get("key")
            if key not in defaults:
                continue
            overrides: dict[str, Any] = {}
            for name, value in item.items():
                if name == "key" or name not in _FIELD_NAMES:
                    continue
                if name == "code":
                    try:
                        value = int(value)
                    except (TypeError, ValueError):
                        continue
                elif name in ("trigger", "log", "increment"):
                    value = bool(value)
                overrides[name] = value
            defaults[key] = replace(defaults[key], **overrides)
    return list(defaults.values())


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
