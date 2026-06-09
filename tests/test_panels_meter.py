"""Tests for the reusable level meters (#37).

Headless Qt (offscreen). ``InputLevelMeter`` would open a sounddevice input stream,
so those tests stub ``sd.InputStream`` and drive the callback/refresh by hand.
"""

from __future__ import annotations

import numpy as np
import pytest

from smacc.panels import meter
from smacc.panels.meter import InputLevelMeter, LevelMeter


def test_level_meter_shows_and_clears(qtbot):
    m = LevelMeter()
    qtbot.addWidget(m)
    m.show_level(0.0)  # full scale -> top of the bar
    assert m.value() == 100
    assert "dBFS" in m.format()
    m.clear_level()
    assert m.value() == 0
    assert m.format() == ""


class _FakeInput:
    """Stand-in for sd.InputStream that records its lifecycle calls."""

    last: _FakeInput | None = None

    def __init__(self, *args, **kwargs):
        self.started = False
        self.aborted = False
        self.closed = False
        _FakeInput.last = self

    def start(self):
        self.started = True

    def abort(self):
        self.aborted = True

    def close(self):
        self.closed = True


def test_input_meter_start_then_stop(qtbot, monkeypatch):
    monkeypatch.setattr(meter.sd, "InputStream", _FakeInput)
    m = InputLevelMeter()
    qtbot.addWidget(m)
    assert not m.is_active()
    m.start("Mic, Windows WASAPI")
    assert m.is_active()
    assert _FakeInput.last is not None and _FakeInput.last.started
    m.stop()
    assert not m.is_active()
    assert _FakeInput.last.aborted and _FakeInput.last.closed


def test_input_meter_start_propagates_errors(qtbot, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("no device")

    monkeypatch.setattr(meter.sd, "InputStream", boom)
    m = InputLevelMeter()
    qtbot.addWidget(m)
    with pytest.raises(RuntimeError):
        m.start(None)
    assert not m.is_active()  # left cleanly stopped for the caller to handle


def test_input_meter_refresh_renders_level_and_rise(qtbot, monkeypatch):
    monkeypatch.setattr(meter.sd, "InputStream", _FakeInput)
    m = InputLevelMeter()
    qtbot.addWidget(m)
    m.start(None)
    # Simulate the audio callback delivering a block, then a display refresh.
    m._capture(np.full((256, 1), 0.5, dtype=np.float32), 256, None, None)
    m._refresh()
    assert m.value() > 0
    assert "dBFS" in m.format()
    m.stop()
