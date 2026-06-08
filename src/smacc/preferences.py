"""Persist and restore operator/machine preferences as ``preferences.yaml``.

Preferences are the *operator/machine* layer — window geometry, theme, always-on-top,
which log levels show in the preview pane — distinct from a portable study config
(:mod:`smacc.settings`) and from a per-run session record. They are auto-loaded at
startup and saved on quit, and must never break the app: a missing or corrupt file
falls back to :data:`DEFAULTS`, and saving swallows errors.
"""

from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any

import yaml

KIND = "smacc/preferences"
SCHEMA_VERSION = 1

# Operator/machine preferences and their out-of-the-box values. Loading merges a
# file's keys over a copy of this, so older/partial files still yield every key.
DEFAULTS: dict[str, Any] = {
    "always_on_top": False,
    "lights_on": True,
    "preview_levels": ["INFO", "WARNING", "ERROR", "CRITICAL"],  # names, not ints
    "window": {"x": None, "y": None, "w": 640, "h": 560},
    "association_prompted": False,
}

_logger = logging.getLogger("smacc")


def default_preferences() -> dict[str, Any]:
    """Return a fresh deep copy of :data:`DEFAULTS` (safe to mutate)."""
    return copy.deepcopy(DEFAULTS)


def load_preferences(path: str | Path) -> dict[str, Any]:
    """Return preferences merged over the defaults; never raises.

    A missing, unreadable, unparseable, or non-preferences file yields a full copy
    of :data:`DEFAULTS`. A valid file's keys are merged on top, so a file written
    by an older schema still provides every key.
    """
    prefs = default_preferences()
    try:
        text = Path(path).read_text(encoding="utf-8")
        payload = yaml.safe_load(text)
    except (OSError, yaml.YAMLError):
        return prefs
    if not isinstance(payload, dict) or payload.get("kind") != KIND:
        return prefs
    stored = payload.get("preferences")
    if isinstance(stored, dict):
        for key in prefs:
            if key in stored:
                prefs[key] = stored[key]
    return prefs


def save_preferences(path: str | Path, prefs: dict[str, Any]) -> None:
    """Best-effort write of ``prefs`` to ``path``; never raises (logs on failure).

    Called at quit, where a write failure must not block shutdown.
    """
    payload = {"kind": KIND, "schema_version": SCHEMA_VERSION, "preferences": prefs}
    try:
        text = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
        Path(path).write_text(text, encoding="utf-8")
    except (OSError, yaml.YAMLError):
        _logger.exception("Could not save preferences")


def levels_to_names(levels: set[int]) -> list[str]:
    """Convert ``logging`` level ints to level-name strings (sorted by severity)."""
    return [logging.getLevelName(level) for level in sorted(levels)]


def names_to_levels(names: list[str]) -> set[int]:
    """Convert level-name strings to a set of ``logging`` level ints (unknowns dropped)."""
    out: set[int] = set()
    for name in names:
        value = logging.getLevelName(name)  # name -> int, or "Level X" if unknown
        if isinstance(value, int):
            out.add(value)
    return out
