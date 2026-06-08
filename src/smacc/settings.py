"""Persist and restore a SMACC study config as a single ``.smacc`` file (YAML).

A study file lets a researcher configure SMACC once (cue sounds, volumes, noise
color, BlinkStick color/length, survey presets) and reload it each session so the
setup stays consistent across nights and researchers. It carries optional metadata
(subject/session/notes) and is tagged with a ``kind`` discriminator so SMACC can
reject YAML that wasn't written by it.

The on-disk shape (a ``.smacc`` file is YAML text with a leading comment header)::

    kind: smacc/settings
    schema_version: 4
    smacc_version: "0.0.7"
    metadata: {subject: "", session: "", notes: "", created: "..."}
    settings: { ...the panel state from SmaccWindow.gather_settings()... }

Referenced media (cue/noise WAVs) are stored *relative* to the file when they sit
beside it and *absolute* otherwise, so a study folder is portable as-is; see
:func:`relativize_paths` / :func:`resolve_paths`. The user-facing extension is
``.smacc`` but the ``kind`` discriminator stays ``smacc/settings`` (it is embedded
verbatim in every log's settings block).
"""

from __future__ import annotations

import copy
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml

from .config import VERSION

# The discriminator written at the top of every settings file. A loaded mapping
# is rejected when it carries a different ``kind``.
KIND = "smacc/settings"

# Prepended to every saved file so it self-identifies even before parsing (YAML
# ignores ``#`` comments, so this round-trips cleanly through ``safe_load``).
_FILE_HEADER = "# SMACC study config — YAML (.smacc). Edit with care.\n"

# Bump when the serialized layout changes incompatibly. Files written by older
# (lower) versions are still accepted on load; panels handle field-level
# back-compat (e.g. a v1 single cue maps into the first multi-slot cue, and a
# pre-v4 file with no event_codes falls back to the default registry).
SCHEMA_VERSION = 4


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
    Path(path).write_text(_FILE_HEADER + text, encoding="utf-8")


def parse_settings_mapping(payload: Any) -> tuple[dict, dict]:
    """Validate a loaded settings mapping and return ``(settings, metadata)``.

    Shared by file loading and log-block extraction so both go through the same
    checks.

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
    settings = payload.get("settings")
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


def _iter_path_slots(settings: dict) -> Iterator[tuple[dict, str]]:
    """Yield ``(container, key)`` for each media-path slot present in ``settings``.

    The one place that knows the panel schema's path-bearing keys, so portability
    rewriting stays out of the panels and out of the path-agnostic save/load core.
    """
    cues = settings.get("cues")
    if isinstance(cues, list):
        for cue in cues:
            if isinstance(cue, dict) and "file" in cue:
                yield cue, "file"
    if "noise_file" in settings:
        yield settings, "noise_file"


def relativize_paths(settings: dict, base_dir: str | Path) -> dict:
    """Return a deep copy of ``settings`` with media paths made portable.

    A referenced WAV under ``base_dir`` is stored relative to it (POSIX
    separators) so a study file shared alongside its audio stays valid; anything
    else is stored as a normalized absolute path. Empty slots are left untouched.
    """
    out = copy.deepcopy(settings)
    base = Path(base_dir).resolve()
    for container, key in _iter_path_slots(out):
        raw = container[key]
        if not raw:  # "" / None: skip before constructing Path (Path("") == ".")
            continue
        try:
            absolute = Path(raw).resolve()
        except OSError:
            continue  # leave an unresolvable path verbatim
        if absolute.is_relative_to(base):
            container[key] = absolute.relative_to(base).as_posix()
        else:
            container[key] = os.fspath(absolute)
    return out


def resolve_paths(settings: dict, base_dir: str | Path) -> dict:
    """Return a deep copy of ``settings`` with relative media paths resolved.

    Relative paths are resolved against ``base_dir`` (the loaded file's folder);
    absolute paths are kept as-is. The inverse of :func:`relativize_paths`.
    """
    out = copy.deepcopy(settings)
    base = Path(base_dir).resolve()
    for container, key in _iter_path_slots(out):
        raw = container[key]
        if not raw:
            continue
        path = Path(raw)
        if not path.is_absolute():
            container[key] = os.fspath((base / path).resolve())
    return out
