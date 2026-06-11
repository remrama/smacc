"""Tests for the Visual cue board's slots, playback, and live controls.

Headless Qt (offscreen). A fake backend stands in for the BlinkStick and a fake
clock replaces ``time.monotonic``, so ticks are driven by calling ``_tick()``
directly — fully deterministic, no real-timer waits.
"""

from __future__ import annotations

from PyQt6 import QtGui, QtWidgets

from smacc import hue, lights
from smacc.panels.visual import MAX_LIGHT_SLOTS, VisualWindow


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


class _SyncWriter:
    """FrameWriter stand-in: applies on submit, no thread — deterministic tests."""

    def __init__(self, backend, applied=None) -> None:
        self._backend = backend
        self.error: str | None = None

    def submit(self, rgb) -> None:
        try:
            self._backend.apply(rgb)
        except Exception as exc:  # mirror the real writer's error capture
            self.error = str(exc)

    def stop(self, timeout: float = 2.0) -> None:
        pass


def _spies(panel, monkeypatch):
    """Replace the session's marker + popup sinks with recording lists."""
    events: list[tuple[str, str | None]] = []
    popups: list[str] = []
    monkeypatch.setattr(
        panel.session,
        "emit_event",
        lambda key, detail=None: events.append((key, detail)),
    )
    monkeypatch.setattr(
        panel.session,
        "show_error_popup",
        lambda short, long=None, parent=None: popups.append(short),
    )
    return events, popups


def _board(qtbot, design_session, monkeypatch, backend=None):
    """A board with a fake clock + backend + sync writer, plus its spies."""
    panel = VisualWindow(design_session)
    qtbot.addWidget(panel)
    clock = {"t": 0.0}
    panel._clock = lambda: clock["t"]
    panel._backend = backend if backend is not None else _FakeLight()
    panel._make_writer = _SyncWriter  # no writer thread: frames apply inline
    events, popups = _spies(panel, monkeypatch)
    return panel, clock, events, popups


def test_defaults_are_one_playable_red_steady_slot(qtbot, design_session):
    panel = VisualWindow(design_session)
    qtbot.addWidget(panel)
    assert len(panel.slots) == 1
    slot = panel.slots[0]
    assert slot.nameEdit.text() == "Light 1"
    assert slot.rgb == (255, 0, 0)  # black would make Play invisible
    assert slot.patternCombo.currentData() == lights.STEADY
    assert not slot.rateSpinBox.isEnabled()  # rate only matters for pulse/flash
    assert slot.brightnessSpinBox.value() == 1.0
    assert not slot.removeButton.isEnabled()  # the one required slot stays
    assert "off" in panel.nowLitLabel.text()


def test_play_without_a_device_pops_an_error_and_marks_nothing(
    qtbot, design_session, monkeypatch
):
    panel = VisualWindow(design_session)
    qtbot.addWidget(panel)
    events, popups = _spies(panel, monkeypatch)
    assert panel._backend is None  # the default equipment has no device bound
    panel.play_slot(panel.slots[0])
    assert popups and not events
    assert not panel._timer.isActive()


def test_play_lights_the_first_frame_then_marks_with_the_slot_name(
    qtbot, design_session, monkeypatch
):
    panel, clock, events, popups = _board(qtbot, design_session, monkeypatch)
    panel.play_slot(panel.slots[0])
    backend = panel._active_backend
    assert backend.frames == [(255, 0, 0)]  # frame applied before the marker
    assert events == [("VisualStarted", "Light 1")]
    assert panel._timer.isActive()
    assert "Light 1" in panel.nowLitLabel.text()


def test_cue_ends_on_its_own_with_an_off_and_a_stop_marker(
    qtbot, design_session, monkeypatch
):
    panel, clock, events, popups = _board(qtbot, design_session, monkeypatch)
    slot = panel.slots[0]
    slot.lengthSpinBox.setValue(2.0)
    panel.play_slot(slot)
    backend = panel._active_backend
    clock["t"] = 1.0
    panel._tick()  # mid-cue: still lit
    assert backend.frames[-1] == (255, 0, 0)
    clock["t"] = 2.5
    panel._tick()  # past the length: finished
    assert backend.off_calls == 1
    assert events == [("VisualStarted", "Light 1"), ("VisualStopped", "Light 1")]
    assert not panel._timer.isActive()
    assert "off" in panel.nowLitLabel.text()


def test_stop_button_turns_off_immediately_without_a_fade(
    qtbot, design_session, monkeypatch
):
    panel, clock, events, popups = _board(qtbot, design_session, monkeypatch)
    slot = panel.slots[0]
    panel.play_slot(slot)
    backend = panel._active_backend
    clock["t"] = 0.2
    panel.stop_slot(slot)  # finalizes inline, not a tick later
    assert backend.off_calls == 1
    assert events[-1] == ("VisualStopped", "Light 1")
    assert not panel._timer.isActive()
    panel.stop_slot(slot)  # idempotent when nothing is lit
    assert len(events) == 2


def test_stop_with_a_release_fades_before_the_marker(
    qtbot, design_session, monkeypatch
):
    panel, clock, events, popups = _board(qtbot, design_session, monkeypatch)
    panel.releaseSpinBox.setValue(1.0)
    slot = panel.slots[0]
    slot.lengthSpinBox.setValue(60.0)
    panel.play_slot(slot)
    backend = panel._active_backend
    clock["t"] = 1.0
    panel.stop_slot(slot)
    assert panel._timer.isActive()  # release fade still running
    clock["t"] = 1.5
    panel._tick()
    assert backend.frames[-1] == (128, 0, 0)  # half-faded red
    assert events == [("VisualStarted", "Light 1")]
    clock["t"] = 2.1
    panel._tick()  # fade done
    assert backend.off_calls == 1
    assert events[-1] == ("VisualStopped", "Light 1")


def test_playing_another_slot_stops_the_lit_one_first(
    qtbot, design_session, monkeypatch
):
    panel, clock, events, popups = _board(qtbot, design_session, monkeypatch)
    panel.add_slot()
    first, second = panel.slots
    panel.play_slot(first)
    panel.play_slot(second)  # one-at-a-time: replaces the lit cue
    assert events == [
        ("VisualStarted", "Light 1"),
        ("VisualStopped", "Light 1"),
        ("VisualStarted", "Light 2"),
    ]


def test_replay_of_the_lit_slot_restarts_without_a_stop_marker(
    qtbot, design_session, monkeypatch
):
    panel, clock, events, popups = _board(qtbot, design_session, monkeypatch)
    slot = panel.slots[0]
    panel.play_slot(slot)
    clock["t"] = 0.5
    panel.play_slot(slot)
    assert events == [("VisualStarted", "Light 1"), ("VisualStarted", "Light 1")]


def test_brightness_and_loop_edits_apply_to_the_lit_cue(
    qtbot, design_session, monkeypatch
):
    panel, clock, events, popups = _board(qtbot, design_session, monkeypatch)
    slot = panel.slots[0]
    slot.loopCheckBox.setChecked(True)
    panel.play_slot(slot)
    slot.brightnessSpinBox.setValue(0.5)
    assert panel._engine.brightness == 0.5
    clock["t"] = 100.0  # looping: far past the 1 s length, still lit
    panel._tick()
    assert panel._active_backend.frames[-1] == (128, 0, 0)
    slot.loopCheckBox.setChecked(False)  # live: the cue now ends
    clock["t"] = 100.1
    panel._tick()
    assert events[-1] == ("VisualStopped", "Light 1")


def test_failed_write_mid_cue_stops_marks_and_reports(
    qtbot, design_session, monkeypatch
):
    panel, clock, events, popups = _board(qtbot, design_session, monkeypatch)
    panel.play_slot(panel.slots[0])
    # The device vanishes mid-cue: the writer captures the failure on its thread
    # and the next tick polls it.
    panel._writer.error = "usb gone"
    clock["t"] = 0.5
    panel._tick()
    assert events[-1] == ("VisualStopped", "Light 1")  # marker before the popup
    assert popups
    assert not panel._timer.isActive()


def test_failed_first_frame_reports_without_markers(qtbot, design_session, monkeypatch):
    # The first frame is applied synchronously, so an unreachable device is
    # reported at the click and no start marker fires for a cue that never lit.
    panel, clock, events, popups = _board(
        qtbot, design_session, monkeypatch, backend=_DeadLight()
    )
    panel.play_slot(panel.slots[0])
    assert popups and not events
    assert not panel._timer.isActive()


def test_cleanup_forces_the_light_off_without_a_marker(
    qtbot, design_session, monkeypatch
):
    panel, clock, events, popups = _board(qtbot, design_session, monkeypatch)
    panel.play_slot(panel.slots[0])
    backend = panel._active_backend
    panel.cleanup()  # app quit mid-cue
    assert backend.off_calls == 1
    assert events == [("VisualStarted", "Light 1")]  # no stop marker on quit
    assert not panel._timer.isActive()


def test_add_and_remove_slots_respect_the_bounds(qtbot, design_session, monkeypatch):
    panel, clock, events, popups = _board(qtbot, design_session, monkeypatch)
    panel.add_slot()
    assert [s.nameEdit.text() for s in panel.slots] == ["Light 1", "Light 2"]
    assert all(s.removeButton.isEnabled() for s in panel.slots)
    panel.remove_slot(panel.slots[1])
    assert len(panel.slots) == 1
    panel.remove_slot(panel.slots[0])  # the last slot can't be removed
    assert len(panel.slots) == 1
    panel._resize_slots(MAX_LIGHT_SLOTS + 5)  # clamped at the cap
    assert len(panel.slots) == MAX_LIGHT_SLOTS
    assert not panel._addButton.isEnabled()


def test_removing_the_lit_slot_darkens_without_a_marker(
    qtbot, design_session, monkeypatch
):
    panel, clock, events, popups = _board(qtbot, design_session, monkeypatch)
    panel.add_slot()
    second = panel.slots[1]
    panel.play_slot(second)
    backend = panel._active_backend
    panel.remove_slot(second)
    assert backend.off_calls == 1
    assert events == [("VisualStarted", "Light 2")]  # no spurious stop marker


def test_rate_warning_appears_only_for_fast_patterned_slots(
    qtbot, design_session, monkeypatch
):
    panel, clock, events, popups = _board(qtbot, design_session, monkeypatch)
    slot = panel.slots[0]
    assert not panel.rateWarningLabel.isVisibleTo(panel)
    slot.rateSpinBox.setValue(12.0)  # fast, but the pattern is steady
    assert not panel.rateWarningLabel.isVisibleTo(panel)
    slot.patternCombo.setCurrentIndex(slot.patternCombo.findData(lights.FLASH))
    assert slot.rateSpinBox.isEnabled()
    assert panel.rateWarningLabel.isVisibleTo(panel)
    slot.rateSpinBox.setValue(5.0)
    assert not panel.rateWarningLabel.isVisibleTo(panel)


def test_color_can_be_picked_with_no_device(qtbot, design_session, monkeypatch):
    panel = VisualWindow(design_session)
    qtbot.addWidget(panel)
    events, popups = _spies(panel, monkeypatch)
    monkeypatch.setattr(
        QtWidgets.QColorDialog, "getColor", lambda *a, **k: QtGui.QColor("#112233")
    )
    assert panel._backend is None
    panel.pick_slot_color(panel.slots[0])
    assert panel.slots[0].rgb == (0x11, 0x22, 0x33)
    assert not popups  # choosing a color never needs hardware


def test_visual_route_to_hue_resolves_a_hue_backend(qtbot, design_session):
    design_session.hue_config = hue.HueConfig("192.168.1.50", "key")
    design_session.devices.bindings["philips_hue_light"] = "light:1"
    design_session.devices.routing["play_visual_cue"] = "philips_hue_light"
    panel = VisualWindow(design_session)
    qtbot.addWidget(panel)
    assert isinstance(panel._backend, hue.HueBackend)
    assert "Philips Hue" in panel.deviceLabel.text()


def test_flash_is_refused_on_a_backend_without_flash_support(
    qtbot, design_session, monkeypatch
):
    class _NoFlashLight(_FakeLight):
        supports_flash = False

    panel, clock, events, popups = _board(
        qtbot, design_session, monkeypatch, backend=_NoFlashLight()
    )
    panel.add_slot()
    steady, flashy = panel.slots
    flashy.patternCombo.setCurrentIndex(flashy.patternCombo.findData(lights.FLASH))
    panel.play_slot(steady)  # steady is fine on any backend
    panel.play_slot(flashy)  # refused — and must not kill the lit steady cue
    assert popups
    assert events == [("VisualStarted", "Light 1")]
    assert panel._active_slot is steady
    assert panel._timer.isActive()
