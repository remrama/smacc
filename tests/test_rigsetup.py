"""Tests for the standalone Rig setup tool (edits this machine's rig profile, #300)."""

from smacc import devices, hue, preferences, rigsetup
from smacc.rigsetup import RigSetupWindow


def test_lists_all_equipment_and_loads_saved_bindings(
    qtbot, tmp_path, monkeypatch, mock_devices
):
    monkeypatch.setattr(hue, "targets", lambda cfg: [])  # no Hue network in tests
    prefs_path = tmp_path / "preferences.yaml"
    preferences.update_rig(
        prefs_path, {"bindings": {"bedroom_speaker": mock_devices["outputs"][0]}}
    )
    monkeypatch.setattr(rigsetup, "preferences_path", prefs_path)
    window = RigSetupWindow()
    qtbot.addWidget(window)
    # One dropdown per piece of equipment, and the saved binding is loaded.
    assert set(window._combos) == {e.key for e in devices.EQUIPMENT}
    assert window._bindings["bedroom_speaker"] == mock_devices["outputs"][0]


def test_binding_edit_writes_the_rig_profile(
    qtbot, tmp_path, monkeypatch, mock_devices
):
    monkeypatch.setattr(hue, "targets", lambda cfg: [])
    prefs_path = tmp_path / "preferences.yaml"
    monkeypatch.setattr(rigsetup, "preferences_path", prefs_path)
    window = RigSetupWindow()
    qtbot.addWidget(window)
    combo = window._combos["bedroom_speaker"]
    index = combo.findData(mock_devices["outputs"][0])
    assert index >= 0
    combo.setCurrentIndex(index)  # fires _set_binding -> update_rig
    saved = preferences.rig_bindings(preferences.load_preferences(prefs_path))
    assert saved["bedroom_speaker"] == mock_devices["outputs"][0]


def test_selecting_none_clears_the_binding(qtbot, tmp_path, monkeypatch, mock_devices):
    monkeypatch.setattr(hue, "targets", lambda cfg: [])
    prefs_path = tmp_path / "preferences.yaml"
    preferences.update_rig(
        prefs_path, {"bindings": {"bedroom_speaker": mock_devices["outputs"][0]}}
    )
    monkeypatch.setattr(rigsetup, "preferences_path", prefs_path)
    window = RigSetupWindow()
    qtbot.addWidget(window)
    window._combos["bedroom_speaker"].setCurrentIndex(0)  # the "(none)" row
    saved = preferences.rig_bindings(preferences.load_preferences(prefs_path))
    assert "bedroom_speaker" not in saved


def test_close_emits_closed(qtbot, tmp_path, monkeypatch, mock_devices):
    monkeypatch.setattr(hue, "targets", lambda cfg: [])
    prefs_path = tmp_path / "preferences.yaml"
    monkeypatch.setattr(rigsetup, "preferences_path", prefs_path)
    window = RigSetupWindow()
    qtbot.addWidget(window)
    closed: list[bool] = []
    window.closed.connect(lambda: closed.append(True))
    window.close()
    assert closed == [True]
