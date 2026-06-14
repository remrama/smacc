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

from smacc import config, dialogs, settings, surveys

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


# ----- SMACC-file selection (the launcher's Session… / Editor… dialogs) -------


def _write_incompatible(path):
    path.write_text(
        "kind: smacc/settings\nschema_version: 99\nsettings: {}\n", encoding="utf-8"
    )


def test_validate_settings_file_accepts_a_loadable_file(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(dialogs, "preferences_path", tmp_path / "preferences.yaml")
    good = tmp_path / "study.smacc"
    settings.save_settings(good, {}, {})
    assert dialogs.validate_settings_file(str(good)) is True


def test_validate_settings_file_rejects_and_drops_from_recents(
    qtbot, tmp_path, monkeypatch
):
    from smacc import preferences

    prefs_path = tmp_path / "preferences.yaml"
    monkeypatch.setattr(dialogs, "preferences_path", prefs_path)
    bad = tmp_path / "old.smacc"
    _write_incompatible(bad)
    preferences.update_preferences(prefs_path, {"recent_settings": [str(bad)]})
    calls: list[tuple] = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "critical", lambda *a, **k: calls.append(a)
    )
    assert dialogs.validate_settings_file(str(bad)) is False  # #186
    assert calls  # the user was told why
    recents = preferences.load_preferences(prefs_path).get("recent_settings", [])
    assert str(bad) not in recents  # and it won't keep resurfacing in the picker


def test_file_combo_browse_validates_and_remembers(qtbot, tmp_path, monkeypatch):
    from smacc import preferences

    prefs_path = tmp_path / "preferences.yaml"
    monkeypatch.setattr(dialogs, "preferences_path", prefs_path)
    good = tmp_path / "study.smacc"
    settings.save_settings(good, {}, {})
    monkeypatch.setattr(
        QtWidgets.QFileDialog, "getOpenFileName", lambda *a, **k: (str(good), "")
    )
    combo = dialogs.SmaccFileCombo()
    qtbot.addWidget(combo)
    combo._browse()  # the Browse… entry's handler
    assert combo.chosen_path() == str(good)
    recents = preferences.load_preferences(prefs_path).get("recent_settings", [])
    assert str(good) in recents


def test_file_combo_surfaces_a_preselect_that_is_not_a_recent(
    qtbot, tmp_path, monkeypatch
):
    monkeypatch.setattr(dialogs, "preferences_path", tmp_path / "preferences.yaml")
    good = tmp_path / "study.smacc"
    settings.save_settings(good, {}, {})
    # A freshly double-clicked file isn't in recents yet; it must still be the
    # selection rather than silently dropping to "default".
    combo = dialogs.SmaccFileCombo(preselect=str(good))
    qtbot.addWidget(combo)
    assert combo.chosen_path() == str(good)


def test_start_session_dialog_prefills_metadata_from_the_file(
    qtbot, tmp_path, monkeypatch
):
    monkeypatch.setattr(dialogs, "preferences_path", tmp_path / "preferences.yaml")
    good = tmp_path / "study.smacc"
    settings.save_settings(
        good, {}, {"subject": "sub-001", "session": "ses-02", "notes": "template"}
    )
    dialog = dialogs.StartSessionDialog(preselect=str(good))
    qtbot.addWidget(dialog)
    assert dialog.chosen_path() == str(good)
    assert dialog.get_inputs() == ("sub-001", "ses-02", "template")  # #184


def test_start_session_dialog_tolerates_an_unloadable_preselect(
    qtbot, tmp_path, monkeypatch
):
    # A last-used file that has since become corrupt is still selectable, but its
    # metadata can't be read; the dialog must degrade to blank fields, not crash
    # (the launcher re-validates and blocks the start before a session opens).
    monkeypatch.setattr(dialogs, "preferences_path", tmp_path / "preferences.yaml")
    broken = tmp_path / "broken.smacc"
    _write_incompatible(broken)
    dialog = dialogs.StartSessionDialog(preselect=str(broken))
    qtbot.addWidget(dialog)
    assert dialog.get_inputs() == ("", "", "")


def test_editor_file_dialog_defaults_to_new(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(dialogs, "preferences_path", tmp_path / "preferences.yaml")
    dialog = dialogs.EditorFileDialog()
    qtbot.addWidget(dialog)
    assert dialog.is_new() is True  # "New SMACC file" leads the list
    assert dialog.chosen_path() is None


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


def _demo_survey(name="Demo", key="demo"):
    return surveys.parse_survey_mapping(
        {
            "kind": surveys.KIND,
            "schema_version": 1,
            "key": key,
            "name": name,
            "title": f"{name} survey",
            "scale": {"min": 0, "max": 2, "anchors": []},
            "items": ["First item", "Second item"],
        }
    )


def test_manage_surveys_lists_files_and_persists_urls_only(qtbot, tmp_path):
    builtin_dir = tmp_path / "builtin"
    user_dir = tmp_path / "user"
    surveys.save_survey(_demo_survey(), builtin_dir)
    options = {"Post survey": "https://a.example"}
    dialog = dialogs.ManageSurveysDialog(options, builtin_dir, user_dir)
    qtbot.addWidget(dialog)
    assert dialog.listWidget.count() == 2  # the built-in row + the URL row
    assert dialog.get_options() == options  # file-backed rows never persist
    assert dialog.files_changed is False


def test_manage_surveys_builtin_cannot_be_removed(qtbot, tmp_path, monkeypatch):
    builtin_dir = tmp_path / "builtin"
    path = surveys.save_survey(_demo_survey(), builtin_dir)
    informed = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "information", lambda *a, **k: informed.append(a)
    )
    dialog = dialogs.ManageSurveysDialog({}, builtin_dir, tmp_path / "user")
    qtbot.addWidget(dialog)
    dialog.listWidget.setCurrentRow(0)
    dialog._remove_selected()
    assert informed and path.is_file() and dialog.files_changed is False


def test_manage_surveys_remove_custom_deletes_file(qtbot, tmp_path, monkeypatch):
    user_dir = tmp_path / "user"
    path = surveys.save_survey(_demo_survey(), user_dir)
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "question",
        lambda *a, **k: QtWidgets.QMessageBox.StandardButton.Yes,
    )
    dialog = dialogs.ManageSurveysDialog({}, tmp_path / "builtin", user_dir)
    qtbot.addWidget(dialog)
    dialog.listWidget.setCurrentRow(0)
    dialog._remove_selected()
    assert not path.exists()
    assert dialog.files_changed is True
    assert dialog.listWidget.count() == 0


def test_manage_surveys_save_custom_writes_and_reloads(qtbot, tmp_path):
    user_dir = tmp_path / "user"
    dialog = dialogs.ManageSurveysDialog({}, tmp_path / "builtin", user_dir)
    qtbot.addWidget(dialog)
    dialog._save_custom(_demo_survey(name="Mine", key="mine"))
    assert (user_dir / "mine.yaml").is_file()
    assert dialog.files_changed is True
    assert dialog.listWidget.count() == 1


def test_manage_surveys_guards_editing_typed_survey(qtbot, tmp_path, monkeypatch):
    # A custom survey with typed items (#118) can't round-trip through the simple
    # builder, so View/Edit explains that instead of opening (and mangling) it.
    user_dir = tmp_path / "user"
    typed = surveys.parse_survey_mapping(
        {
            "kind": surveys.KIND,
            "schema_version": 1,
            "key": "mine",
            "name": "Mine",
            "title": "Mine",
            "items": [{"text": "Occupation", "type": "text"}],
        }
    )
    surveys.save_survey(typed, user_dir)
    informed = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "information", lambda *a, **k: informed.append(a)
    )
    monkeypatch.setattr(
        dialogs.BuildSurveyDialog, "exec", lambda self: pytest.fail("builder opened")
    )
    dialog = dialogs.ManageSurveysDialog({}, tmp_path / "builtin", user_dir)
    qtbot.addWidget(dialog)
    dialog.listWidget.setCurrentRow(0)
    dialog._view_or_edit_selected()  # would fail if it opened the builder
    assert informed and dialog.files_changed is False


# ----- BuildSurveyDialog -------------------------------------------------------


def test_build_survey_dialog_returns_validated_survey(qtbot):
    dialog = dialogs.BuildSurveyDialog(existing_keys=("demo",))
    qtbot.addWidget(dialog)
    dialog.nameEdit.setText("My Scale")
    dialog.minSpin.setValue(1)
    dialog.maxSpin.setValue(3)
    dialog.anchorsEdit.setPlainText("Low\nMid\nHigh")
    dialog.itemsEdit.setPlainText("First item\n\nSecond item\n")
    dialog._on_accept()
    survey = dialog.get_survey()
    assert survey.key == "my-scale"
    assert survey.title == "My Scale"  # defaults to the name
    assert survey.scale_min == 1 and survey.scale_max == 3
    assert survey.anchors == ("Low", "Mid", "High")
    assert [it.text for it in survey.items] == ["First item", "Second item"]
    assert all(it.type == surveys.LIKERT for it in survey.items)
    assert survey.is_simple_likert  # the builder only makes shared-scale Likert
    assert survey.builtin is False


def test_build_survey_dialog_rejects_anchor_mismatch(qtbot, monkeypatch):
    warned = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "warning", lambda *a, **k: warned.append(a)
    )
    dialog = dialogs.BuildSurveyDialog()
    qtbot.addWidget(dialog)
    dialog.nameEdit.setText("Broken")
    dialog.anchorsEdit.setPlainText("only\ntwo")  # 0..4 needs five
    dialog.itemsEdit.setPlainText("An item")
    dialog._on_accept()
    assert warned
    assert dialog.result() != QtWidgets.QDialog.DialogCode.Accepted


def test_build_survey_dialog_edit_keeps_key_and_dodges_taken_keys(qtbot):
    edited = dialogs.BuildSurveyDialog(_demo_survey(name="Demo", key="demo"))
    qtbot.addWidget(edited)
    edited.nameEdit.setText("Renamed Demo")
    edited._on_accept()
    assert edited.get_survey().key == "demo"  # key is stable across renames

    fresh = dialogs.BuildSurveyDialog(existing_keys=("fresh",))
    qtbot.addWidget(fresh)
    fresh.nameEdit.setText("Fresh")
    fresh.itemsEdit.setPlainText("An item")
    fresh._on_accept()
    assert fresh.get_survey().key == "fresh-2"


# ----- ManageChatPresetsDialog (#112) ----------------------------------------


def test_manage_chat_presets_round_trips_both_lists(qtbot):
    dialog = dialogs.ManageChatPresetsDialog(
        ["Are you awake?", "Going back to sleep now."], ["Got it", "Yes"]
    )
    qtbot.addWidget(dialog)
    experimenter, participant = dialog.get_presets()
    assert experimenter == ["Are you awake?", "Going back to sleep now."]
    assert participant == ["Got it", "Yes"]


def test_manage_chat_presets_reorders_participant_replies(qtbot):
    # Order is meaningful: it maps to the number keys, so rows can be moved.
    dialog = dialogs.ManageChatPresetsDialog([], ["Yes", "No", "Maybe"])
    qtbot.addWidget(dialog)
    editor = dialog._participant
    editor.listWidget.setCurrentRow(2)
    editor._move(-1)  # "Maybe" moves up past "No"
    assert dialog.get_presets()[1] == ["Yes", "Maybe", "No"]
    editor.listWidget.setCurrentRow(0)
    editor._move(-1)  # already at the top: a no-op
    assert dialog.get_presets()[1] == ["Yes", "Maybe", "No"]


def test_manage_chat_presets_remove_selected(qtbot):
    dialog = dialogs.ManageChatPresetsDialog(["A", "B"], ["Yes"])
    qtbot.addWidget(dialog)
    dialog._experimenter.listWidget.setCurrentRow(0)
    dialog._experimenter._remove_selected()
    assert dialog.get_presets()[0] == ["B"]


def test_manage_chat_presets_caps_participant_replies(qtbot, monkeypatch):
    full = [f"r{i}" for i in range(config.MAX_PARTICIPANT_PRESETS)]
    dialog = dialogs.ManageChatPresetsDialog([], full)
    qtbot.addWidget(dialog)
    # At the cap, Add warns (a blocking QMessageBox) and refuses to grow the list.
    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda *a, **k: None)
    dialog._participant._add()
    assert len(dialog.get_presets()[1]) == config.MAX_PARTICIPANT_PRESETS


def test_manage_chat_presets_add_trims_via_input_dialog(qtbot, monkeypatch):
    dialog = dialogs.ManageChatPresetsDialog(["A"], [])
    qtbot.addWidget(dialog)
    monkeypatch.setattr(
        QtWidgets.QInputDialog, "getText", lambda *a, **k: ("  Are you awake?  ", True)
    )
    dialog._experimenter._add()
    assert dialog.get_presets()[0] == ["A", "Are you awake?"]


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
