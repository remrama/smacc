"""Tests for the hardware-free Study Editor window (#301).

These build the real :class:`~smacc.studyeditor.StudyEditorWindow` with no session
and no hardware — the whole point of the editor — and exercise its file lifecycle:
load a ``.smacc`` into the model, save it back byte-stable, track unsaved changes,
and refuse to clobber the bundled template.
"""

from __future__ import annotations

from smacc import settings, studyconfig
from smacc.paths import DEFAULT_SETTINGS_PATH
from smacc.studyconfig import StudyConfig
from smacc.studyeditor import StudyEditorWindow


def _sample_settings(base) -> dict:
    """A representative study with path-bearing slots, in canonical model form.

    Paths are absolute under ``base`` so :func:`settings.relativize_paths` resolves
    them deterministically (independent of the test's working directory).
    """
    raw = {
        "cues": [
            studyconfig.cue_to_dict(
                studyconfig.AudioCue("Buzz", str(base / "cues" / "buzz.wav"), 0.3, True)
            )
        ],
        "noise_color": "pink",
        "noise_source": "file",
        "noise_file": str(base / "noise" / "pink.wav"),
        "survey_options": {"Morning": "https://example.com/m"},
        "chat_font_size": 22,
        "data_directory": str(base / "data"),
        "event_code_safe_max": 200,
    }
    return StudyConfig.from_settings_dict(raw).to_settings_dict()


def _write_smacc(path, settings_map, meta, base) -> None:
    settings.save_settings(
        str(path), settings.relativize_paths(settings_map, base), meta
    )


def test_fresh_editor_has_default_config_and_no_file(qtbot, silence_dialogs):
    editor = StudyEditorWindow()
    qtbot.addWidget(editor)
    assert editor.settings_path is None
    assert editor.config.to_settings_dict() == StudyConfig().to_settings_dict()
    assert not editor.has_unsaved_changes()


def test_editor_loads_a_smacc_file_into_the_model(qtbot, silence_dialogs, tmp_path):
    full = _sample_settings(tmp_path)
    meta = {"subject": "s1", "session": "n1", "notes": ""}
    path = tmp_path / "study.smacc"
    _write_smacc(path, full, meta, tmp_path)

    editor = StudyEditorWindow(str(path))
    qtbot.addWidget(editor)
    assert editor.settings_path == str(path)
    assert editor.config.cueing.audio.cues[0].name == "Buzz"
    assert editor.config.cueing.noise.color == "pink"
    assert editor.config.interface.chat_font_size == 22
    assert editor.metadata["subject"] == "s1"  # file metadata adopted
    assert not editor.has_unsaved_changes()  # freshly loaded ⇒ clean


def test_editor_save_round_trips_byte_stable(qtbot, silence_dialogs, tmp_path):
    # The window-level keystone: a study loaded then re-saved through the editor is
    # byte-identical, so the editor's save is a faithful, stable .smacc.
    full = _sample_settings(tmp_path)
    meta = {"subject": "s1", "session": "n1", "notes": ""}
    path1 = tmp_path / "study.smacc"
    _write_smacc(path1, full, meta, tmp_path)

    editor = StudyEditorWindow(str(path1))
    qtbot.addWidget(editor)
    path2 = tmp_path / "study2.smacc"
    assert editor._write(str(path2)) is True
    assert path1.read_text(encoding="utf-8") == path2.read_text(encoding="utf-8")


def test_editing_an_unformed_section_marks_unsaved_then_save_clears_it(
    qtbot, silence_dialogs, tmp_path
):
    # surveys has no form yet, so a programmatic edit there isn't overwritten by a
    # form commit — this exercises the snapshot/dirty machinery for sections whose
    # values round-trip untouched.
    editor = StudyEditorWindow()
    qtbot.addWidget(editor)
    assert not editor.has_unsaved_changes()
    editor.config.surveys.url = "smacc://survey/lusk"
    assert editor.has_unsaved_changes()
    assert editor._write(str(tmp_path / "s.smacc")) is True
    assert not editor.has_unsaved_changes()  # saving rebaselines the snapshot


def test_editor_refuses_to_overwrite_the_default_template(qtbot, silence_dialogs):
    editor = StudyEditorWindow()
    qtbot.addWidget(editor)
    assert editor._write(str(DEFAULT_SETTINGS_PATH)) is False
    assert editor.settings_path is None  # nothing was written; path unchanged


def test_editor_emits_closed_when_clean(qtbot, silence_dialogs):
    editor = StudyEditorWindow()
    qtbot.addWidget(editor)
    with qtbot.waitSignal(editor.closed, timeout=1000):
        editor.close()


# ----- section forms ---------------------------------------------------------


def test_forms_reflect_a_loaded_study(qtbot, silence_dialogs, tmp_path):
    full = _sample_settings(tmp_path)
    path = tmp_path / "study.smacc"
    _write_smacc(path, full, {"subject": "", "session": "", "notes": ""}, tmp_path)

    editor = StudyEditorWindow(str(path))
    qtbot.addWidget(editor)
    assert editor._forms["data"].edit.text() == str(tmp_path / "data")
    assert editor._forms["noise"].color.currentText() == "pink"
    assert editor._forms["noise"].fileRadio.isChecked()  # source == file
    assert editor._forms["interface"].fontSize.value() == 22
    assert not editor.has_unsaved_changes()  # load → commit is the identity


def test_editing_a_form_widget_round_trips_through_save(
    qtbot, silence_dialogs, tmp_path
):
    editor = StudyEditorWindow()
    qtbot.addWidget(editor)
    editor._forms["noise"].volume.setValue(0.55)
    editor._forms["interface"].redText.setChecked(True)
    assert editor.has_unsaved_changes()

    path = tmp_path / "edited.smacc"
    assert editor._write(str(path)) is True
    assert not editor.has_unsaved_changes()

    reloaded = StudyEditorWindow(str(path))
    qtbot.addWidget(reloaded)
    assert reloaded.config.cueing.noise.volume == 0.55
    assert reloaded.config.interface.chat_red_text is True
    assert reloaded._forms["noise"].volume.value() == 0.55
