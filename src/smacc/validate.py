"""The headless ``SMACC validate <file>`` command (#302).

Checks a ``.smacc`` file without opening any window — for a power user who edits the
YAML by hand, or for CI on a study repository. It reports **graded** issues and exits
non-zero only when there are hard errors:

* **structural** — the file parses as a SMACC settings file (``kind`` / schema
  version / shape), via :func:`smacc.settings.load_settings`;
* **schema** — the settings conform to the model-derived JSON Schema (types, enums,
  ranges, unknown-key typos), when :mod:`jsonschema` is available (it is in a normal
  install; the command degrades to the checks below if a build lacks it);
* **registry** — the safety-critical event-code checks from the model's own
  :func:`smacc.events.validate_events` (duplicate/out-of-range codes are errors; a
  TTL code above the safe max is a warning).

Pure and Qt-free: dispatched from ``smacc.__main__`` before any QApplication.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from . import events, settings
from .studyconfig import StudyConfig


def _schema_issues(state: dict) -> list[str]:
    """Schema-validation messages for the settings mapping (``[]`` if unavailable).

    Optional by design: if :mod:`jsonschema` (or its native ``rpds`` backend) isn't
    importable in this build, schema checks are skipped and the structural/registry
    checks still run. Editors get the same validation from the published schema.
    """
    try:
        import jsonschema

        from .schema import build_schema

        settings_schema = build_schema()["properties"]["settings"]
        validator = jsonschema.Draft202012Validator(settings_schema)
        errors = sorted(validator.iter_errors(state), key=lambda e: list(e.path))
    except Exception:
        # jsonschema (or its native rpds/specifications data) absent or unusable in
        # this build: skip schema checks; the structural/registry checks still run.
        return []
    return [
        f"{'.'.join(str(p) for p in e.path) or 'settings'}: {e.message}" for e in errors
    ]


def validate_file(path: str | Path) -> tuple[list[str], list[str]]:
    """Return ``(errors, warnings)`` for the ``.smacc`` file at ``path``.

    A structural failure is fatal and returned on its own — the later checks need a
    parsed mapping. Schema violations are errors (the file doesn't match the model's
    shape); the registry's soft checks contribute warnings.
    """
    try:
        state, _metadata = settings.load_settings(path)
    except (OSError, ValueError) as exc:
        return [str(exc)], []

    errors = _schema_issues(state)
    config = StudyConfig.from_settings_dict(state)
    registry_errors, registry_warnings = events.validate_events(
        config.markers.event_codes, config.markers.event_code_safe_max
    )
    errors.extend(registry_errors)
    return errors, registry_warnings


def main(argv: list[str] | None = None) -> int:
    """``SMACC validate <file>``: print graded issues, return the exit code."""
    parser = argparse.ArgumentParser(
        prog="SMACC validate", description="Validate a SMACC (.smacc) study file."
    )
    parser.add_argument("file", help="the .smacc file to validate")
    args = parser.parse_args(argv)

    errors, warnings = validate_file(args.file)
    name = Path(args.file).name
    for warning in warnings:
        print(f"warning: {warning}")
    for error in errors:
        print(f"error: {error}")
    if errors:
        print(f"{name}: invalid ({len(errors)} error(s), {len(warnings)} warning(s)).")
        return 1
    if warnings:
        print(f"{name}: valid, with {len(warnings)} warning(s).")
        return 0
    print(f"{name}: valid.")
    return 0
