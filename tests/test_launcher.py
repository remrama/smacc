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
