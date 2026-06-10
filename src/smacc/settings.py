"""Persist and restore a SMACC study config as a single ``.smacc`` file (YAML).

A study file lets a researcher configure SMACC once (cue sounds, volumes, noise
color, visual cues, survey presets) and reload it each session so the setup stays
consistent across nights and researchers. It carries optional metadata
(subject/session/notes) and is tagged with a ``kind`` discriminator so SMACC can
reject YAML that wasn't written by it.

The on-disk shape (a ``.smacc`` file is YAML text with a leading comment header)::

    kind: smacc/settings
    schema_version: 2
    smacc_version: "0.0.7"
    metadata: {subject: "", session: "", notes: "", created: "..."}
    settings: { ...the panel state from SmaccWindow.gather_settings()... }

The ``settings`` mapping carries, besides each panel's state, a few window-level
blocks: ``devices`` (role/routing config), ``event_codes`` + ``event_code_safe_max``
(the marker registry), ``trigger_output`` (the optional hardware-trigger config; see
:mod:`smacc.triggers`), ``data_directory``, and the interface choices ``preview_levels``
(the live-log levels), ``always_on_top`` (the main window's), and ``tool_always_on_top``
(a per-tool map).

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
_FILE_HEADER = "# SMACC settings — YAML (.smacc). Edit with care.\n"

# v1 was the first stable on-disk schema; v2 reshaped the single visual cue
# (``blink_color``/``blink_length``) into the multi-slot ``visual_cues`` list.
# Bump this when the layout changes incompatibly — and when you do, extend
# :func:`_migrate_settings` plus the version-history table in
# docs/reference/settings-file.md. A file carrying a higher or otherwise-unknown
# version is rejected on load. Missing *optional* keys are not a version concern:
# each panel/sub-block fills its own default, so a partial or hand-edited file
# still loads.
SCHEMA_VERSION = 2


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
    # Versions 1..current are accepted; older shapes are upgraded on the way in.
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
    return _migrate_settings(settings, version), metadata


def _migrate_settings(settings: dict, version: int) -> dict:
    """Upgrade an older-schema ``settings`` mapping to the current shape, in place.

    v1 -> v2: the single visual cue (``blink_color``/``blink_length``) became the
    multi-slot ``visual_cues`` list; a v1 file's blink keys load into the first
    slot (panels only ever see the current shape).
    """
    if version < 2:
        color = settings.pop("blink_color", None)
        length = settings.pop("blink_length", None)
        if "visual_cues" not in settings and (color is not None or length is not None):
            slot: dict[str, Any] = {"name": "Light 1"}
            if color is not None:
                slot["color"] = color
            if length is not None:
                slot["length"] = length
            settings["visual_cues"] = [slot]
    return settings


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
    """Yield ``(container, key)`` for each path slot present in ``settings``.

    The one place that knows the schema's path-bearing keys (cue/noise files and the
    data directory), so portability rewriting stays out of the panels and out of the
    path-agnostic save/load core.
    """
    cues = settings.get("cues")
    if isinstance(cues, list):
        for cue in cues:
            if isinstance(cue, dict) and "file" in cue:
                yield cue, "file"
    if "noise_file" in settings:
        yield settings, "noise_file"
    # The data directory (where runs from this settings file are written) is stored
    # relative to the .smacc when it sits alongside it, so a self-contained folder
    # stays portable; absolute when it points elsewhere (e.g. a shared lab drive).
    if "data_directory" in settings:
        yield settings, "data_directory"


def data_directory_of(
    settings: dict, base_dir: str | Path, default: str | Path
) -> Path:
    """Return the data directory a settings mapping points at, resolved to absolute.

    A relative ``data_directory`` resolves against ``base_dir`` (the .smacc's folder);
    an absolute one is kept; a missing/blank one falls back to ``default``.
    """
    raw = settings.get("data_directory")
    if not raw:
        return Path(default)
    path = Path(raw)
    return path if path.is_absolute() else (Path(base_dir) / path).resolve()


def load_data_directory(path: str | Path, default: str | Path) -> Path:
    """Resolve the data directory of the settings file at ``path`` (``default`` on error)."""
    try:
        state, _ = load_settings(path)
    except (OSError, ValueError):
        return Path(default)
    return data_directory_of(state, Path(path).parent, default)


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
