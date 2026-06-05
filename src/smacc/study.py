"""Persist and restore study configuration as ``study.json`` bundles.

A study bundle lets a researcher configure SMACC once (cue sound, volumes, noise
color, BlinkStick color/length, survey presets) and reload it each session so the
setup stays consistent across nights and researchers. Audio *device* selection is
intentionally excluded for now (only the noise device routes today); device
persistence will follow once real per-device routing lands.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Bump when the serialized layout changes incompatibly.
SCHEMA_VERSION = 1


def save_study(path: str | Path, state: dict[str, Any]) -> None:
    """Write study ``state`` to ``path`` as JSON, tagged with the schema version."""
    payload = {"schema_version": SCHEMA_VERSION, "state": state}
    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_study(path: str | Path) -> dict[str, Any]:
    """Load and return study state from ``path``.

    Raises:
        ValueError: if the file is malformed or its schema version is unsupported.
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Malformed study file: expected a JSON object.")
    version = payload.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported study schema version {version!r} (expected {SCHEMA_VERSION})."
        )
    state = payload.get("state")
    if not isinstance(state, dict):
        raise ValueError("Malformed study file: missing 'state' object.")
    return state
