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

from smacc import dialogs, events, surveys, triggers

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
    assert survey.items == ("First item", "Second item")
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


# ----- TriggerOutputDialog ---------------------------------------------------


@pytest.fixture
def stub_serial_ports(monkeypatch):
    """Pin the serial-port list so these tests don't depend on the machine's ports.

    Includes a described port (label != device) and a bare one, so the device
    resolution is exercised regardless of what COM ports the CI runner exposes.
    """
    ports = [("COM2", "USB Serial Device"), ("COM5", "COM5")]
    monkeypatch.setattr(triggers, "list_serial_ports", lambda: ports)
    return ports


def test_trigger_output_dialog_round_trips_config(qtbot, stub_serial_ports):
    cfg = triggers.TriggerConfig(
        enabled=True, transport="serial", port="COM9", baud=9600, mode="hold"
    )
    dialog = dialogs.TriggerOutputDialog(cfg)
    qtbot.addWidget(dialog)
    out = dialog.get_config()
    assert out.enabled is True
    assert out.transport == "serial"
    # COM9 isn't attached but other ports are: it must survive as typed text, not
    # snap to a listed port (regression: editable combo's stale currentData()).
    assert out.port == "COM9"
    assert out.baud == 9600
    assert out.mode == "hold"


def test_trigger_output_dialog_selecting_listed_port_returns_device(
    qtbot, stub_serial_ports
):
    # A listed port is shown with its description ("COM2 — USB Serial Device") but
    # get_config resolves it back to the bare device name.
    dialog = dialogs.TriggerOutputDialog(
        triggers.TriggerConfig(enabled=True, transport="serial", port="COM2")
    )
    qtbot.addWidget(dialog)
    assert dialog.get_config().port == "COM2"


def test_trigger_output_dialog_reflects_edits(qtbot):
    dialog = dialogs.TriggerOutputDialog(triggers.TriggerConfig())
    qtbot.addWidget(dialog)
    dialog.enabledBox.setChecked(True)
    dialog._select_data(dialog.transportCombo, "parallel")
    dialog.addressEdit.setText("0x278")
    out = dialog.get_config()
    assert out.enabled is True
    assert out.transport == "parallel"
    assert out.address == "0x278"


def test_trigger_output_dialog_disabled_greys_config(qtbot):
    dialog = dialogs.TriggerOutputDialog(triggers.TriggerConfig(enabled=False))
    qtbot.addWidget(dialog)
    assert dialog._config_widget.isEnabled() is False
    dialog.enabledBox.setChecked(True)
    assert dialog._config_widget.isEnabled() is True


def test_trigger_output_dialog_test_button_reports_result(qtbot, stub_serial_ports):
    calls = []

    def fake_test(config):
        calls.append(config)
        return None  # success

    dialog = dialogs.TriggerOutputDialog(
        triggers.TriggerConfig(enabled=True, port="COM3"), test_callback=fake_test
    )
    qtbot.addWidget(dialog)
    dialog._on_test()
    assert len(calls) == 1 and calls[0].port == "COM3"
    assert "✓" in dialog.testResult.text()


def test_trigger_output_dialog_test_button_shows_error(qtbot):
    dialog = dialogs.TriggerOutputDialog(
        triggers.TriggerConfig(enabled=True), test_callback=lambda cfg: "no such port"
    )
    qtbot.addWidget(dialog)
    dialog._on_test()
    assert "no such port" in dialog.testResult.text()
