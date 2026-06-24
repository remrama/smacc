"""Tests for the in-app survey window (#114): gating, submission, and files.

Headless like the other GUI tests: the window is constructed directly, radios
are driven through their button groups, and the blocking confirmation box is
monkeypatched. Submissions write real JSON into the live session's run folder.
"""

from __future__ import annotations

import json

import pytest
from PyQt6 import QtWidgets

from smacc import surveys
from smacc.panels.survey import SurveyWindow


@pytest.fixture
def demo_survey():
    return surveys.parse_survey_mapping(
        {
            "kind": surveys.KIND,
            "schema_version": 1,
            "key": "demo",
            "name": "Demo",
            "title": "Demo survey",
            "version": "1.0",
            "scale": {"min": 0, "max": 2, "anchors": ["No", "Some", "Yes"]},
            "items": ["First item", "Second item"],
        }
    )


def _answer(window: SurveyWindow, item_index: int, value: int) -> None:
    button = window._groups[item_index].button(value)
    assert button is not None
    button.setChecked(True)


def test_preview_without_session_disables_submit(qtbot, demo_survey):
    window = SurveyWindow(demo_survey, None)
    qtbot.addWidget(window)
    assert not window.submitButton.isEnabled()


def test_designer_session_disables_submit(qtbot, demo_survey, headless_session):
    window = SurveyWindow(demo_survey, headless_session)
    qtbot.addWidget(window)
    assert not window.submitButton.isEnabled()


def test_responses_track_radio_state(qtbot, demo_survey, headless_session):
    window = SurveyWindow(demo_survey, headless_session)
    qtbot.addWidget(window)
    assert window.responses() == [None, None]
    _answer(window, 0, 2)
    _answer(window, 1, 0)
    assert window.responses() == [2, 0]


def test_submit_attached_writes_report_named_file(qtbot, demo_survey, live_session):
    window = SurveyWindow(demo_survey, live_session, report_number=1)
    qtbot.addWidget(window)
    assert window.submitButton.isEnabled()
    _answer(window, 0, 1)
    _answer(window, 1, 2)
    window.notesEdit.setText("verbal over intercom")
    window._on_submit()
    path = live_session.session_dir / "report-01-survey-demo.json"
    assert path.is_file()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["kind"] == surveys.RESPONSE_KIND
    assert payload["survey"] == {
        "key": "demo",
        "name": "Demo",
        "title": "Demo survey",
        "version": "1.0",
        "builtin": False,
    }
    assert payload["report_number"] == 1
    assert [r["response"] for r in payload["responses"]] == [1, 2]
    assert payload["notes"] == "verbal over intercom"
    assert window.result() == QtWidgets.QDialog.DialogCode.Accepted


def test_submit_standalone_uses_own_sequence(qtbot, demo_survey, live_session):
    for expected in ("survey-01-demo.json", "survey-02-demo.json"):
        window = SurveyWindow(demo_survey, live_session)
        qtbot.addWidget(window)
        _answer(window, 0, 0)
        _answer(window, 1, 0)
        window._on_submit()
        assert (live_session.session_dir / expected).is_file()


def test_submit_confirms_unanswered_items(
    qtbot, monkeypatch, demo_survey, live_session
):
    asked = []

    def fake_question(*args, **kwargs):
        asked.append(args)
        return QtWidgets.QMessageBox.StandardButton.No

    monkeypatch.setattr(QtWidgets.QMessageBox, "question", fake_question)
    window = SurveyWindow(demo_survey, live_session, report_number=1)
    qtbot.addWidget(window)
    _answer(window, 0, 1)  # the second item stays unanswered
    window._on_submit()
    assert asked  # the confirmation fired
    assert not list(live_session.session_dir.glob("*.json"))  # and No meant no file


def test_repeat_submission_for_same_report_is_suffixed(
    qtbot, demo_survey, live_session
):
    for expected in ("report-01-survey-demo.json", "report-01-survey-demo-2.json"):
        window = SurveyWindow(demo_survey, live_session, report_number=1)
        qtbot.addWidget(window)
        _answer(window, 0, 1)
        _answer(window, 1, 1)
        window._on_submit()
        assert (live_session.session_dir / expected).is_file()


# ----- mixed item types (#118) -----------------------------------------------


@pytest.fixture
def mixed_survey():
    return surveys.parse_survey_mapping(
        {
            "kind": surveys.KIND,
            "schema_version": 1,
            "key": "mixed",
            "name": "Mixed",
            "title": "Mixed survey",
            "scale": {"min": 0, "max": 2, "anchors": ["No", "Some", "Yes"]},
            "items": [
                {"text": "Background", "type": "heading"},
                "A Likert item",
                {"text": "Age", "type": "number", "min": 0, "max": 99, "unit": "years"},
                {"text": "Job", "type": "text"},
                {
                    "text": "How often?",
                    "type": "select",
                    "levels": {0: "never", 1: "sometimes", 2: "often"},
                },
            ],
        }
    )


def _control(window: SurveyWindow, item_type: str):
    """The input control for the (single) item of ``item_type`` in this survey."""
    return next(c for it, c, _ in window._fields if it.type == item_type)


def test_mixed_survey_builds_typed_widgets(qtbot, mixed_survey, headless_session):
    window = SurveyWindow(mixed_survey, headless_session)
    qtbot.addWidget(window)
    kinds = {it.type: type(control) for it, control, _ in window._fields}
    assert kinds["likert"] is QtWidgets.QButtonGroup
    assert kinds["number"] is QtWidgets.QSpinBox
    assert kinds["text"] is QtWidgets.QLineEdit
    assert kinds["select"] is QtWidgets.QComboBox
    # The heading is display-only: not a field, no response.
    assert all(it.type != "heading" for it, _, _ in window._fields)
    assert len(window._fields) == 4


def test_mixed_survey_responses_read_each_widget(qtbot, mixed_survey, headless_session):
    window = SurveyWindow(mixed_survey, headless_session)
    qtbot.addWidget(window)
    assert window.responses() == [None, None, None, None]
    window._groups[0].button(2).setChecked(True)
    _control(window, "number").setValue(42)
    _control(window, "text").setText("  scientist  ")
    combo = _control(window, "select")
    combo.setCurrentIndex(combo.findData(1))
    # _fields order follows item order: likert, number, text, select.
    assert window.responses() == [2, 42, "scientist", 1]


def test_number_left_blank_is_unanswered(qtbot, mixed_survey, headless_session):
    window = SurveyWindow(mixed_survey, headless_session)
    qtbot.addWidget(window)
    spin = _control(window, "number")
    assert spin.value() == spin.minimum()  # starts on the "—" special-value slot
    assert window.responses()[1] is None


def test_mixed_survey_submit_writes_typed_responses(qtbot, mixed_survey, live_session):
    window = SurveyWindow(mixed_survey, live_session)
    qtbot.addWidget(window)
    window._groups[0].button(1).setChecked(True)
    _control(window, "number").setValue(30)
    _control(window, "text").setText("pilot")
    combo = _control(window, "select")
    combo.setCurrentIndex(combo.findData(2))
    window._on_submit()
    payload = json.loads(
        (live_session.session_dir / "survey-01-mixed.json").read_text(encoding="utf-8")
    )
    by_type = {r["type"]: r for r in payload["responses"]}
    assert len(payload["responses"]) == 4  # heading excluded
    assert by_type["likert"]["response"] == 1 and by_type["likert"]["label"] == "Some"
    assert by_type["number"]["response"] == 30 and by_type["number"]["label"] == ""
    assert by_type["text"]["response"] == "pilot"
    assert by_type["select"]["response"] == 2 and by_type["select"]["label"] == "often"
