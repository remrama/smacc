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


def test_add_event_button_adds_to_registry_and_grid(tmp_path, qtbot, monkeypatch):
    # The panel's Add event… button defines a custom event in place: it lands in
    # the session registry and its button appears in the grid without a detour
    # through File ▸ Event codes….
    from smacc import dialogs

    win, session = _events_window(tmp_path, qtbot)
    before = len(session.events)
    monkeypatch.setattr(dialogs.AddEventDialog, "exec", lambda self: True)
    # A code that's unused AND outside every incrementing event's code..255 band,
    # so the add raises neither a hard error nor a soft-warning prompt.
    evs = list(session.events.values())
    taken = {e.code for e in evs}
    free_code = next(
        c
        for c in range(1, 256)
        if c not in taken
        and all(not (e.increment and e.trigger and c >= e.code) for e in evs)
    )
    monkeypatch.setattr(
        dialogs.AddEventDialog,
        "get_inputs",
        lambda self: ("Spontaneous arousal", free_code, "", False),
    )

    # Any popup here means the chosen code wasn't as clean as intended — fail
    # loudly rather than hang the headless run on a modal box.
    def _unexpected(*a, **k):
        raise AssertionError(f"unexpected modal prompt: {a}")

    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", _unexpected)
    monkeypatch.setattr(QtWidgets.QMessageBox, "question", _unexpected)
    win.add_custom_event()
    assert len(session.events) == before + 1
    added = next(e for e in session.events.values() if not e.builtin)
    assert added.label == "Spontaneous arousal"
    assert added.code == free_code
    labels = [b.text() for b in win.findChildren(QtWidgets.QPushButton)]
    assert any("Spontaneous arousal" in label for label in labels)


def test_add_event_with_duplicate_code_is_blocked(tmp_path, qtbot, monkeypatch):
    from smacc import dialogs

    win, session = _events_window(tmp_path, qtbot)
    taken = next(e.code for e in session.events.values() if e.trigger)
    before = len(session.events)
    monkeypatch.setattr(dialogs.AddEventDialog, "exec", lambda self: True)
    monkeypatch.setattr(
        dialogs.AddEventDialog, "get_inputs", lambda self: ("Dupe", taken, "", False)
    )
    warned: list[str] = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *a, **k: warned.append(a[2]) or QtWidgets.QMessageBox.StandardButton.Ok,
    )
    win.add_custom_event()
    assert len(session.events) == before  # blocked, nothing added
    assert warned and "fix these first" in warned[0]
