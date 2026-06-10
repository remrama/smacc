"""Tests for the Event logging panel (#121): the stage keypad and Signal observed.

The panel auto-builds its buttons from the manual registry. Two behaviors are
specific to the panel (not the registry): sleep-stage buttons take a fixed 0–4
keypad regardless of grid position, and the Signal observed button fires instantly
with the pre-armed signal type + confidence composed into the marker's log detail.
"""

from __future__ import annotations

from PyQt6 import QtWidgets

from smacc.panels.events import EventsWindow
from smacc.session import SmaccSession


def _events_window(tmp_path, qtbot):
    session = SmaccSession(tmp_path / "s", design=True)
    win = EventsWindow(session)
    qtbot.addWidget(win)
    return win, session


def _button_shortcuts(win) -> dict[str, str]:
    """Map each grid button's visible text -> its assigned shortcut string."""
    return {
        b.text(): b.shortcut().toString()
        for b in win.findChildren(QtWidgets.QPushButton)
    }


def test_sleep_stage_buttons_use_a_fixed_keypad(tmp_path, qtbot):
    win, _ = _events_window(tmp_path, qtbot)
    shortcuts = _button_shortcuts(win)
    # Each button renders its key in parens; the stage family is pinned 0=Wake..4=REM.
    assert shortcuts["Wake detected (0)"] == "0"
    assert shortcuts["N1 detected (1)"] == "1"
    assert shortcuts["N2 detected (2)"] == "2"
    assert shortcuts["N3 detected (3)"] == "3"
    assert shortcuts["REM detected (4)"] == "4"


def test_signal_observed_tags_type_and_confidence(tmp_path, qtbot, monkeypatch):
    win, session = _events_window(tmp_path, qtbot)
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        session, "emit_event", lambda key, **kw: calls.append((key, kw))
    )
    win._signal_combo.setCurrentText("Sniff")  # confidence defaults to "certain"
    win._emit_signal_observed()
    assert calls == [("SignalObserved", {"detail": "Sniff (certain)"})]


def test_signal_observed_remembers_a_typed_signal(tmp_path, qtbot, monkeypatch):
    win, session = _events_window(tmp_path, qtbot)
    monkeypatch.setattr(session, "emit_event", lambda *a, **k: None)
    assert win._signal_combo.findText("Mouth twitch") < 0  # not a seeded option
    win._signal_combo.setCurrentText("Mouth twitch")
    win._emit_signal_observed()
    assert win._signal_combo.findText("Mouth twitch") >= 0  # remembered this session
