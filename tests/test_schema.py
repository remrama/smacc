"""Tests for the model-derived .smacc JSON Schema (#302)."""

from __future__ import annotations

import jsonschema

from smacc import schema, settings
from smacc.paths import BUNDLED_DEFAULT_SETTINGS, BUNDLED_SCHEMA_PATH


def test_build_schema_is_itself_a_valid_json_schema():
    jsonschema.Draft202012Validator.check_schema(schema.build_schema())


def test_committed_schema_file_is_up_to_date():
    # The committed file is generated from the model. If this fails, regenerate it:
    #   uv run python -c "from smacc.schema import write_schema; write_schema()"
    committed = BUNDLED_SCHEMA_PATH.read_text(encoding="utf-8")
    assert committed == schema.dumps()


def test_schema_covers_every_settings_key():
    # The properties are built from the model's own flat projection, so the schema
    # cannot silently miss a key a study can carry.
    props = schema.build_schema()["properties"]["settings"]["properties"]
    assert set(props) == set(schema._maximal_settings())


def test_every_refinement_targets_a_real_settings_key():
    # Guards a typo in a refinement key (which would silently do nothing).
    assert set(schema._REFINEMENTS) <= set(schema._maximal_settings())


def test_schema_validates_the_bundled_default_smacc():
    state, _meta = settings.load_settings(BUNDLED_DEFAULT_SETTINGS)
    settings_schema = schema.build_schema()["properties"]["settings"]
    jsonschema.validate(state, settings_schema)  # raises if the template is invalid


def test_schema_flags_bad_values_and_unknown_keys():
    settings_schema = schema.build_schema()["properties"]["settings"]
    validator = jsonschema.Draft202012Validator(settings_schema)
    bad = {"noise_volume": 2.0, "noise_color": "chartreuse", "typo_key": 1}
    messages = " ".join(e.message for e in validator.iter_errors(bad))
    assert "maximum" in messages  # noise_volume 2.0 > 1
    assert "chartreuse" in messages  # noise_color not in the enum
    assert "typo_key" in messages  # unknown key (additionalProperties: false)
