"""Tests for the pure helpers in panels.base (need a QApplication, no hardware).

``describe_target`` is pure logic over a DeviceConfig; the combo helpers and
``make_section_title`` build throwaway widgets, so they take the pytest-qt
``qtbot`` fixture (which guarantees a QApplication) and register widgets for
cleanup.
"""

from __future__ import annotations

from PyQt6 import QtCore, QtWidgets

from smacc import devices
from smacc.panels import base

# ----- describe_target -------------------------------------------------------


def _session_with(design_session, bindings, routing=None):
    design_session.devices = devices.DeviceConfig(
        bindings=dict(bindings), routing=dict(routing or {})
    )
    return design_session


def test_describe_target_bound_device_reads_role_arrow_device(design_session):
    session = _session_with(design_session, {"bedroom_out": "Speakers (USB)"})
    # cue_out defaults to the bedroom_out role, which is bound above.
    assert (
        base.describe_target(session, "cue_out") == "Bedroom speakers → Speakers (USB)"
    )


def test_describe_target_unbound_audio_reads_system_default(design_session):
    session = _session_with(design_session, {})
    assert base.describe_target(session, "report_in") == "Bedroom mic (system default)"


def test_describe_target_unbound_visual_reads_not_set(design_session):
    session = _session_with(design_session, {})
    assert base.describe_target(session, "visual_out") == "BlinkStick (not set)"


def test_describe_target_off_route_reads_off(design_session):
    # cue_monitor is an optional route whose default role is "" (off).
    session = _session_with(design_session, {})
    assert base.describe_target(session, "cue_monitor") == "off"


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
