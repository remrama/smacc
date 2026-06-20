"""Tests for the Chat window's voice (#20) and its audio bridge, plus the chat section.

The ``_Bridge`` queue/resampler logic is tested directly (no Qt, no hardware);
window tests stub the bridge so toggles, markers, and push-to-talk are exercised
headless.
"""

from __future__ import annotations

import queue

import numpy as np
import pytest
from PyQt6 import QtCore, QtGui

from smacc import audio
from smacc.panels import chat
from smacc.panels.chat import ChatWindow, _Bridge

# ----- _Bridge (pure queue/resampler logic) ----------------------------------


def _primed_bridge(in_rate=8000, out_rate=8000, maxsize=4) -> _Bridge:
    bridge = _Bridge()
    bridge._queue = queue.Queue(maxsize=maxsize)
    bridge._resampler = audio.LinearResampler(in_rate, out_rate)
    return bridge


def test_bridge_in_callback_queues_audio_and_meters_level():
    bridge = _primed_bridge()
    block = np.full((128, 1), 1.0, dtype="float32")
    bridge._in_callback(block, 128, None, None)
    assert bridge._queue.qsize() == 1
    assert bridge.level_db == pytest.approx(0.0)  # full scale -> 0 dBFS


def test_bridge_drops_blocks_instead_of_blocking_when_full():
    bridge = _primed_bridge(maxsize=1)
    block = np.zeros((64, 1), dtype="float32")
    bridge._in_callback(block, 64, None, None)
    bridge._in_callback(block, 64, None, None)  # queue full: dropped, no raise
    assert bridge._queue.qsize() == 1


def test_bridge_out_callback_drains_the_queue_into_the_output():
    bridge = _primed_bridge()
    bridge._in_callback(np.full((64, 1), 0.5, dtype="float32"), 64, None, None)
    out = np.zeros((32, 1), dtype="float32")
    bridge._out_callback(out, 32, None, None)
    assert bridge._queue.qsize() == 0  # drained into the resampler
    assert out.any()  # and the output carries the bridged audio


def test_bridge_out_callback_is_silent_when_inactive():
    bridge = _Bridge()  # never started: no queue, no resampler
    out = np.ones((32, 1), dtype="float32")
    bridge._out_callback(out, 32, None, None)
    assert not out.any()


def test_bridge_start_failure_tears_down_cleanly(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("no such device")

    monkeypatch.setattr(chat.sd, "query_devices", boom)
    bridge = _Bridge()
    with pytest.raises(RuntimeError):
        bridge.start(None, None)
    assert not bridge.active()
    assert bridge._queue is None and bridge._resampler is None
    assert bridge.level_db == audio.FLOOR_DBFS


# ----- ChatWindow voice -------------------------------------------------------


def _stub_bridges(monkeypatch, fail=False):
    """Replace _Bridge.start/stop with recorders so no stream ever opens."""
    calls = {"start": 0, "stop": 0}

    def fake_start(self, input_device, output_device):
        if fail:
            raise RuntimeError("PortAudio error")
        calls["start"] += 1
        self._queue = queue.Queue()  # marks the bridge "active enough" for stop()

    def fake_stop(self):
        running = self._queue is not None
        calls["stop"] += 1
        self._queue = None
        return running

    monkeypatch.setattr(_Bridge, "start", fake_start)
    monkeypatch.setattr(_Bridge, "stop", fake_stop)
    monkeypatch.setattr(_Bridge, "active", lambda self: self._queue is not None)
    return calls


def _bind_devices(session):
    """Give both voice directions definite devices (#139: no unbound opens).

    Talk needs the control-room mic (#160) and the participant output; Listen
    needs the participant mic plus the optional return route pointed at bound
    equipment.
    """
    session.devices.bindings["bedroom_speaker"] = "Speakers (Test)"
    session.devices.bindings["bedroom_mic_1"] = "Mic (Test)"
    session.devices.bindings["control_mic"] = "Headset Mic (Test)"
    session.devices.bindings["control_speaker"] = "Headphones (Test)"
    session.devices.routing["listen_to_participant"] = "control_speaker"


def test_toggle_talk_starts_the_bridge_and_marks(qtbot, design_session, monkeypatch):
    calls = _stub_bridges(monkeypatch)
    _bind_devices(design_session)
    window = ChatWindow(design_session)
    qtbot.addWidget(window)
    emitted = []
    monkeypatch.setattr(
        design_session, "emit_event", lambda key, **k: emitted.append(key)
    )

    window.talkButton.setChecked(True)
    assert calls["start"] == 1
    assert emitted == ["TalkStarted"]
    assert window._level_timer.isActive()

    window.talkButton.setChecked(False)
    assert emitted == ["TalkStarted", "TalkStopped"]
    assert not window._level_timer.isActive()
    window.cleanup()


def test_talk_start_failure_reverts_the_button(
    qtbot, design_session, monkeypatch, silence_dialogs
):
    _stub_bridges(monkeypatch, fail=True)
    _bind_devices(design_session)
    window = ChatWindow(design_session)
    qtbot.addWidget(window)
    emitted = []
    monkeypatch.setattr(
        design_session, "emit_event", lambda key, **k: emitted.append(key)
    )
    window.talkButton.setChecked(True)
    assert not window.talkButton.isChecked()  # reverted by the error path
    assert emitted == []  # a failed start is never marked
    window.cleanup()


def test_listen_toggles_without_markers(qtbot, design_session, monkeypatch):
    calls = _stub_bridges(monkeypatch)
    _bind_devices(design_session)
    window = ChatWindow(design_session)
    qtbot.addWidget(window)
    emitted = []
    monkeypatch.setattr(
        design_session, "emit_event", lambda key, **k: emitted.append(key)
    )
    window.listenButton.setChecked(True)
    window.listenButton.setChecked(False)
    assert calls["start"] == 1
    assert emitted == []  # passive monitoring: log line only, no EEG marker
    window.cleanup()


def test_listen_with_route_off_errors_and_reverts(qtbot, design_session, monkeypatch):
    # #139: the listen route is off by default; toggling it must refuse (instead
    # of opening the participant mix on the system default output) and revert.
    calls = _stub_bridges(monkeypatch)
    design_session.devices.bindings["bedroom_mic_1"] = "Mic (Test)"
    errors = []
    monkeypatch.setattr(
        design_session, "show_error_popup", lambda *a, **k: errors.append(a)
    )
    window = ChatWindow(design_session)
    qtbot.addWidget(window)
    window.listenButton.setChecked(True)
    assert not window.listenButton.isChecked()
    assert calls["start"] == 0
    assert errors and "not routed" in errors[0][1]
    window.cleanup()


def test_talk_with_no_bound_output_errors_and_reverts(
    qtbot, design_session, monkeypatch
):
    # #139: an unbound participant output refuses to talk (instead of speaking
    # through the system default device) and the button reverts, unmarked.
    calls = _stub_bridges(monkeypatch)
    design_session.devices.bindings["control_mic"] = "Headset Mic (Test)"
    errors = []
    monkeypatch.setattr(
        design_session, "show_error_popup", lambda *a, **k: errors.append(a)
    )
    emitted = []
    monkeypatch.setattr(
        design_session, "emit_event", lambda key, **k: emitted.append(key)
    )
    window = ChatWindow(design_session)
    qtbot.addWidget(window)
    window.talkButton.setChecked(True)
    assert not window.talkButton.isChecked()
    assert calls["start"] == 0
    assert emitted == []
    assert errors and "Bedroom speaker" in errors[0][1]
    window.cleanup()


def test_talk_with_no_bound_mic_errors_and_reverts(qtbot, design_session, monkeypatch):
    # #160: an unbound control-room mic refuses to talk (instead of capturing
    # from the system default input) and the button reverts, unmarked.
    calls = _stub_bridges(monkeypatch)
    design_session.devices.bindings["bedroom_speaker"] = "Speakers (Test)"
    errors = []
    monkeypatch.setattr(
        design_session, "show_error_popup", lambda *a, **k: errors.append(a)
    )
    emitted = []
    monkeypatch.setattr(
        design_session, "emit_event", lambda key, **k: emitted.append(key)
    )
    window = ChatWindow(design_session)
    qtbot.addWidget(window)
    window.talkButton.setChecked(True)
    assert not window.talkButton.isChecked()
    assert calls["start"] == 0
    assert emitted == []
    assert errors and "Control-room mic" in errors[0][1]
    window.cleanup()


def _space_event(etype) -> QtGui.QKeyEvent:
    return QtGui.QKeyEvent(
        etype, QtCore.Qt.Key.Key_Space, QtCore.Qt.KeyboardModifier.NoModifier
    )


def test_spacebar_push_to_talk_holds_and_releases(qtbot, design_session, monkeypatch):
    _stub_bridges(monkeypatch)
    _bind_devices(design_session)
    window = ChatWindow(design_session)
    qtbot.addWidget(window)
    monkeypatch.setattr(
        ChatWindow, "_is_text_widget_focused", staticmethod(lambda: False)
    )

    consumed = window.eventFilter(window, _space_event(QtCore.QEvent.Type.KeyPress))
    assert consumed and window.talkButton.isChecked()
    consumed = window.eventFilter(window, _space_event(QtCore.QEvent.Type.KeyRelease))
    assert consumed and not window.talkButton.isChecked()
    window.cleanup()


def test_spacebar_passes_through_while_typing(qtbot, design_session, monkeypatch):
    _stub_bridges(monkeypatch)
    _bind_devices(design_session)
    window = ChatWindow(design_session)
    qtbot.addWidget(window)
    monkeypatch.setattr(
        ChatWindow, "_is_text_widget_focused", staticmethod(lambda: True)
    )

    consumed = window.eventFilter(window, _space_event(QtCore.QEvent.Type.KeyPress))
    assert not consumed and not window.talkButton.isChecked()
    window.cleanup()


def test_send_chat_message_posts_and_clears_the_entry(qtbot, design_session):
    window = ChatWindow(design_session)
    qtbot.addWidget(window)
    window.chatEntry.setText("  Are you comfortable?  ")
    window.send_chat_message()
    assert "You:  Are you comfortable?" in window.chatView.toPlainText()
    assert window.chatEntry.text() == ""
    window.cleanup()


def test_empty_chat_message_is_not_posted(qtbot, design_session):
    window = ChatWindow(design_session)
    qtbot.addWidget(window)
    window.chatEntry.setText("   ")
    window.send_chat_message()
    assert window.chatView.toPlainText() == ""
    window.cleanup()


def test_preset_buttons_rebuild_and_send_verbatim(qtbot, design_session):
    window = ChatWindow(design_session)
    qtbot.addWidget(window)
    long = "Please describe everything that was going through your mind just now."
    window._presets.set([long], [])
    assert len(window._preset_buttons) == 1
    button = window._preset_buttons[0]
    assert button.text().endswith("…")  # elided label
    assert button.toolTip() == long  # full text preserved
    button.click()
    assert f"You:  {long}" in window.chatView.toPlainText()
    window.cleanup()


def test_preset_state_round_trips(qtbot, design_session):
    window = ChatWindow(design_session)
    qtbot.addWidget(window)
    window._presets.set(["Prompt one"], ["Yes", "No"])
    state = window.gather_state()
    other = ChatWindow(design_session)
    qtbot.addWidget(other)
    other.apply_state(state)
    assert other._presets.experimenter == ["Prompt one"]
    assert other._presets.participant == ["Yes", "No"]
    window.cleanup()
    other.cleanup()
