"""Tests for launching the optional EEG component from the launcher (#136).

Covers the availability probe (dev extra vs. frozen exe-beside-exe), the
detached-process launch, and the launcher's Review EEG button — which is shown
disabled (never hidden) when the component is absent, the same
surface-don't-hide approach as missing trigger hardware (#147).
"""

from __future__ import annotations

import sys

import pytest
from PyQt6 import QtCore, QtWidgets

import smacc.eeg as eeg
from smacc import launcher
from smacc.launcher import LauncherWindow

# ----- availability ----------------------------------------------------------


def test_available_in_development_needs_the_eeg_extra():
    # This test env has the extra installed, so the probe must say yes.
    assert eeg.available()


def test_available_in_development_without_the_extra(monkeypatch):
    monkeypatch.setattr(eeg, "find_spec", lambda name: None)
    assert not eeg.available()


def test_available_frozen_checks_for_the_exe(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "SMACC.exe"))
    assert not eeg.available()  # component not installed
    (tmp_path / eeg.EXE_NAME).write_bytes(b"")
    assert eeg.available()


def test_component_exe_sits_beside_the_main_exe(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "executable", str(tmp_path / "SMACC.exe"))
    assert eeg.component_exe() == tmp_path / eeg.EXE_NAME


# ----- launching ----------------------------------------------------------------


@pytest.fixture
def spawned(monkeypatch):
    """Capture detached-process launches instead of spawning anything."""
    calls: list[tuple[str, list[str]]] = []

    def fake_start(program, arguments=(), *args):
        calls.append((program, list(arguments)))
        return True, 4242

    monkeypatch.setattr(QtCore.QProcess, "startDetached", staticmethod(fake_start))
    return calls


def test_launch_in_development_runs_the_module(spawned):
    assert eeg.launch()
    assert spawned == [(sys.executable, ["-m", "smacc.eeg"])]


def test_launch_frozen_runs_the_component_exe(spawned, tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "SMACC.exe"))
    assert eeg.launch()
    assert spawned == [(str(tmp_path / eeg.EXE_NAME), [])]


# ----- the launcher button ----------------------------------------------------------


@pytest.fixture
def make_launcher(qtbot, tmp_path, monkeypatch):
    """Build a LauncherWindow with isolated prefs (the test_launcher pattern)."""
    monkeypatch.setattr(launcher, "preferences_path", tmp_path / "preferences.yaml")

    def build() -> LauncherWindow:
        win = LauncherWindow(settings_path=None)
        qtbot.addWidget(win)
        win.show()
        return win

    return build


def test_button_launches_and_keeps_the_launcher_visible(
    make_launcher, monkeypatch, spawned
):
    monkeypatch.setattr(eeg, "available", lambda: True)
    win = make_launcher()
    assert win.reviewEegButton.isEnabled()
    win.reviewEegButton.click()
    assert len(spawned) == 1
    # Unlike launcher-managed tools, the viewer is a sibling process: the
    # launcher must stay up (there is no closed signal to bring it back).
    assert win.isVisible()


def test_button_is_disabled_with_an_install_hint_when_absent(
    make_launcher, monkeypatch
):
    monkeypatch.setattr(eeg, "available", lambda: False)
    win = make_launcher()
    assert not win.reviewEegButton.isEnabled()
    assert "installer" in win.reviewEegButton.statusTip()


def test_failed_launch_shows_a_warning(make_launcher, monkeypatch):
    monkeypatch.setattr(eeg, "available", lambda: True)
    monkeypatch.setattr(eeg, "launch", lambda: False)
    warnings: list[str] = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda parent, title, text: warnings.append(text),
    )
    win = make_launcher()
    win.review_eeg()
    assert len(warnings) == 1
    assert "EEG Review Tools" in warnings[0]
