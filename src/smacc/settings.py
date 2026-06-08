"""Persist and restore SMACC settings as a single ``.yaml`` file.

A settings file lets a researcher configure SMACC once (cue sounds, volumes, noise
color, BlinkStick color/length, survey presets) and reload it each session so the
setup stays consistent across nights and researchers. It carries optional metadata
(subject/session/notes) and is tagged with a ``kind`` discriminator so SMACC can
reject YAML that wasn't written by it.

The on-disk shape::

    kind: smacc/settings
    schema_version: 3
    smacc_version: "0.0.7"
    metadata: {subject: "", session: "", notes: "", created: "..."}
    settings: { ...the panel state from SmaccWindow.gather_settings()... }

Loading also accepts the legacy ``study.json`` shape (``{"schema_version", "state"}``)
since YAML is a superset of JSON; panels handle field-level back-compat.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .config import VERSION

# The discriminator written at the top of every settings file. A loaded mapping
# is rejected when it carries a different ``kind`` (legacy files have none).
KIND = "smacc/settings"

# Bump when the serialized layout changes incompatibly. Files written by older
# (lower) versions are still accepted on load; panels handle field-level
# back-compat (e.g. a v1 single cue maps into the first multi-slot cue).
SCHEMA_VERSION = 3


def build_payload(settings: dict[str, Any], metadata: dict) -> dict[str, Any]:
    """Wrap ``settings`` + ``metadata`` in the tagged, versioned payload mapping.

    Shared by file export and the log front-matter block so both write the same
    structure (and both round-trip through :func:`parse_settings_mapping`).
    """
    return {
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "smacc_version": VERSION,
        "metadata": metadata,
        "settings": settings,
    }


def save_settings(path: str | Path, settings: dict[str, Any], metadata: dict) -> None:
    """Write ``settings`` (+ ``metadata``) to ``path`` as a SMACC settings YAML.

    Raises:
        ValueError: if the payload can't be serialized to YAML.
        OSError: if the file can't be written.
    """
    payload = build_payload(settings, metadata)
    try:
        text = yaml.safe_dump(
            payload, sort_keys=False, default_flow_style=False, allow_unicode=True
        )
    except yaml.YAMLError as exc:
        raise ValueError(f"Could not serialize settings to YAML: {exc}") from exc
    Path(path).write_text(text, encoding="utf-8")


def parse_settings_mapping(payload: Any) -> tuple[dict, dict]:
    """Validate a loaded settings mapping and return ``(settings, metadata)``.

    Shared by file loading and log-block extraction so both go through the same
    checks. Accepts the current ``settings`` key and the legacy ``state`` key.

    Raises:
        ValueError: if ``payload`` isn't a compatible SMACC settings mapping.
    """
    if not isinstance(payload, dict):
        raise ValueError("Not a compatible SMACC settings file (expected a mapping).")
    kind = payload.get("kind")
    if kind is not None and kind != KIND:
        raise ValueError(f"Not a compatible SMACC settings file (kind={kind!r}).")
    version = payload.get("schema_version")
    # Accept any known (current-or-older) version; panels migrate field shapes.
    if isinstance(version, bool) or not isinstance(version, int):
        raise ValueError(f"Unsupported settings schema version {version!r}.")
    if not (1 <= version <= SCHEMA_VERSION):
        raise ValueError(
            f"Unsupported settings schema version {version!r} "
            f"(expected 1..{SCHEMA_VERSION})."
        )
    # New files nest under "settings"; legacy study.json used "state".
    settings = payload.get("settings")
    if settings is None:
        settings = payload.get("state")
    if not isinstance(settings, dict):
        raise ValueError("Malformed settings file: missing 'settings' mapping.")
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    return settings, metadata


def load_settings(path: str | Path) -> tuple[dict, dict]:
    """Load a settings file and return ``(settings, metadata)``.

    Raises:
        ValueError: if the file is empty, unparseable, or not a compatible
            SMACC settings file.
        OSError: if the file can't be read.
    """
    text = Path(path).read_text(encoding="utf-8")
    try:
        payload = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"Could not parse YAML: {exc}") from exc
    if payload is None:
        raise ValueError("Empty file; not a compatible SMACC settings file.")
    return parse_settings_mapping(payload)
