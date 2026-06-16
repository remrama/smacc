"""Tests for launching the EEG Annotator from the launcher (#136).

The Annotator is a mode of the single SMACC binary: :func:`smacc.eeg.launch`
re-execs this binary with ``--eeg`` as a detached process (so it can outlive the
launcher), and ``smacc.__main__`` routes ``--eeg`` to its entry point. MNE ships
inside the one binary, so the launcher button is always enabled.
"""

from __future__ import annotations

import sys

import pytest
from PyQt6 import QtCore, QtWidgets

import smacc.eeg as eeg
from smacc import launcher
from smacc.launcher import LauncherWindow

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


def test_launch_in_development_reexecs_the_module(spawned):
    assert eeg.launch()
    assert spawned == [(sys.executable, ["-m", "smacc", "--eeg"])]


def test_launch_frozen_reexecs_itself(spawned, monkeypatch):
    # The frozen build re-execs SMACC.exe itself with --eeg — there is no
    # separate exe, and sys.executable is the SMACC.exe being run.
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert eeg.launch()
    assert spawned == [(sys.executable, ["--eeg"])]


def test_launch_forwards_extra_args_in_development(spawned):
    # The Analyzer "open in annotator" handoff passes --log; it must reach the
    # binary after the --eeg flag.
    assert eeg.launch(["--log", "night1.log"])
    assert spawned == [
        (sys.executable, ["-m", "smacc", "--eeg", "--log", "night1.log"])
    ]


def test_launch_forwards_extra_args_when_frozen(spawned, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert eeg.launch(["--log", "night1.log"])
    assert spawned == [(sys.executable, ["--eeg", "--log", "night1.log"])]


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


def test_button_launches_and_keeps_the_launcher_visible(make_launcher, spawned):
    win = make_launcher()
    assert win.reviewEegButton.isEnabled()
    win.reviewEegButton.click()
    assert len(spawned) == 1
    # Unlike launcher-managed tools, the Annotator is a sibling process: the
    # launcher must stay up (there is no closed signal to bring it back).
    assert win.isVisible()


def test_failed_launch_shows_a_warning(make_launcher, monkeypatch):
    monkeypatch.setattr(eeg, "launch", lambda args=None: False)
    warnings: list[str] = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda parent, title, text: warnings.append(text),
    )
    win = make_launcher()
    win.review_eeg()
    assert len(warnings) == 1
    assert "EEG Annotator" in warnings[0]
