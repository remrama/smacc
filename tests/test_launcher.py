"""Tests for launcher logic: initial-settings resolution and the tool buttons.

File selection + the validate-then-remember rule (#186) and metadata prefill
(#184) now live in the launcher's dialogs (smacc.dialogs) and are covered in
tests/test_dialogs.py; here we cover what the launcher itself does with the
dialogs' results.
"""

from __future__ import annotations

from smacc import launcher
from smacc.cuedesigner import CueDesignerWindow
from smacc.launcher import LauncherWindow, resolve_initial_settings
from smacc.toolwindow import ToolWindow


def _patch_prefs(monkeypatch, tmp_path):
    """Point both launcher and dialogs at a throwaway preferences file."""
    from smacc import dialogs

    prefs_path = tmp_path / "preferences.yaml"
    monkeypatch.setattr(launcher, "preferences_path", prefs_path)
    monkeypatch.setattr(dialogs, "preferences_path", prefs_path)
    return prefs_path


def _silence_critical(monkeypatch):
    """Replace the blocking error popup with a recorder; returns the call list."""
    from PyQt6 import QtWidgets

    calls: list[tuple] = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "critical",
        lambda *a, **k: calls.append(a) or QtWidgets.QMessageBox.StandardButton.Ok,
    )
    return calls


# ----- initial-settings resolution -------------------------------------------


def test_resolve_initial_settings_prefers_last_used(tmp_path):
    last = tmp_path / "peter.smacc"
    last.write_text("kind: smacc/settings\n", encoding="utf-8")
    assert resolve_initial_settings({"last_settings": str(last)}) == str(last)


def test_resolve_initial_settings_falls_back_to_default(tmp_path, monkeypatch):
    default = tmp_path / "default.smacc"
    default.write_text("kind: smacc/settings\n", encoding="utf-8")
    monkeypatch.setattr(launcher, "DEFAULT_SETTINGS_PATH", default)
    assert resolve_initial_settings({"last_settings": None}) == str(default)


def test_resolve_initial_settings_none_when_nothing_available(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "DEFAULT_SETTINGS_PATH", tmp_path / "missing.smacc")
    # Stale last-settings path is ignored; no default present → built-in defaults.
    assert (
        resolve_initial_settings({"last_settings": str(tmp_path / "gone.smacc")})
        is None
    )


# ----- a tool button opens its tool and hides the launcher --------------------


def test_design_cues_button_opens_the_cue_designer(qtbot, tmp_path, monkeypatch):
    _patch_prefs(monkeypatch, tmp_path)
    win = LauncherWindow()
    qtbot.addWidget(win)
    win.show()
    win.design_cues()
    assert isinstance(win._tool, CueDesignerWindow)
    assert win._tool.isVisible()  # the tool shows itself
    assert not win.isVisible()  # and the launcher hides until it closes
    win._tool.close()  # returns control to the launcher (it reappears)
    assert win.isVisible()


# ----- Session…: open the dialog, then run a session with its result ----------


def test_open_session_starts_with_the_chosen_file_and_metadata(
    qtbot, tmp_path, monkeypatch
):
    from smacc import dialogs, settings

    _patch_prefs(monkeypatch, tmp_path)
    good = tmp_path / "study.smacc"
    settings.save_settings(good, {}, {})
    captured = {}

    class FakeSession:
        def __init__(self, data_dir, metadata=None):
            captured["metadata"] = metadata

    monkeypatch.setattr(launcher, "SmaccSession", FakeSession)
    monkeypatch.setattr(
        launcher, "SmaccWindow", lambda session, settings_path=None: ToolWindow()
    )
    monkeypatch.setattr(dialogs.StartSessionDialog, "exec", lambda self: True)
    monkeypatch.setattr(
        dialogs.StartSessionDialog, "chosen_path", lambda self: str(good)
    )
    monkeypatch.setattr(
        dialogs.StartSessionDialog,
        "get_inputs",
        lambda self: ("sub-001", "ses-02", "first night"),
    )
    win = LauncherWindow()
    qtbot.addWidget(win)
    win._open_session()
    assert captured["metadata"] == {
        "subject": "sub-001",
        "session": "ses-02",
        "notes": "first night",
    }
    assert win._tool is not None  # the session window was opened


def test_open_session_cancelled_aborts_and_shows_the_launcher(
    qtbot, tmp_path, monkeypatch
):
    from smacc import dialogs

    _patch_prefs(monkeypatch, tmp_path)
    monkeypatch.setattr(dialogs.StartSessionDialog, "exec", lambda self: False)
    win = LauncherWindow()
    qtbot.addWidget(win)
    win._open_session()
    assert win._tool is None  # no session started
    # The double-click flow opens this dialog before the launcher is shown; on
    # Cancel the launcher must come up rather than leave no window at all.
    assert win.isVisible()


def test_open_session_aborts_when_the_chosen_file_breaks_after_the_dialog(
    qtbot, tmp_path, monkeypatch
):
    from smacc import dialogs, settings

    _patch_prefs(monkeypatch, tmp_path)
    good = tmp_path / "study.smacc"
    settings.save_settings(good, {}, {})
    _silence_critical(monkeypatch)
    monkeypatch.setattr(dialogs.StartSessionDialog, "exec", lambda self: True)
    monkeypatch.setattr(
        dialogs.StartSessionDialog, "chosen_path", lambda self: str(good)
    )
    win = LauncherWindow()
    qtbot.addWidget(win)
    good.write_text("not: [valid", encoding="utf-8")  # corrupted after the dialog
    win._open_session()
    assert win._tool is None  # the re-check (#186) blocked the session
    assert win.isVisible()


# ----- Editor…: New file vs an existing one -----------------------------------


def test_open_editor_new_opens_a_blank_editor(qtbot, tmp_path, monkeypatch):
    from smacc import dialogs

    _patch_prefs(monkeypatch, tmp_path)
    captured = {}
    monkeypatch.setattr(
        launcher,
        "StudyEditorWindow",
        lambda settings_path=None: captured.update(path=settings_path) or ToolWindow(),
    )
    monkeypatch.setattr(dialogs.EditorFileDialog, "exec", lambda self: True)
    monkeypatch.setattr(dialogs.EditorFileDialog, "is_new", lambda self: True)
    win = LauncherWindow()
    qtbot.addWidget(win)
    win._open_editor()
    assert captured["path"] is None  # New → a fresh file (Save-As)
    assert win._tool is not None


def test_open_editor_existing_opens_that_file(qtbot, tmp_path, monkeypatch):
    from smacc import dialogs, settings

    _patch_prefs(monkeypatch, tmp_path)
    good = tmp_path / "study.smacc"
    settings.save_settings(good, {}, {})
    captured = {}
    monkeypatch.setattr(
        launcher,
        "StudyEditorWindow",
        lambda settings_path=None: captured.update(path=settings_path) or ToolWindow(),
    )
    monkeypatch.setattr(dialogs.EditorFileDialog, "exec", lambda self: True)
    monkeypatch.setattr(dialogs.EditorFileDialog, "is_new", lambda self: False)
    monkeypatch.setattr(dialogs.EditorFileDialog, "chosen_path", lambda self: str(good))
    win = LauncherWindow()
    qtbot.addWidget(win)
    win._open_editor()
    assert captured["path"] == str(good)


def test_editor_close_remembers_the_saved_file(
    qtbot, tmp_path, monkeypatch, silence_dialogs
):
    # Closing an editor that has a settings file returns to the launcher and
    # remembers that file (recents + last_settings) for the next Session…/Editor….
    from smacc import dialogs, preferences, settings
    from smacc.studyeditor import StudyEditorWindow

    prefs_path = _patch_prefs(monkeypatch, tmp_path)
    saved = tmp_path / "study.smacc"
    settings.save_settings(saved, {}, {})
    remembered: list[str] = []
    monkeypatch.setattr(dialogs, "remember_settings", remembered.append)

    win = LauncherWindow()
    qtbot.addWidget(win)
    editor = StudyEditorWindow(settings_path=str(saved))
    qtbot.addWidget(editor)
    win._tool = editor
    win._on_tool_closed()

    assert remembered == [str(saved)]
    assert preferences.load_preferences(prefs_path).get("last_settings") == str(saved)
    assert win.isVisible()  # the launcher came back (not quit, as a session would)


# ----- Rig setup: a standalone launcher tool (#300) ---------------------------


def test_setup_rig_button_opens_the_rig_setup_tool(
    qtbot, tmp_path, monkeypatch, mock_devices
):
    from smacc import hue, rigsetup
    from smacc.rigsetup import RigSetupWindow

    _patch_prefs(monkeypatch, tmp_path)
    monkeypatch.setattr(rigsetup, "preferences_path", tmp_path / "preferences.yaml")
    monkeypatch.setattr(hue, "targets", lambda cfg: [])  # no Hue network in tests
    win = LauncherWindow()
    qtbot.addWidget(win)
    win.show()
    win.setup_rig()
    assert isinstance(win._tool, RigSetupWindow)
    assert win._tool.isVisible()  # the tool shows itself
    assert not win.isVisible()  # and the launcher hides until it closes
    win._tool.close()  # returns control to the launcher (it reappears)
    assert win.isVisible()
