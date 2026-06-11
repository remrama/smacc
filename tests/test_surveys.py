"""Tests for the survey registry, files, and response payloads (#114).

Pure-module coverage for :mod:`smacc.surveys`: the bundled definitions load
clean, the parser rejects malformed files with useful messages, definitions
round-trip through the builder's save path, and response filenames/payloads
carry the report linkage and content version they promise.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from smacc import surveys
from smacc.paths import BUNDLED_SURVEYS_DIR


def _mapping(**overrides):
    """A small valid survey mapping; override fields to probe validation."""
    payload = {
        "kind": surveys.KIND,
        "schema_version": 1,
        "key": "demo",
        "name": "Demo",
        "title": "Demo survey",
        "version": "1.0",
        "citation": "Someone (2026)",
        "instructions": "Rate each item.",
        "scale": {"min": 0, "max": 2, "anchors": ["No", "Some", "Yes"]},
        "items": ["First item", "Second item"],
    }
    payload.update(overrides)
    return payload


# ----- bundled definitions ----------------------------------------------------


def test_bundled_surveys_load_clean(tmp_path):
    loaded, problems = surveys.all_surveys(BUNDLED_SURVEYS_DIR, tmp_path / "none")
    assert problems == []
    assert set(loaded) >= {"lucid", "dlq", "lusk"}
    for survey in loaded.values():
        assert survey.builtin
        assert survey.items
        assert survey.version  # content version is recorded in every response
        assert len(survey.anchors) in (0, survey.n_points)


# ----- parsing / validation ----------------------------------------------------


def test_parse_returns_definition():
    survey = surveys.parse_survey_mapping(_mapping())
    assert survey.key == "demo"
    assert survey.n_points == 3
    assert survey.anchor_for(2) == "Yes"
    assert survey.anchor_for(99) == ""
    assert survey.url == "smacc://survey/demo"
    assert survey.builtin is False


def test_parse_coerces_numeric_version():
    assert surveys.parse_survey_mapping(_mapping(version=2)).version == "2"


def test_parse_defaults_title_to_name():
    assert surveys.parse_survey_mapping(_mapping(title="")).title == "Demo"


@pytest.mark.parametrize(
    "overrides",
    [
        {"kind": "smacc/settings"},
        {"schema_version": "x"},
        {"schema_version": 0},
        {"schema_version": surveys.SCHEMA_VERSION + 1},
        {"key": "Bad Key!"},
        {"key": ""},
        {"name": ""},
        {"items": []},
        {"items": ["ok", "  "]},
        {"items": "not a list"},
        {"scale": "not a mapping"},
        {"scale": {"min": 0}},
        {"scale": {"min": 2, "max": 2}},
        {"scale": {"min": 0, "max": 99}},
        {"scale": {"min": 0, "max": 2, "anchors": ["only", "two"]}},
        {"scale": {"min": 0, "max": 2, "anchors": "nope"}},
    ],
)
def test_parse_rejects_malformed(overrides):
    with pytest.raises(ValueError):
        surveys.parse_survey_mapping(_mapping(**overrides))


def test_parse_rejects_non_mapping():
    with pytest.raises(ValueError):
        surveys.parse_survey_mapping(["not", "a", "mapping"])


# ----- typed items (#118) -------------------------------------------------------


def _typed_mapping(items, **overrides):
    """A valid survey mapping carrying the given (typed) items."""
    payload = _mapping(**overrides)
    payload["items"] = items
    return payload


def test_bare_string_item_is_likert():
    survey = surveys.parse_survey_mapping(_mapping())
    assert all(it.type == surveys.LIKERT for it in survey.items)
    assert survey.items[0].text == "First item"
    assert survey.is_simple_likert


def test_parse_select_number_text_heading_items():
    survey = surveys.parse_survey_mapping(
        _typed_mapping(
            [
                {"text": "A section", "type": "heading"},
                "A Likert item",
                {"text": "Age", "type": "number", "min": 0, "max": 99, "unit": "years"},
                {"text": "Job", "type": "text"},
                {
                    "text": "How often?",
                    "type": "select",
                    "help": "see note",
                    "levels": {2: "often", 0: "never", 1: "sometimes"},
                },
            ]
        )
    )
    heading, likert, number, text, select = survey.items
    assert heading.type == surveys.HEADING and not heading.collects_response
    assert likert.type == surveys.LIKERT
    assert number.type == surveys.NUMBER
    assert (number.number_min, number.number_max, number.unit) == (0, 99, "years")
    assert text.type == surveys.TEXT
    # Levels are sorted by value regardless of mapping order, and help is kept.
    assert select.levels == ((0, "never"), (1, "sometimes"), (2, "often"))
    assert select.help == "see note"
    assert not survey.is_simple_likert
    assert len(survey.response_items) == 4  # the heading collects nothing


def test_scale_optional_when_no_likert_items():
    survey = surveys.parse_survey_mapping(
        {
            "kind": surveys.KIND,
            "schema_version": surveys.SCHEMA_VERSION,
            "key": "demo",
            "name": "Demo",
            "items": [{"text": "Job", "type": "text"}],  # no Likert -> no scale needed
        }
    )
    assert survey.items[0].type == surveys.TEXT


@pytest.mark.parametrize(
    "items",
    [
        [{"text": "Q", "type": "bogus"}],  # unknown type
        [{"text": "Q", "type": "select"}],  # select needs levels
        [{"text": "Q", "type": "select", "levels": {0: "only"}}],  # <2 levels
        [{"text": "Q", "type": "select", "levels": {0: "a", 1: ""}}],  # blank label
        [{"text": "Q", "type": "select", "levels": {"x": "a", "y": "b"}}],  # bad keys
        [{"text": "Q", "type": "number", "min": 5, "max": 5}],  # max !> min
        [{"type": "text"}],  # missing item text
        [{"text": "only a heading", "type": "heading"}],  # nothing collects a response
    ],
)
def test_parse_rejects_malformed_typed_items(items):
    with pytest.raises(ValueError):
        surveys.parse_survey_mapping(_typed_mapping(items))


def test_madre_is_the_bundled_mixed_survey(tmp_path):
    from smacc.paths import BUNDLED_SURVEYS_DIR

    loaded, problems = surveys.all_surveys(BUNDLED_SURVEYS_DIR, tmp_path / "none")
    assert problems == []
    madre = loaded["madre"]
    types = {it.type for it in madre.items}
    assert {"select", "number", "text", "likert", "heading"} <= types
    # "No"/"Yes" survive YAML's boolean coercion as text labels.
    recurrence = next(
        it for it in madre.items if it.text.startswith("Do you experience")
    )
    assert recurrence.levels == ((0, "No"), (1, "Yes"))


def test_typed_survey_round_trips_through_mapping():
    survey = surveys.parse_survey_mapping(
        _typed_mapping(
            [
                {"text": "Sec", "type": "heading"},
                "A Likert item",
                {"text": "Pick", "type": "select", "levels": {0: "no", 1: "yes"}},
            ]
        )
    )
    mapping = surveys.survey_to_mapping(survey)
    assert mapping["schema_version"] == surveys.SCHEMA_VERSION
    assert mapping["items"][1] == "A Likert item"  # plain Likert collapses to a string
    reloaded = surveys.parse_survey_mapping(mapping)
    assert reloaded.items == survey.items


# ----- save / load round trip ---------------------------------------------------


def test_save_and_load_round_trip(tmp_path):
    survey = surveys.parse_survey_mapping(_mapping())
    path = surveys.save_survey(survey, tmp_path / "surveys")
    assert path.name == "demo.yaml"
    loaded = surveys.load_survey(path)
    assert loaded.path == path
    assert loaded.builtin is False
    for field in ("key", "name", "title", "version", "citation", "instructions"):
        assert getattr(loaded, field) == getattr(survey, field)
    assert loaded.anchors == survey.anchors
    assert loaded.items == survey.items


def test_load_survey_dir_skips_malformed(tmp_path):
    surveys.save_survey(surveys.parse_survey_mapping(_mapping()), tmp_path)
    (tmp_path / "broken.yaml").write_text("kind: smacc/settings\n", encoding="utf-8")
    loaded, problems = surveys.load_survey_dir(tmp_path)
    assert [s.key for s in loaded] == ["demo"]
    assert len(problems) == 1 and "broken.yaml" in problems[0]


def test_load_survey_dir_missing_directory_is_empty(tmp_path):
    loaded, problems = surveys.load_survey_dir(tmp_path / "nowhere")
    assert loaded == [] and problems == []


def test_all_surveys_builtin_wins_key_collision(tmp_path):
    builtin_dir = tmp_path / "builtin"
    user_dir = tmp_path / "user"
    surveys.save_survey(surveys.parse_survey_mapping(_mapping()), builtin_dir)
    surveys.save_survey(
        surveys.parse_survey_mapping(_mapping(name="Imposter")), user_dir
    )
    loaded, problems = surveys.all_surveys(builtin_dir, user_dir)
    assert loaded["demo"].name == "Demo"  # the built-in one
    assert loaded["demo"].builtin
    assert any("demo" in p for p in problems)


# ----- pseudo-URL helpers --------------------------------------------------------


def test_survey_key_from_url():
    assert surveys.survey_key_from_url("smacc://survey/dlq") == "dlq"
    assert surveys.survey_key_from_url("https://example.com") is None
    assert surveys.survey_key_from_url(surveys.URL_PREFIX) is None
    assert surveys.survey_key_from_url("") is None


def test_slugify_key():
    assert surveys.slugify_key("My Survey! (v2)") == "my-survey-v2"
    assert surveys.slugify_key("???") == "survey"


# ----- response files -------------------------------------------------------------


def test_response_filename_attached_vs_standalone():
    assert surveys.response_filename("dlq", report_number=2) == "report-02-survey-dlq"
    assert surveys.response_filename("dlq", ordinal=3) == "survey-03-dlq"


def test_next_response_ordinal(tmp_path):
    assert surveys.next_response_ordinal(tmp_path / "nowhere") == 1
    assert surveys.next_response_ordinal(tmp_path) == 1
    (tmp_path / "survey-01-dlq.json").write_text("{}", encoding="utf-8")
    (tmp_path / "survey-03-lusk.json").write_text("{}", encoding="utf-8")
    # Report-attached responses are a separate sequence and don't count.
    (tmp_path / "report-09-survey-dlq.json").write_text("{}", encoding="utf-8")
    assert surveys.next_response_ordinal(tmp_path) == 4


def test_unique_response_path(tmp_path):
    first = surveys.unique_response_path(tmp_path, "report-01-survey-dlq")
    assert first.name == "report-01-survey-dlq.json"
    first.write_text("{}", encoding="utf-8")
    second = surveys.unique_response_path(tmp_path, "report-01-survey-dlq")
    assert second.name == "report-01-survey-dlq-2.json"


def test_response_payload_carries_linkage_and_version():
    survey = surveys.parse_survey_mapping(_mapping())
    payload = surveys.response_payload(
        survey,
        [2, None],
        metadata={"subject": "001", "session": "2", "notes": "ignored here"},
        opened=datetime(2026, 6, 10, 3, 2, 1),
        submitted=datetime(2026, 6, 10, 3, 4, 5),
        elapsed=timedelta(hours=1, seconds=5),
        report_number=2,
        notes="  participant unsure on item 2  ",
    )
    assert payload["kind"] == surveys.RESPONSE_KIND
    assert payload["survey"]["key"] == "demo"
    assert payload["survey"]["version"] == "1.0"
    assert payload["subject"] == "001"
    assert payload["report_number"] == 2
    assert payload["opened"] == "2026-06-10T03:02:01"
    assert payload["submitted"] == "2026-06-10T03:04:05"
    assert payload["time_since_recording_start"] == "01:00:05"
    assert payload["responses"] == [
        {"item": "First item", "type": "likert", "response": 2, "label": "Yes"},
        {"item": "Second item", "type": "likert", "response": None, "label": ""},
    ]
    assert payload["notes"] == "participant unsure on item 2"


def test_response_payload_unmarked_recording_and_standalone():
    survey = surveys.parse_survey_mapping(_mapping())
    payload = surveys.response_payload(survey, [0, 1])
    assert payload["report_number"] is None
    assert payload["time_since_recording_start"] is None
    assert payload["opened"] is None and payload["submitted"] is None
