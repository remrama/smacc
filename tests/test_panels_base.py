"""Tests for the pure helpers in panels.base (need a QApplication, no hardware).

``describe_action`` is pure logic over a DeviceConfig; the combo helpers and
``make_section_title`` build throwaway widgets, so they take the pytest-qt
``qtbot`` fixture (which guarantees a QApplication) and register widgets for
cleanup.
"""

from __future__ import annotations

from PyQt6 import QtCore, QtWidgets

from smacc import devices
from smacc.panels import base

# ----- describe_action -------------------------------------------------------


def _session_with(headless_session, bindings, routing=None):
    headless_session.devices = devices.DeviceConfig(
        bindings=dict(bindings), routing=dict(routing or {})
    )
    return headless_session


def test_describe_target_bound_device_reads_role_arrow_device(headless_session):
    session = _session_with(headless_session, {"bedroom_speaker": "Speakers (USB)"})
    # play_audio_cue defaults to the bedroom_speaker equipment, which is bound above.
    assert (
        base.describe_action(session, "play_audio_cue")
        == "Bedroom speaker → Speakers (USB)"
    )


def test_describe_target_unbound_audio_reads_not_set(headless_session):
    # No silent system-default fallback (#139): an unbound equipment reads "(not set)".
    session = _session_with(headless_session, {})
    assert (
        base.describe_action(session, "record_dream_report")
        == "Bedroom mic 1 (not set)"
    )


def test_describe_target_unbound_visual_reads_not_set(headless_session):
    session = _session_with(headless_session, {})
    assert (
        base.describe_action(session, "play_visual_cue") == "BlinkStick light (not set)"
    )


def test_describe_target_off_route_reads_off(headless_session):
    # listen_audio_cue is an optional route whose default equipment is "" (off).
    session = _session_with(headless_session, {})
    assert base.describe_action(session, "listen_audio_cue") == "off"


def test_describe_role_bound_and_unbound(headless_session):
    # The Talk/Listen source mics (#160) are described directly, without an action.
    session = _session_with(headless_session, {"control_mic": "Headset Mic"})
    assert (
        base.describe_equipment(session, devices.TALK_SOURCE)
        == "Control-room mic → Headset Mic"
    )
    assert (
        base.describe_equipment(session, devices.LISTEN_SOURCE)
        == "Bedroom mic 1 (not set)"
    )


# ----- require_device / require_equipment_device (#139) ----------------------------


def _capture_errors(monkeypatch, session) -> list[tuple]:
    errors: list[tuple] = []
    monkeypatch.setattr(session, "show_error_popup", lambda *a, **k: errors.append(a))
    return errors


def test_require_device_unbound_role_pops_error_and_returns_none(
    headless_session, monkeypatch
):
    session = _session_with(headless_session, {})
    errors = _capture_errors(monkeypatch, session)
    got = base.require_device(
        session,
        "play_audio_cue",
        devices.OUTPUT,
        failure="Could not play.",
        parent=None,
    )
    assert got is None
    assert errors and errors[0][0] == "Could not play."
    assert "Bedroom speaker" in errors[0][1]  # names the unbound equipment


def test_require_device_off_route_pops_error_and_returns_none(
    headless_session, monkeypatch
):
    # listen_audio_cue's default route is off — no equipment to resolve through.
    session = _session_with(headless_session, {})
    errors = _capture_errors(monkeypatch, session)
    got = base.require_device(
        session,
        "listen_audio_cue",
        devices.OUTPUT,
        failure="Could not play.",
        parent=None,
    )
    assert got is None
    assert errors and "not routed" in errors[0][1]


def test_require_device_bound_role_resolves_without_error(
    headless_session, monkeypatch
):
    _patch_sd(monkeypatch)
    session = _session_with(
        headless_session, {"bedroom_speaker": "Speakers (Realtek(R) Audio)"}
    )
    errors = _capture_errors(monkeypatch, session)
    got = base.require_device(
        session,
        "play_audio_cue",
        devices.OUTPUT,
        failure="Could not play.",
        parent=None,
    )
    assert got == 3  # the WASAPI index (see the resolve_device tests below)
    assert errors == []


def test_require_role_device_unbound_pops_error_and_returns_none(
    headless_session, monkeypatch
):
    session = _session_with(headless_session, {})
    errors = _capture_errors(monkeypatch, session)
    got = base.require_equipment_device(
        session,
        devices.LISTEN_SOURCE,
        devices.INPUT,
        failure="Could not listen.",
        parent=None,
    )
    assert got is None
    assert errors and "Bedroom mic 1" in errors[0][1]


# ----- resolve_device --------------------------------------------------------

# A Realtek-style layout: the same short name once per host API (the MME name is
# only truncated past 31 chars, so short names collide exactly — issue seen live:
# sounddevice raises "Multiple output devices found" on the bare name).
_HOST_APIS = [
    {"name": "MME"},
    {"name": "Windows DirectSound"},
    {"name": "Windows WASAPI"},
]
_DEVICES = [
    {
        "name": "Speakers (Realtek(R) Audio)",
        "hostapi": 0,
        "max_output_channels": 2,
        "max_input_channels": 0,
    },
    {
        "name": "Microphone (Realtek(R) Audio)",
        "hostapi": 0,
        "max_output_channels": 0,
        "max_input_channels": 2,
    },
    {
        "name": "Speakers (Realtek(R) Audio)",
        "hostapi": 1,
        "max_output_channels": 2,
        "max_input_channels": 0,
    },
    {
        "name": "Speakers (Realtek(R) Audio)",
        "hostapi": 2,
        "max_output_channels": 2,
        "max_input_channels": 0,
    },
    {
        "name": "Microphone (Realtek(R) Audio)",
        "hostapi": 2,
        "max_output_channels": 0,
        "max_input_channels": 2,
    },
]


def _patch_sd(monkeypatch, host_apis=_HOST_APIS, device_list=_DEVICES):
    monkeypatch.setattr(base.sd, "query_hostapis", lambda: host_apis)
    monkeypatch.setattr(base.sd, "query_devices", lambda: device_list)


def test_resolve_device_picks_the_wasapi_index(monkeypatch):
    _patch_sd(monkeypatch)
    assert base.resolve_device("Speakers (Realtek(R) Audio)", devices.OUTPUT) == 3
    assert base.resolve_device("Microphone (Realtek(R) Audio)", devices.INPUT) == 4


def test_resolve_device_respects_the_channel_kind(monkeypatch):
    # The speaker name only exists as an output; resolving it as an *input*
    # finds no WASAPI match and falls back to the name (sounddevice then raises
    # its usual "no matching device" error).
    _patch_sd(monkeypatch)
    assert (
        base.resolve_device("Speakers (Realtek(R) Audio)", devices.INPUT)
        == "Speakers (Realtek(R) Audio)"
    )


def test_resolve_device_blank_is_none(monkeypatch):
    # "" / None mean "nothing bound" — callers guard via require_device instead
    # of opening a stream on the PortAudio default (#139).
    _patch_sd(monkeypatch)
    assert base.resolve_device("", devices.OUTPUT) is None
    assert base.resolve_device(None, devices.OUTPUT) is None


def test_resolve_device_unplugged_name_passes_through(monkeypatch):
    _patch_sd(monkeypatch)
    assert base.resolve_device("Speakers (USB)", devices.OUTPUT) == "Speakers (USB)"


def test_resolve_device_no_wasapi_host_api_passes_through(monkeypatch):
    _patch_sd(monkeypatch, host_apis=[{"name": "MME"}])
    assert (
        base.resolve_device("Speakers (Realtek(R) Audio)", devices.OUTPUT)
        == "Speakers (Realtek(R) Audio)"
    )


def test_resolve_device_query_failure_passes_through(monkeypatch):
    def boom():
        raise RuntimeError("PortAudio not initialized")

    monkeypatch.setattr(base.sd, "query_hostapis", boom)
    assert (
        base.resolve_device("Speakers (Realtek(R) Audio)", devices.OUTPUT)
        == "Speakers (Realtek(R) Audio)"
    )


# ----- current_device_key ----------------------------------------------------


def test_current_device_key_empty_combo_is_blank(qtbot):
    combo = QtWidgets.QComboBox()
    qtbot.addWidget(combo)
    assert base.current_device_key(combo) == ""


def test_current_device_key_prefers_item_data(qtbot):
    combo = QtWidgets.QComboBox()
    qtbot.addWidget(combo)
    combo.addItem("Visible label", "stable-serial")
    assert base.current_device_key(combo) == "stable-serial"


def test_current_device_key_falls_back_to_text_when_no_data(qtbot):
    combo = QtWidgets.QComboBox()
    qtbot.addWidget(combo)
    combo.addItem("Plain text device")  # no data
    assert base.current_device_key(combo) == "Plain text device"
    combo.clear()
    combo.addItem("Empty-data device", "")  # blank data falls back to text too
    assert base.current_device_key(combo) == "Empty-data device"


# ----- select_saved_device ---------------------------------------------------


def _combo_with_devices(qtbot):
    combo = QtWidgets.QComboBox()
    qtbot.addWidget(combo)
    for name in ("Device A", "Device B", "Device C"):
        combo.addItem(name, name)
    combo.setCurrentIndex(0)
    return combo


def test_select_saved_device_selects_match_and_returns_true(qtbot):
    combo = _combo_with_devices(qtbot)
    assert base.select_saved_device(combo, "Device B") is True
    assert combo.currentText() == "Device B"


def test_select_saved_device_no_match_keeps_selection_and_returns_false(qtbot):
    combo = _combo_with_devices(qtbot)
    assert base.select_saved_device(combo, "Unplugged device") is False
    assert combo.currentIndex() == 0  # selection untouched


def test_select_saved_device_blank_returns_false(qtbot):
    combo = _combo_with_devices(qtbot)
    assert base.select_saved_device(combo, None) is False
    assert base.select_saved_device(combo, "") is False


# ----- make_section_title ----------------------------------------------------


def test_make_section_title_is_centered_18pt(qtbot):
    label = base.make_section_title("Hello")
    qtbot.addWidget(label)
    assert label.text() == "Hello"
    assert label.alignment() == QtCore.Qt.AlignmentFlag.AlignCenter
    assert label.font().pointSize() == 18
