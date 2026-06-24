"""A JSON Schema for a ``.smacc`` file, generated from the StudyConfig model (#302).

Power users edit ``.smacc`` files by hand; this schema gives their editor
autocomplete and validation. It is **derived from the model**, not a second
hand-maintained copy that could drift: the set of settings keys and each key's base
JSON type come straight from :meth:`StudyConfig.to_settings_dict` (the canonical
flat projection), and only *refinements* — enums, numeric ranges, and the shapes of
the cue/event/biocal array items — are declared here. The committed schema file
(``assets/smacc-schema.json``) is regenerated from :func:`build_schema` and a test
fails if it drifts (see ``tests/test_schema.py``), so the model stays the single
source of truth.

Pure and Qt-free, like the model: imported by the headless ``SMACC validate`` CLI.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import biocals, events
from .config import SCHEMA_URL
from .paths import BUNDLED_SCHEMA_PATH
from .settings import KIND, SCHEMA_VERSION
from .studyconfig import StudyConfig

# JSON Schema dialect this schema targets. The public URL it is served at (and that
# the template's modeline points to) is SCHEMA_URL, shared from smacc.config.
SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_PATH = BUNDLED_SCHEMA_PATH

# A 0-1 software gain; a hex color; an 8-bit port code. Reused across refinements.
_UNIT = {"type": "number", "minimum": 0, "maximum": 1}
_HEX_COLOR = {"type": "string", "pattern": "^#[0-9a-fA-F]{6}$"}
_CODE = {"type": "integer", "minimum": events.CODE_MIN, "maximum": events.CODE_MAX}
_LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

_CUE_ITEM = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "file": {"type": "string"},
        "volume": _UNIT,
        "loop": {"type": "boolean"},
    },
    "additionalProperties": False,
}
_VISUAL_CUE_ITEM = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "color": _HEX_COLOR,
        "brightness": _UNIT,
        "pattern": {"enum": ["steady", "pulse", "flash"]},
        "rate": {"type": "number", "exclusiveMinimum": 0},
        "length": {"type": "number", "minimum": 0},
        "loop": {"type": "boolean"},
    },
    "additionalProperties": False,
}
_EVENT_ITEM = {
    "type": "object",
    "properties": {
        "key": {"type": "string"},
        "code": _CODE,
        "lsl": {"type": "boolean"},
        "ttl": {"type": "boolean"},
        "preview": {"type": "boolean"},
        "increment": {"type": "boolean"},
    },
    "required": ["key", "code"],
}
_BIOCAL_ROW = {
    "type": "object",
    "properties": {
        "biocal": {"type": "string"},
        "sequence": {"type": "boolean"},
        "voice": {"type": "boolean"},
        "duration": {
            "type": "integer",
            "minimum": biocals.MIN_DURATION_S,
            "maximum": biocals.MAX_DURATION_S,
        },
    },
    "required": ["biocal"],
}

# Per-key refinements layered onto the base type derived from the model's own
# output. Keys not listed keep just their base type. Every key here must be a real
# settings key (guarded by tests/test_schema.py).
_REFINEMENTS: dict[str, dict[str, Any]] = {
    "biocals": {
        "properties": {
            "voice_volume": _UNIT,
            "rows": {"type": "array", "items": _BIOCAL_ROW},
        }
    },
    "visual_cues": {"items": _VISUAL_CUE_ITEM},
    "visual_attack": {"minimum": 0},
    "visual_release": {"minimum": 0},
    "cues": {"items": _CUE_ITEM},
    "cue_attack": {"minimum": 0},
    "cue_release": {"minimum": 0},
    "noise_volume": dict(_UNIT),
    "noise_color": {"enum": ["white", "pink", "brown"]},
    "noise_source": {"enum": ["builtin", "file"]},
    "survey_options": {"additionalProperties": {"type": "string"}},
    "chat_experimenter_presets": {"items": {"type": "string"}},
    "chat_participant_presets": {"items": {"type": "string"}},
    "chat_font_size": {"minimum": 8, "maximum": 72},
    "volume_cap": dict(_UNIT),
    "output_latency": {"enum": ["high", "low"]},
    "devices": {
        "properties": {
            "routing": {"type": "object", "additionalProperties": {"type": "string"}}
        }
    },
    "event_codes": {"items": _EVENT_ITEM},
    "event_code_safe_max": {"minimum": events.CODE_MIN, "maximum": events.CODE_MAX},
    "trigger_output": {
        "properties": {
            "enabled": {"type": "boolean"},
            "transport": {"enum": ["serial", "parallel"]},
            "mode": {"enum": ["pulsed", "hold"]},
            "pulse_ms": {"type": "integer", "minimum": 1},
            "port": {"type": "string"},
            "baud": {"type": "integer"},
            "address": {"type": "string"},
        }
    },
    "preview_levels": {"items": {"enum": _LOG_LEVELS}},
    "tool_always_on_top": {"additionalProperties": {"type": "boolean"}},
}

# JSON type for each Python type the flat projection emits.
_JSON_TYPE = {bool: "boolean", int: "integer", float: "number", str: "string"}


def _base_type(value: object) -> dict[str, Any]:
    """The base JSON Schema type for a settings value (derived from the model)."""
    if isinstance(value, bool):  # bool before int (bool is an int subclass)
        return {"type": "boolean"}
    for py_type, json_type in _JSON_TYPE.items():
        if type(value) is py_type:
            return {"type": json_type}
    if isinstance(value, list):
        return {"type": "array"}
    return {"type": "object"}


def _maximal_settings() -> dict[str, Any]:
    """``to_settings_dict`` with the optional blocks present, for the full key set."""
    cfg = StudyConfig()
    cfg.interface.chat_experimenter_presets = []
    cfg.interface.chat_participant_presets = []
    cfg.cueing.biocals.rows = []
    return cfg.to_settings_dict()


def _settings_properties() -> dict[str, Any]:
    """The ``settings`` object's properties: base type per key, refined where known."""
    props: dict[str, Any] = {}
    for key, value in _maximal_settings().items():
        schema = _base_type(value)
        schema.update(_REFINEMENTS.get(key, {}))
        props[key] = schema
    return props


def build_schema() -> dict[str, Any]:
    """Build the JSON Schema for a ``.smacc`` file from the StudyConfig model."""
    return {
        "$schema": SCHEMA_DIALECT,
        "$id": SCHEMA_URL,
        "title": "SMACC settings file",
        "description": "A SMACC study configuration (.smacc). Generated from the "
        "StudyConfig model; edit the model, not this file.",
        "type": "object",
        "properties": {
            "kind": {"const": KIND},
            "schema_version": {"const": SCHEMA_VERSION},
            "smacc_version": {"type": "string"},
            "metadata": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "session": {"type": "string"},
                    "notes": {"type": "string"},
                },
            },
            "settings": {
                "type": "object",
                "properties": _settings_properties(),
                "additionalProperties": False,
            },
        },
        "required": ["settings"],
    }


def dumps() -> str:
    """The committed schema text: pretty, stable key order, trailing newline."""
    return json.dumps(build_schema(), indent=2, sort_keys=False) + "\n"


def write_schema(path: Path = SCHEMA_PATH) -> None:
    """Regenerate the committed schema file (run from a small CI/dev command).

    Writes raw bytes (LF), not text, so the file is byte-identical whatever platform
    regenerates it — and the drift test (which reads back with universal newlines)
    stays stable across Windows and Linux.
    """
    path.write_bytes(dumps().encode("utf-8"))
