"""Tests for the Audio cue panel: the mixer layout (#289) and monitoring (#37).

Headless Qt (offscreen). The room-monitor meter would open a sounddevice input
stream, so those tests stub ``sd.InputStream`` via the meter module.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from smacc.panels import meter
from smacc.panels.audio import (
    INITIAL_CUE_SLOTS,
    MAX_CUE_SLOTS,
    AudioCueWindow,
)


def _write_wav(path: Path) -> Path:
    """Write a tiny mono WAV so set_slot_file has something real to decode."""
    sf.write(path, np.zeros(128, dtype="float32"), 8000)
    return path


class _FakeInput:
    """Stand-in for sd.InputStream that records its lifecycle calls."""

    def __init__(self, *args, **kwargs):
        self.aborted = False
        self.closed = False

    def start(self):
        pass

    def abort(self):
        self.aborted = True

    def close(self):
        self.closed = True


def test_volume_fader_and_spinbox_stay_in_sync(qtbot, design_session):
    panel = AudioCueWindow(design_session)
    qtbot.addWidget(panel)
    slot = panel.slots[0]
    # Dragging the fader drives the (precise) spinbox...
    slot.volumeSlider.setValue(75)
    assert slot.volumeSpinBox.value() == pytest.approx(0.75)
    # ...and editing the spinbox echoes back to the fader.
    slot.volumeSpinBox.setValue(0.30)
    assert slot.volumeSlider.value() == 30


def test_set_slot_file_labels_button_and_decodes(qtbot, design_session, tmp_path):
    panel = AudioCueWindow(design_session)
    qtbot.addWidget(panel)
    slot = panel.slots[0]
    wav = _write_wav(tmp_path / "chime.wav")
    panel.set_slot_file(slot, str(wav))
    assert slot.file_path == str(wav)
    assert slot.fileButton.text() not in ("", "Choose sound…")  # shows the file
    assert slot.fileButton.toolTip() == str(wav)  # full path on hover
    assert slot.audio is not None and slot.rate == 8000
    # An empty path clears the buffer and shows the placeholder label.
    panel.set_slot_file(slot, "")
    assert slot.file_path == ""
    assert slot.audio is None
    assert "Choose" in slot.fileButton.text()


def test_audio_panel_round_trips_the_file_path(qtbot, design_session, tmp_path):
    panel = AudioCueWindow(design_session)
    qtbot.addWidget(panel)
    wav = _write_wav(tmp_path / "cue.wav")
    panel.apply_state({"cues": [{"name": "Cue 1", "file": str(wav), "volume": 0.5}]})
    got = panel.gather_state()
    assert got["cues"][0]["file"] == str(wav)
    assert panel.slots[0].volumeSlider.value() == 50  # fader followed the loaded value


def test_loop_button_is_a_checkable_toggle_that_drives_the_loop_flag(
    qtbot, design_session
):
    panel = AudioCueWindow(design_session)
    qtbot.addWidget(panel)
    slot = panel.slots[0]
    assert slot.loopButton.isCheckable()
    assert not slot.loopButton.isChecked()
    # The loop flag round-trips through the toggle button (no checkbox anymore).
    panel.apply_state({"cues": [{"name": "Cue 1", "file": "", "loop": True}]})
    assert panel.slots[0].loopButton.isChecked()
    assert panel.gather_state()["cues"][0]["loop"] is True


def test_transport_buttons_are_icon_only(qtbot, design_session):
    panel = AudioCueWindow(design_session)
    qtbot.addWidget(panel)
    slot = panel.slots[0]
    for button in (
        slot.playButton,
        slot.stopButton,
        slot.loopButton,
        slot.removeButton,
    ):
        assert not button.icon().isNull()  # has an icon
        assert button.text() == ""  # icon-only, no label text


def test_add_and_remove_strips_keeps_the_lone_strip(qtbot, design_session):
    panel = AudioCueWindow(design_session)
    qtbot.addWidget(panel)
    assert len(panel.slots) == INITIAL_CUE_SLOTS == 2  # a fresh study opens with two
    assert all(s.removeButton.isEnabled() for s in panel.slots)
    panel.remove_slot(panel.slots[1])
    assert len(panel.slots) == 1
    assert not panel.slots[0].removeButton.isEnabled()  # the lone strip stays
    panel.remove_slot(panel.slots[0])  # the last strip can't be removed
    assert len(panel.slots) == 1
    while len(panel.slots) < MAX_CUE_SLOTS:
        panel.add_slot()
    assert not panel._addButton.isEnabled()  # capped


def test_monitor_device_label_shows_the_room_monitor_route(qtbot, design_session):
    panel = AudioCueWindow(design_session)
    qtbot.addWidget(panel)
    # monitor_bedroom_noise defaults to Bedroom mic 1 (reads "(not set)" until bound).
    assert "Bedroom mic 1" in panel.monitorDeviceLabel.text()


def test_output_meter_reflects_the_sent_level(qtbot, design_session):
    panel = AudioCueWindow(design_session)
    qtbot.addWidget(panel)
    assert panel.outMeter.value() == 0  # nothing playing yet
    panel._out_level_db = -6.0  # as if the cue callback measured a block
    panel._poll_cue()  # the GUI-thread tick that drives the meter
    assert panel.outMeter.value() > 0


def test_room_monitor_toggle_opens_and_closes_and_gates_streaming(
    qtbot, design_session, monkeypatch
):
    monkeypatch.setattr(meter.sd, "InputStream", _FakeInput)
    design_session.devices.bindings["bedroom_mic_1"] = "Mic (Test)"
    panel = AudioCueWindow(design_session)
    qtbot.addWidget(panel)
    assert not panel.is_streaming()
    panel.monitorCheckBox.setChecked(True)  # -> toggle_room_monitor(True)
    assert panel.roomMeter.is_active()
    assert panel.is_streaming()  # the open input stream gates device rescans
    panel.monitorCheckBox.setChecked(False)
    assert not panel.roomMeter.is_active()
    assert not panel.is_streaming()


def test_room_monitor_start_failure_reverts_the_checkbox(
    qtbot, design_session, monkeypatch, silence_dialogs
):
    def boom(*args, **kwargs):
        raise RuntimeError("no mic")

    monkeypatch.setattr(meter.sd, "InputStream", boom)
    design_session.devices.bindings["bedroom_mic_1"] = "Mic (Test)"
    panel = AudioCueWindow(design_session)
    qtbot.addWidget(panel)
    panel.monitorCheckBox.setChecked(True)
    assert not panel.monitorCheckBox.isChecked()  # reverted on failure
    assert not panel.roomMeter.is_active()


def test_room_monitor_with_no_bound_mic_errors_and_reverts(
    qtbot, design_session, monkeypatch
):
    # #139: unbound monitor equipment refuses to open (instead of listening on the
    # system default input) and the checkbox reverts.
    monkeypatch.setattr(meter.sd, "InputStream", _FakeInput)
    errors = []
    monkeypatch.setattr(
        design_session, "show_error_popup", lambda *a, **k: errors.append(a)
    )
    panel = AudioCueWindow(design_session)
    qtbot.addWidget(panel)
    panel.monitorCheckBox.setChecked(True)
    assert not panel.monitorCheckBox.isChecked()
    assert not panel.roomMeter.is_active()
    assert errors and "Bedroom mic 1" in errors[0][1]
