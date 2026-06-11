"""Tests for the Audio cue panel's monitoring additions (#37).

Headless Qt (offscreen). The room-monitor meter would open a sounddevice input
stream, so those tests stub ``sd.InputStream`` via the meter module.
"""

from __future__ import annotations

from smacc.panels import meter
from smacc.panels.audio import AudioCueWindow


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


def test_monitor_device_label_shows_the_room_monitor_route(qtbot, design_session):
    panel = AudioCueWindow(design_session)
    qtbot.addWidget(panel)
    # monitor_in defaults to the bedroom-mic role (reads "(not set)" until bound).
    assert "Bedroom mic" in panel.monitorDeviceLabel.text()


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
    design_session.devices.bindings["bedroom_mic"] = "Mic (Test)"
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
    design_session.devices.bindings["bedroom_mic"] = "Mic (Test)"
    panel = AudioCueWindow(design_session)
    qtbot.addWidget(panel)
    panel.monitorCheckBox.setChecked(True)
    assert not panel.monitorCheckBox.isChecked()  # reverted on failure
    assert not panel.roomMeter.is_active()


def test_room_monitor_with_no_bound_mic_errors_and_reverts(
    qtbot, design_session, monkeypatch
):
    # #139: an unbound monitor role refuses to open (instead of listening on the
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
    assert errors and "Bedroom mic" in errors[0][1]
