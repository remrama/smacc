"""Tests for the Visual stimulation panel's non-blocking playback.

Headless Qt (offscreen). A fake backend stands in for the BlinkStick and a fake
clock replaces ``time.monotonic``, so ticks are driven by calling ``_tick()``
directly — fully deterministic, no real-timer waits.
"""

from __future__ import annotations

from PyQt6 import QtGui, QtWidgets

from smacc.panels.visual import VisualWindow


class _FakeLight:
    """LightBackend stand-in recording every frame and off() call."""

    def __init__(self) -> None:
        self.frames: list[tuple[int, int, int]] = []
        self.off_calls = 0

    def apply(self, rgb) -> None:
        self.frames.append(rgb)

    def off(self) -> None:
        self.off_calls += 1


class _DeadLight(_FakeLight):
    """A backend whose writes fail (the stick was unplugged mid-cue)."""

    def apply(self, rgb) -> None:
        raise OSError("usb gone")


def _spies(panel, monkeypatch):
    """Replace the session's marker + popup sinks with recording lists."""
    events: list[str] = []
    popups: list[str] = []
    monkeypatch.setattr(
        panel.session, "emit_event", lambda key, detail=None: events.append(key)
    )
    monkeypatch.setattr(
        panel.session,
        "show_error_popup",
        lambda short, long=None, parent=None: popups.append(short),
    )
    return events, popups


def _playing_panel(qtbot, design_session, monkeypatch, backend=None):
    """A panel with a fake clock + backend, plus its event/popup spies."""
    panel = VisualWindow(design_session)
    qtbot.addWidget(panel)
    clock = {"t": 0.0}
    panel._clock = lambda: clock["t"]
    panel._backend = backend if backend is not None else _FakeLight()
    events, popups = _spies(panel, monkeypatch)
    return panel, clock, events, popups


def test_defaults_are_a_visible_red_cue(qtbot, design_session):
    panel = VisualWindow(design_session)
    qtbot.addWidget(panel)
    assert panel.blink_hexcode == "#ff0000"  # black would make Play invisible
    assert "off" in panel.stateLabel.text()


def test_play_without_a_device_pops_an_error_and_marks_nothing(
    qtbot, design_session, monkeypatch
):
    panel = VisualWindow(design_session)
    qtbot.addWidget(panel)
    events, popups = _spies(panel, monkeypatch)
    assert panel._backend is None  # the default role has no device bound
    panel.play_cue()
    assert popups and not events
    assert not panel._timer.isActive()


def test_play_lights_the_first_frame_then_marks_the_start(
    qtbot, design_session, monkeypatch
):
    panel, clock, events, popups = _playing_panel(qtbot, design_session, monkeypatch)
    panel.play_cue()
    backend = panel._active_backend
    assert backend.frames == [(255, 0, 0)]  # frame applied before the marker
    assert events == ["VisualStarted"]
    assert panel._timer.isActive()
    assert "lit" in panel.stateLabel.text()


def test_cue_ends_on_its_own_with_an_off_and_a_stop_marker(
    qtbot, design_session, monkeypatch
):
    panel, clock, events, popups = _playing_panel(qtbot, design_session, monkeypatch)
    panel.lengthSpinBox.setValue(2.0)
    panel.play_cue()
    backend = panel._active_backend
    clock["t"] = 1.0
    panel._tick()  # mid-cue: still lit
    assert backend.frames[-1] == (255, 0, 0)
    assert events == ["VisualStarted"]
    clock["t"] = 2.5
    panel._tick()  # past the length: finished
    assert backend.off_calls == 1
    assert events == ["VisualStarted", "VisualStopped"]
    assert not panel._timer.isActive()
    assert "off" in panel.stateLabel.text()


def test_stop_button_turns_off_immediately(qtbot, design_session, monkeypatch):
    panel, clock, events, popups = _playing_panel(qtbot, design_session, monkeypatch)
    panel.play_cue()
    backend = panel._active_backend
    clock["t"] = 0.2
    panel.stop_cue()  # finalizes inline, not a tick later
    assert backend.off_calls == 1
    assert events == ["VisualStarted", "VisualStopped"]
    assert not panel._timer.isActive()
    panel.stop_cue()  # idempotent when nothing is playing
    assert events == ["VisualStarted", "VisualStopped"]


def test_replay_while_lit_restarts_without_a_stop_marker(
    qtbot, design_session, monkeypatch
):
    panel, clock, events, popups = _playing_panel(qtbot, design_session, monkeypatch)
    panel.play_cue()
    clock["t"] = 0.5
    panel.play_cue()  # restart, like re-playing the active audio slot
    assert events == ["VisualStarted", "VisualStarted"]


def test_failed_write_mid_cue_stops_marks_and_reports(
    qtbot, design_session, monkeypatch
):
    panel, clock, events, popups = _playing_panel(qtbot, design_session, monkeypatch)
    panel.play_cue()
    panel._active_backend = _DeadLight()  # the stick vanishes mid-cue
    clock["t"] = 0.5
    panel._tick()
    assert events == ["VisualStarted", "VisualStopped"]  # marker before the popup
    assert popups
    assert not panel._timer.isActive()


def test_cleanup_forces_the_light_off_without_a_marker(
    qtbot, design_session, monkeypatch
):
    panel, clock, events, popups = _playing_panel(qtbot, design_session, monkeypatch)
    panel.play_cue()
    backend = panel._active_backend
    panel.cleanup()  # app quit mid-cue
    assert backend.off_calls == 1
    assert events == ["VisualStarted"]  # no stop marker on quit
    assert not panel._timer.isActive()


def test_color_can_be_picked_with_no_device(qtbot, design_session, monkeypatch):
    panel = VisualWindow(design_session)
    qtbot.addWidget(panel)
    events, popups = _spies(panel, monkeypatch)
    monkeypatch.setattr(
        QtWidgets.QColorDialog, "getColor", lambda *a, **k: QtGui.QColor("#112233")
    )
    assert panel._backend is None
    panel.pick_color()
    assert panel.blink_hexcode == "#112233"
    assert not popups  # the old panel refused without hardware
