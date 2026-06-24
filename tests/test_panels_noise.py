"""Tests for the noise-machine window: playback lifecycle, callback, and state.

Headless: sounddevice is stubbed, the loop buffer and callback are driven by hand.
"""

from __future__ import annotations

import numpy as np
import pytest

from smacc.panels import noise
from smacc.panels.noise import NOISE_LOOP_SECONDS, NoiseWindow


class _FakeOutput:
    """Stand-in for sd.OutputStream that records its lifecycle calls."""

    last: _FakeOutput | None = None
    latency = 0.01  # the panel reads it for the marker's onset offset

    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs
        self.started = False
        self.aborted = False
        self.closed = False
        _FakeOutput.last = self

    def start(self):
        self.started = True

    def abort(self):
        self.aborted = True

    def close(self):
        self.closed = True


def _stub_output(monkeypatch, stream_cls=_FakeOutput, rate=8000.0):
    monkeypatch.setattr(
        noise.sd, "query_devices", lambda *a, **k: {"default_samplerate": rate}
    )
    monkeypatch.setattr(noise.sd, "OutputStream", stream_cls)


def _bind_output(session):
    """Give the noise route a definite device (#139: nothing opens unbound)."""
    session.devices.bindings["bedroom_speaker"] = "Speakers (Test)"


def test_play_then_stop_builds_buffer_and_updates_status(
    qtbot, headless_session, monkeypatch
):
    _stub_output(monkeypatch)
    _bind_output(headless_session)
    window = NoiseWindow(headless_session)
    qtbot.addWidget(window)
    assert not window.is_streaming()

    window.play_noise()
    assert window.is_streaming()
    assert _FakeOutput.last is not None and _FakeOutput.last.started
    assert window._noise_buffer is not None
    assert window._noise_buffer.shape == (NOISE_LOOP_SECONDS * 8000,)
    assert "playing" in window.noiseStatusLabel.text()

    window.stop_noise()
    assert not window.is_streaming()
    assert window._noise_buffer is None
    assert "stopped" in window.noiseStatusLabel.text()
    assert _FakeOutput.last.aborted and _FakeOutput.last.closed


def test_play_marks_once_but_not_on_silent_restart(
    qtbot, headless_session, monkeypatch
):
    _stub_output(monkeypatch)
    _bind_output(headless_session)
    window = NoiseWindow(headless_session)
    qtbot.addWidget(window)
    emitted = []
    monkeypatch.setattr(
        headless_session, "emit_event", lambda key, **k: emitted.append(key)
    )

    window.on_play_noise_clicked()
    assert emitted == ["NoiseStarted"]
    # A color change mid-playback restarts the stream silently (no new marker).
    window.available_noisecolors_dropdown.setCurrentIndex(1)  # white -> pink
    assert window.is_streaming()
    assert emitted == ["NoiseStarted"]

    window.on_stop_noise_clicked()
    assert emitted == ["NoiseStarted", "NoiseStopped"]
    # Stop when already stopped marks nothing.
    window.on_stop_noise_clicked()
    assert emitted == ["NoiseStarted", "NoiseStopped"]


def test_callback_loops_the_buffer_and_applies_gain_and_cap(qtbot, headless_session):
    window = NoiseWindow(headless_session)
    qtbot.addWidget(window)
    window._noise_buffer = np.array([0.0, 1.0, 2.0, 3.0], dtype="float32")
    window._noise_pos = 2
    window.noise_stream_volume = 0.5
    headless_session.volume_cap = 0.5  # the master safety cap is the final gain stage
    out = np.zeros((6, 1), dtype="float32")
    window._noise_callback(out, 6, None, None)
    # Reads wrap around the loop seam; gain = volume * cap = 0.25.
    np.testing.assert_allclose(out[:, 0], np.array([2, 3, 0, 1, 2, 3]) * 0.25)


def test_callback_outputs_silence_without_a_buffer(qtbot, headless_session):
    window = NoiseWindow(headless_session)
    qtbot.addWidget(window)
    out = np.ones((8, 1), dtype="float32")
    window._noise_callback(out, 8, None, None)
    assert not out.any()


def test_file_source_without_a_file_shows_error_and_no_stream(
    qtbot, headless_session, monkeypatch, silence_dialogs
):
    _stub_output(monkeypatch)
    _bind_output(headless_session)
    window = NoiseWindow(headless_session)
    qtbot.addWidget(window)
    window.fileRadio.setChecked(True)
    window.play_noise()
    assert not window.is_streaming()
    assert window._noise_buffer is None


def test_failed_stream_start_clears_the_buffer(
    qtbot, headless_session, monkeypatch, silence_dialogs
):
    def boom(*args, **kwargs):
        raise RuntimeError("no output device")

    _stub_output(monkeypatch, stream_cls=boom)
    _bind_output(headless_session)
    window = NoiseWindow(headless_session)
    qtbot.addWidget(window)
    window.play_noise()
    assert not window.is_streaming()
    assert window._noise_buffer is None
    assert "stopped" in window.noiseStatusLabel.text()


def test_play_with_no_bound_device_errors_and_keeps_quiet(
    qtbot, headless_session, monkeypatch
):
    # #139: unbound equipment refuses to play (with an error pointing at the
    # Devices window) instead of falling back to the system default device.
    _stub_output(monkeypatch)
    errors = []
    monkeypatch.setattr(
        headless_session, "show_error_popup", lambda *a, **k: errors.append(a)
    )
    window = NoiseWindow(headless_session)
    qtbot.addWidget(window)
    window.on_play_noise_clicked()
    assert not window.is_streaming()
    assert window._noise_buffer is None
    assert errors and "Bedroom speaker" in errors[0][1]


@pytest.mark.parametrize("color", ["white", "pink", "brown"])
def test_each_builtin_color_builds_a_normalized_buffer(qtbot, headless_session, color):
    window = NoiseWindow(headless_session)
    qtbot.addWidget(window)
    idx = window.available_noisecolors_dropdown.findText(color)
    window.available_noisecolors_dropdown.setCurrentIndex(idx)
    buf = window._build_noise_buffer(2000)
    assert buf.shape == (NOISE_LOOP_SECONDS * 2000,)
    assert np.all(np.isfinite(buf))
    assert np.abs(buf).max() <= 1.0  # normalized for the volume/cap gain stage


def test_state_round_trips_between_windows(qtbot, headless_session):
    first = NoiseWindow(headless_session)
    qtbot.addWidget(first)
    first.noisevolumeSpinBox.setValue(0.42)
    first.fileRadio.setChecked(True)
    first.noiseFileEdit.setText("C:/sounds/rain.wav")
    idx = first.available_noisecolors_dropdown.findText("brown")
    first.available_noisecolors_dropdown.setCurrentIndex(idx)
    state = first.gather_state()

    second = NoiseWindow(headless_session)
    qtbot.addWidget(second)
    second.apply_state(state)
    assert second.noisevolumeSpinBox.value() == pytest.approx(0.42)
    assert second.fileRadio.isChecked()
    assert second.noiseFileEdit.text() == "C:/sounds/rain.wav"
    assert second.available_noisecolors_dropdown.currentText() == "brown"
    # The file row is enabled (and the color picker not) to match the source.
    assert second.noiseFileEdit.isEnabled()
    assert not second.available_noisecolors_dropdown.isEnabled()
