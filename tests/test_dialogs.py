"""Tests for the dialogs in smacc.dialogs (need a QApplication, no hardware).

Each dialog exposes a read-from-widget getter (``changes``/``get_inputs``/
``get_options``/``get_events``) that the caller reads only on accept. The tests
construct a dialog, drive its widgets, and assert the getter — no event loop and
no ``.exec()``. The couple of paths that pop a blocking ``QMessageBox`` are
exercised with that static call monkeypatched.
"""

from __future__ import annotations

import pytest
from PyQt6 import QtWidgets

from smacc import dialogs, events

# ----- PreferencesDialog -----------------------------------------------------


def test_preferences_dialog_round_trips_prefs(qtbot):
    prefs = {"always_on_top": True, "preview_levels": ["ERROR", "INFO"]}
    dialog = dialogs.PreferencesDialog(prefs)
    qtbot.addWidget(dialog)
    changes = dialog.changes()
    assert changes["always_on_top"] is True
    # Returned in the canonical level order, not the input order.
    assert changes["preview_levels"] == ["INFO", "ERROR"]


def test_preferences_dialog_reflects_edits(qtbot):
    dialog = dialogs.PreferencesDialog({"always_on_top": False, "preview_levels": []})
    qtbot.addWidget(dialog)
    dialog.alwaysOnTop.setChecked(True)
    dialog._levelBoxes["WARNING"].setChecked(True)
    changes = dialog.changes()
    assert changes["always_on_top"] is True
    assert changes["preview_levels"] == ["WARNING"]


# ----- ask_initial_or_final --------------------------------------------------


def _patch_choice(monkeypatch, index):
    """Make the next QMessageBox 'click' resolve to buttons()[index] (None = cancel)."""
    box_cls = QtWidgets.QMessageBox
    monkeypatch.setattr(box_cls, "exec", lambda self: 0)

    def clicked(self):
        btns = self.buttons()
        return btns[index] if index is not None and index < len(btns) else None

    monkeypatch.setattr(box_cls, "clickedButton", clicked)


@pytest.mark.parametrize(
    "index, expected",
    [(0, "initial"), (1, "final"), (None, None)],
)
def test_ask_initial_or_final(qtbot, monkeypatch, index, expected):
    _patch_choice(monkeypatch, index)
    assert dialogs.ask_initial_or_final() == expected


# ----- SessionInfoDialog -----------------------------------------------------


def test_session_info_dialog_returns_inputs(qtbot):
    dialog = dialogs.SessionInfoDialog(subject="001", session="2", notes="a note")
    qtbot.addWidget(dialog)
    assert dialog.get_inputs() == ("001", "2", "a note")
    dialog.subject_id.setText("042")
    assert dialog.get_inputs() == ("042", "2", "a note")


# ----- SurveyDialog ----------------------------------------------------------


def test_survey_dialog_strips_name_and_normalizes_url(qtbot):
    dialog = dialogs.SurveyDialog(name="  My survey  ", url="example.com/post")
    qtbot.addWidget(dialog)
    name, url = dialog.get_inputs()
    assert name == "My survey"
    # normalize_survey_url adds a scheme when none is given.
    assert url.startswith("http") and "example.com/post" in url


# ----- ManageSurveysDialog ---------------------------------------------------


def test_manage_surveys_round_trips_options(qtbot):
    options = {"Post survey": "https://a.example", "Pre survey": "https://b.example"}
    dialog = dialogs.ManageSurveysDialog(options)
    qtbot.addWidget(dialog)
    assert dialog.get_options() == options


def test_manage_surveys_remove_selected(qtbot):
    options = {"Post survey": "https://a.example", "Pre survey": "https://b.example"}
    dialog = dialogs.ManageSurveysDialog(options)
    qtbot.addWidget(dialog)
    dialog.listWidget.setCurrentRow(0)
    dialog._remove_selected()
    assert dialog.get_options() == {"Pre survey": "https://b.example"}


# ----- AddEventDialog --------------------------------------------------------


def test_add_event_dialog_returns_inputs(qtbot):
    dialog = dialogs.AddEventDialog(default_code=42)
    qtbot.addWidget(dialog)
    dialog.labelEdit.setText("  Spontaneous arousal  ")
    dialog.tooltipEdit.setText(" a hint ")
    dialog.incrementBox.setChecked(True)
    label, code, tooltip, increment = dialog.get_inputs()
    assert label == "Spontaneous arousal"
    assert code == 42
    assert tooltip == "a hint"
    assert increment is True


def test_add_event_dialog_rejects_blank_label(qtbot, monkeypatch):
    warned = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "warning", lambda *a, **k: warned.append(a)
    )
    dialog = dialogs.AddEventDialog(default_code=10)
    qtbot.addWidget(dialog)
    dialog.labelEdit.setText("   ")  # blank after strip
    dialog._on_accept()
    assert warned  # the warning fired
    assert dialog.result() != QtWidgets.QDialog.DialogCode.Accepted


# ----- EventCodesDialog ------------------------------------------------------


def _custom(label, code):
    return events.EventDef(
        key=label.replace(" ", ""),
        label=label,
        code=code,
        category="manual",
        builtin=False,
    )


def test_event_codes_dialog_get_safe_max(qtbot):
    dialog = dialogs.EventCodesDialog(events.default_events(), events.DEFAULT_SAFE_MAX)
    qtbot.addWidget(dialog)
    assert dialog.get_safe_max() == events.DEFAULT_SAFE_MAX
    dialog.safeMaxSpin.setValue(200)
    assert dialog.get_safe_max() == 200


def test_event_codes_dialog_get_events_returns_untouched_copies(qtbot):
    source = events.default_events()
    original_first_code = source[0].code
    dialog = dialogs.EventCodesDialog(source, events.DEFAULT_SAFE_MAX)
    qtbot.addWidget(dialog)

    result = dialog.get_events()
    assert len(result) == len(source)
    # Edit the first row's code in the dialog; the result reflects it...
    dialog._code_spins[0].setValue(123)
    assert dialog.get_events()[0].code == 123
    # ...but the caller's original list is untouched (the dialog edits copies).
    assert source[0].code == original_first_code


def test_event_codes_dialog_suggested_code_is_one_past_max(qtbot):
    source = events.default_events()
    dialog = dialogs.EventCodesDialog(source, events.DEFAULT_SAFE_MAX)
    qtbot.addWidget(dialog)
    highest = max(e.code for e in source)
    expected = min(highest + 1, events.CODE_MAX)
    assert dialog._suggested_code() == expected


def test_event_codes_dialog_remove_custom_event(qtbot):
    source = events.default_events() + [_custom("Custom test", 150)]
    dialog = dialogs.EventCodesDialog(source, events.DEFAULT_SAFE_MAX)
    qtbot.addWidget(dialog)
    dialog.table.selectRow(len(source) - 1)  # the custom row
    dialog._remove_selected()
    labels = [e.label for e in dialog.get_events()]
    assert "Custom test" not in labels
    assert len(dialog.get_events()) == len(source) - 1


def test_event_codes_dialog_add_event(qtbot, monkeypatch):
    class _StubAddDialog:
        def __init__(self, *args, **kwargs):
            pass

        def exec(self):
            return 1  # accepted

        def get_inputs(self):
            return ("New event", 199, "tip", False)

    monkeypatch.setattr(dialogs, "AddEventDialog", _StubAddDialog)
    dialog = dialogs.EventCodesDialog(events.default_events(), events.DEFAULT_SAFE_MAX)
    qtbot.addWidget(dialog)
    before = len(dialog.get_events())
    dialog._add_event()
    after = dialog.get_events()
    assert len(after) == before + 1
    assert any(e.label == "New event" for e in after)
