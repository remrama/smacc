"""Convert a SMACC session log into a BIDS ``events.tsv`` (+ JSON sidecar).

SMACC logs every event marker as ``"{label} - portcode {N}"`` on a line formatted
``"YYYY-MM-DD HH:MM:SS.mmm, LEVEL, message"``. This module parses that log and emits
BIDS-style event rows (``onset``/``duration``/``trial_type``/``value``). Pure functions,
no GUI — directly unit-testable.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

_LOG_DATETIME_FMT = "%Y-%m-%d %H:%M:%S.%f"
_PORTCODE_RE = re.compile(r"^(?P<label>.*) - portcode (?P<code>\d+)$")

EVENT_COLUMNS = ["onset", "duration", "trial_type", "value"]

# Sentinels fencing a settings front-matter block embedded in the log. The block
# records the config a session ran with so it can be recovered later. Every line
# is a ``#`` comment, so ``parse_log`` (which needs a 3-field timestamped line)
# skips the whole block. ``which`` is "initial" (logged at start) or "final"
# (appended at quit), letting a reader pick either snapshot.
SETTINGS_BEGIN = "# --8<-- smacc/settings"
SETTINGS_END = "# --8<-- end smacc/settings"


def parse_log(log_text: str) -> list[tuple[datetime, str, str]]:
    """Return ``(timestamp, level, message)`` for each parseable log line."""
    rows: list[tuple[datetime, str, str]] = []
    for line in log_text.splitlines():
        parts = line.split(", ", 2)
        if len(parts) != 3:
            continue
        timestamp, level, message = parts
        try:
            when = datetime.strptime(timestamp, _LOG_DATETIME_FMT)
        except ValueError:
            continue
        rows.append((when, level, message))
    return rows


def log_to_events(log_text: str) -> list[dict[str, Any]]:
    """Build BIDS event rows from log text.

    ``onset`` is seconds relative to the first parseable log entry. Only
    event-marker lines (ending in ``" - portcode N"``) become events.
    """
    rows = parse_log(log_text)
    if not rows:
        return []
    t0 = rows[0][0]
    events: list[dict[str, Any]] = []
    for when, _level, message in rows:
        match = _PORTCODE_RE.match(message)
        if not match:
            continue
        events.append(
            {
                "onset": round((when - t0).total_seconds(), 3),
                "duration": "n/a",
                "trial_type": match.group("label"),
                "value": int(match.group("code")),
            }
        )
    return events


def write_events_tsv(events: list[dict[str, Any]], path: str | Path) -> None:
    """Write event rows to ``path`` as a BIDS tab-separated values file."""
    lines = ["\t".join(EVENT_COLUMNS)]
    lines += ["\t".join(str(ev[col]) for col in EVENT_COLUMNS) for ev in events]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def events_sidecar() -> dict[str, Any]:
    """Return the BIDS JSON sidecar describing the events columns."""
    return {
        "onset": {
            "Description": "Event onset relative to the first log entry.",
            "Units": "second",
        },
        "duration": {
            "Description": "Event duration; 'n/a' for instantaneous markers.",
            "Units": "second",
        },
        "trial_type": {"Description": "Event label as logged by SMACC."},
        "value": {"Description": "SMACC portcode / LSL marker value."},
    }


def write_events_json(path: str | Path) -> None:
    """Write the events JSON sidecar to ``path``."""
    Path(path).write_text(json.dumps(events_sidecar(), indent=2), encoding="utf-8")


def format_settings_block(payload: dict[str, Any], which: str) -> str:
    """Render ``payload`` as a fully ``#``-commented, sentinel-fenced log block.

    ``which`` ("initial"/"final") tags the sentinels so both snapshots can coexist
    in one log. Commenting every line keeps the block invisible to ``parse_log``.
    """
    body = yaml.safe_dump(
        payload, sort_keys=False, default_flow_style=False, allow_unicode=True
    )
    commented = "\n".join(f"# {line}" if line else "#" for line in body.splitlines())
    return f"{SETTINGS_BEGIN} {which}\n{commented}\n{SETTINGS_END} {which}\n"


def extract_settings_from_log(log_text: str, which: str = "initial") -> dict | None:
    """Return the ``which`` settings payload embedded in ``log_text``, or ``None``.

    Returns ``None`` when the requested block is absent (e.g. a crashed session
    that never wrote its "final" block) or unparseable.
    """
    begin = f"{SETTINGS_BEGIN} {which}"
    end = f"{SETTINGS_END} {which}"
    lines = log_text.splitlines()
    start = _index_of(lines, begin)
    if start < 0:
        return None
    stop = _index_of(lines, end, start + 1)
    if stop < 0:
        return None
    body = "\n".join(_uncomment(line) for line in lines[start + 1 : stop])
    try:
        payload = yaml.safe_load(body)
    except yaml.YAMLError:
        return None
    return payload if isinstance(payload, dict) else None


def _index_of(lines: list[str], target: str, start: int = 0) -> int:
    """Return the index of the first line equal to ``target`` (ignoring surrounding
    whitespace) at or after ``start``, or -1 if none."""
    for idx in range(start, len(lines)):
        if lines[idx].strip() == target:
            return idx
    return -1


def _uncomment(line: str) -> str:
    """Strip a leading ``"# "`` (or bare ``"#"``) added by ``format_settings_block``."""
    if line.startswith("# "):
        return line[2:]
    if line.startswith("#"):
        return line[1:]
    return line
