"""Persist and restore operator/machine preferences as ``preferences.yaml``.

Preferences are the *operator/machine* layer — where each window last sat and the
launcher's recent-settings list — distinct from a portable study config
(:mod:`smacc.settings`, which now also carries the interface choices that used to
live here: always-on-top and the log-preview levels) and from a per-run session
record. They are auto-loaded at startup and saved on quit, and must never break the
app: a missing or corrupt file falls back to :data:`DEFAULTS`, and saving swallows
errors.

Window geometry is a *per-window* map (:data:`DEFAULTS` ``windows``) keyed by a
stable id (``"launcher"``, ``"main"``, the analyze window, each tool window), so
every window reopens where it was last left. A legacy single ``window`` block (the
old session-window-only geometry) is migrated into ``windows["main"]`` on load.
"""

from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any

import yaml

KIND = "smacc/preferences"
SCHEMA_VERSION = 1

# The stable id under which the old single-window geometry block is migrated into
# the per-window ``windows`` map (the main session window's geometry).
MAIN_WINDOW_ID = "main"

# Operator/machine preferences and their out-of-the-box values. Loading merges a
# file's keys over a copy of this, so older/partial files still yield every key.
DEFAULTS: dict[str, Any] = {
    # Per-window geometry, keyed by a stable window id (see MAIN_WINDOW_ID and the
    # window classes). Each entry is {x, y, w, h}; an absent/None x or y means
    # "no saved position yet" (open at a sensible default). Empty out of the box.
    "windows": {},
    "association_prompted": False,
    # Launcher state: recently used settings files (paths, most-recent first) and
    # the last one opened, so the launcher can preselect it and offer quick switching.
    "recent_settings": [],
    "last_settings": None,
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
        _migrate_legacy_window(prefs, stored)
    return prefs


def _migrate_legacy_window(prefs: dict[str, Any], stored: dict[str, Any]) -> None:
    """Fold a legacy single ``window`` block into ``windows[MAIN_WINDOW_ID]``.

    Older preference files stored only the session window's geometry under a flat
    ``window`` key. Map it onto the main window's entry in the per-window ``windows``
    map so an upgrading operator keeps their saved main-window position. An explicit
    ``windows`` entry already in the file wins (it is the newer shape).
    """
    legacy = stored.get("window")
    windows = prefs.get("windows")
    if not isinstance(windows, dict):
        windows = {}
        prefs["windows"] = windows
    if isinstance(legacy, dict) and MAIN_WINDOW_ID not in windows:
        windows[MAIN_WINDOW_ID] = legacy


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


def update_preferences(path: str | Path, changes: dict[str, Any]) -> None:
    """Merge ``changes`` into the saved preferences on disk (load → update → save).

    Lets independent writers — the launcher's recents and the session window's
    window geometry — each persist only their own keys without clobbering the
    other's. Best-effort like :func:`save_preferences`: it never raises.
    """
    prefs = load_preferences(path)
    prefs.update(changes)
    save_preferences(path, prefs)


def push_recent(recents: list[str], path: str, limit: int = 8) -> list[str]:
    """Return ``recents`` with ``path`` at the front, de-duplicated and capped.

    Most-recent first; an existing entry for the same path moves up rather than
    duplicating, and the list is trimmed to ``limit`` entries.
    """
    out = [path] + [p for p in recents if p != path]
    return out[:limit]


def window_geometry(prefs: dict[str, Any], window_id: str) -> dict[str, Any]:
    """Return the saved ``{x, y, w, h}`` geometry for ``window_id`` (``{}`` if none).

    A small accessor so window classes don't reach into the ``windows`` map shape
    themselves; an absent id or a malformed entry reads as an empty mapping (the
    caller then falls back to its default size/position).
    """
    windows = prefs.get("windows")
    if not isinstance(windows, dict):
        return {}
    geom = windows.get(window_id)
    return geom if isinstance(geom, dict) else {}


def update_window_geometry(
    path: str | Path, window_id: str, geometry: dict[str, Any]
) -> None:
    """Persist one window's geometry into the on-disk ``windows`` map (merge, never clobber).

    Each window saves only its own entry on close, so several windows can record
    their geometry in the same file without overwriting each other (or the launcher's
    recent-settings list). Best-effort like :func:`update_preferences`: never raises.
    """
    prefs = load_preferences(path)
    windows = prefs.get("windows")
    if not isinstance(windows, dict):
        windows = {}
    windows[window_id] = geometry
    update_preferences(path, {"windows": windows})


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
