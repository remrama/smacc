"""Tests for launcher logic that needs no GUI (initial-settings resolution)."""

from __future__ import annotations

from smacc import launcher
from smacc.cuedesigner import CueDesignerWindow
from smacc.launcher import LauncherWindow, resolve_initial_settings


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


def test_design_cues_button_opens_the_cue_designer(qtbot, tmp_path, monkeypatch):
    # Point preferences at a temp file so building the launcher can't touch real prefs.
    monkeypatch.setattr(launcher, "preferences_path", tmp_path / "preferences.yaml")
    win = LauncherWindow(settings_path=None)
    qtbot.addWidget(win)
    win.show()
    win.design_cues()
    assert isinstance(win._tool, CueDesignerWindow)
    assert win._tool.isVisible()  # the tool shows itself
    assert not win.isVisible()  # and the launcher hides until it closes
    win._tool.close()  # returns control to the launcher (it reappears)
    assert win.isVisible()


# ----- a .smacc must load before it is opened or remembered (#186) ------------


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


def _write_incompatible(path):
    path.write_text(
        "kind: smacc/settings\nschema_version: 99\nsettings: {}\n", encoding="utf-8"
    )


def test_incompatible_launch_file_is_rejected_and_kept_out_of_recents(
    qtbot, tmp_path, monkeypatch
):
    from smacc import preferences

    prefs_path = tmp_path / "preferences.yaml"
    monkeypatch.setattr(launcher, "preferences_path", prefs_path)
    bad = tmp_path / "old.smacc"
    _write_incompatible(bad)
    popups = _silence_critical(monkeypatch)
    win = LauncherWindow(settings_path=str(bad))
    qtbot.addWidget(win)
    assert win.settings_path is None  # rejected → built-in defaults stay selected
    assert len(popups) == 1  # and the user was told why
    recents = preferences.load_preferences(prefs_path).get("recent_settings", [])
    assert str(bad) not in recents


def test_valid_launch_file_is_selected_and_remembered(qtbot, tmp_path, monkeypatch):
    from smacc import preferences, settings

    prefs_path = tmp_path / "preferences.yaml"
    monkeypatch.setattr(launcher, "preferences_path", prefs_path)
    good = tmp_path / "study.smacc"
    settings.save_settings(good, {}, {})
    win = LauncherWindow(settings_path=str(good))
    qtbot.addWidget(win)
    assert win.settings_path == str(good)
    recents = preferences.load_preferences(prefs_path).get("recent_settings", [])
    assert str(good) in recents


def test_failed_selection_drops_a_stale_entry_from_recents(
    qtbot, tmp_path, monkeypatch
):
    from smacc import preferences

    # A file that was fine when remembered but is incompatible now must not
    # keep resurfacing in the dropdown.
    prefs_path = tmp_path / "preferences.yaml"
    monkeypatch.setattr(launcher, "preferences_path", prefs_path)
    bad = tmp_path / "old.smacc"
    _write_incompatible(bad)
    preferences.update_preferences(prefs_path, {"recent_settings": [str(bad)]})
    _silence_critical(monkeypatch)
    win = LauncherWindow(settings_path=None)
    qtbot.addWidget(win)
    win._set_settings(str(bad))  # e.g. picked from the recents dropdown
    assert win.settings_path is None  # the selection did not change
    recents = preferences.load_preferences(prefs_path).get("recent_settings", [])
    assert str(bad) not in recents


def test_start_session_aborts_when_the_file_breaks_after_selection(
    qtbot, tmp_path, monkeypatch
):
    from smacc import settings

    monkeypatch.setattr(launcher, "preferences_path", tmp_path / "preferences.yaml")
    good = tmp_path / "study.smacc"
    settings.save_settings(good, {}, {})
    _silence_critical(monkeypatch)
    win = LauncherWindow(settings_path=str(good))
    qtbot.addWidget(win)
    good.write_text("not: [valid", encoding="utf-8")  # corrupted after selection
    win.start_session()
    assert win._tool is None  # no session window was constructed
    assert win.settings_path is None  # selection fell back to the defaults
    # The double-click flow starts a session before the launcher is ever shown;
    # on rejection the launcher must come up rather than leave no window at all.
    assert win.isVisible()


# ----- the start-of-session metadata prompt (#184) ----------------------------


def test_start_session_prompts_and_passes_metadata(qtbot, tmp_path, monkeypatch):
    from smacc.toolwindow import ToolWindow

    monkeypatch.setattr(launcher, "preferences_path", tmp_path / "preferences.yaml")
    captured = {}

    class FakeSession:
        def __init__(self, data_dir, metadata=None):
            captured["metadata"] = metadata

    monkeypatch.setattr(launcher, "SmaccSession", FakeSession)
    monkeypatch.setattr(
        launcher, "SmaccWindow", lambda session, settings_path=None: ToolWindow()
    )
    entered = {"subject": "sub-001", "session": "ses-02", "notes": "first night"}
    monkeypatch.setattr(
        LauncherWindow, "_prompt_session_info", lambda self: dict(entered)
    )
    win = LauncherWindow(settings_path=None)
    qtbot.addWidget(win)
    win.start_session()
    assert captured["metadata"] == entered
    assert win._tool is not None  # the session window was opened


def test_start_session_cancelled_prompt_aborts(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "preferences_path", tmp_path / "preferences.yaml")
    monkeypatch.setattr(LauncherWindow, "_prompt_session_info", lambda self: None)
    win = LauncherWindow(settings_path=None)
    qtbot.addWidget(win)
    win.start_session()
    assert win._tool is None  # no session was started
    # The double-click flow prompts before the launcher is ever shown; on Cancel
    # the launcher must come up rather than leave no window at all.
    assert win.isVisible()


def test_prompt_session_info_prefills_from_the_smacc_file(qtbot, tmp_path, monkeypatch):
    from smacc import dialogs, settings

    monkeypatch.setattr(launcher, "preferences_path", tmp_path / "preferences.yaml")
    good = tmp_path / "study.smacc"
    settings.save_settings(
        good, {}, {"subject": "sub-001", "session": "ses-02", "notes": "template"}
    )
    monkeypatch.setattr(dialogs.SessionInfoDialog, "exec", lambda self: True)
    win = LauncherWindow(settings_path=str(good))
    qtbot.addWidget(win)
    assert win._prompt_session_info() == {
        "subject": "sub-001",
        "session": "ses-02",
        "notes": "template",
    }
