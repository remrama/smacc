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
every window reopens where it was last left.
"""

from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any

import yaml

KIND = "smacc/preferences"
SCHEMA_VERSION = 1

# The stable id of the main session window's geometry within the per-window
# ``windows`` map.
MAIN_WINDOW_ID = "main"

# Operator/machine preferences and their out-of-the-box values. Loading merges a
# file's keys over a copy of this, so older/partial files still yield every key.
DEFAULTS: dict[str, Any] = {
    # Per-window geometry, keyed by a stable window id (see MAIN_WINDOW_ID and the
    # window classes). Each entry is {x, y, w, h}; an absent/None x or y means
    # "no saved position yet" (open at a sensible default). Empty out of the box.
    "windows": {},
    # Launcher state: recently used settings files (paths, most-recent first) and
    # the last one opened, so the launcher can preselect it and offer quick switching.
    "recent_settings": [],
    "last_settings": None,
    # How many lines the Session window's live log preview keeps (oldest dropped
    # first; the log file always keeps everything). Large values cost GUI memory
    # and repaint time over an overnight session.
    "log_preview_max_lines": 1000,
    # EEG review tool (#136): recently used annotation labels (most-recent
    # first, seeding the label dialog's dropdown) and the last folder a
    # recording was opened from. Note loading only round-trips keys present
    # here, so the EEG window's keys must stay in DEFAULTS even though the
    # tool is an optional component.
    "eeg_recent_labels": [],
    "eeg_last_dir": None,
}

_logger = logging.getLogger("smacc")


def default_preferences() -> dict[str, Any]:
    """Return a fresh deep copy of :data:`DEFAULTS` (safe to mutate)."""
    return copy.deepcopy(DEFAULTS)


def load_preferences(path: str | Path) -> dict[str, Any]:
    """Return preferences merged over the defaults; never raises.

    A missing, unreadable, unparseable, or non-preferences file yields a full copy
    of :data:`DEFAULTS`. A valid file's keys are merged on top, so a partial file
    still provides every key.
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


def log_preview_max_lines(prefs: dict[str, Any]) -> int:
    """Return the log-preview line cap (a positive int), else the default.

    A hand-edited ``preferences.yaml`` may carry anything here; garbage or a
    non-positive value falls back to the default rather than breaking the window.
    """
    value = prefs.get("log_preview_max_lines")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return int(DEFAULTS["log_preview_max_lines"])
    return value


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
