"""Tests for launcher logic that needs no GUI (initial-settings resolution)."""

from __future__ import annotations

from smacc import launcher
from smacc.launcher import resolve_initial_settings


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
