"""Tests for the main window (SmaccWindow) — the whole GUI, built headless.

Constructing SmaccWindow builds every panel (incl. the hardware-enumerating
Devices window) and the menu/log/editor scaffolding, so these tests take
``mock_devices`` and ``silence_dialogs``. The autouse winvolume stub keeps the
embedded Volume panel off the Windows COM volume API. The settings round-trip is
the save/load contract: gather → apply → gather must be a fixed point.
"""

from __future__ import annotations

import pytest

from smacc import winvolume
from smacc.gui import SmaccWindow


@pytest.fixture(autouse=True)
def _stub_winvolume(monkeypatch):
    monkeypatch.setattr(winvolume, "endpoint_volume", lambda: None)
    monkeypatch.setattr(winvolume, "app_volume", lambda: None)


# ----- construction ----------------------------------------------------------


def test_window_builds_in_design_mode(
    qtbot, design_session, mock_devices, silence_dialogs
):
    window = SmaccWindow(design_session)
    qtbot.addWidget(window)
    assert window.design is True
    state = window.gather_settings()
    # A representative spread of the keys the settings file persists.
    for key in (
        "devices",
        "event_codes",
        "event_code_safe_max",
        "data_directory",
        "volume_cap",
        "noise_color",
        "blink_color",
        "cues",
    ):
        assert key in state


def test_window_builds_in_session_mode(
    qtbot, live_session, mock_devices, silence_dialogs
):
    window = SmaccWindow(live_session)
    qtbot.addWidget(window)
    assert window.design is False
    # The session window has the lightswitch (the designer hides it).
    assert hasattr(window, "lightswitchButton")


# ----- settings gather/apply contract ----------------------------------------


def test_settings_gather_apply_is_a_fixed_point(
    qtbot, design_session, mock_devices, silence_dialogs
):
    window = SmaccWindow(design_session)
    qtbot.addWidget(window)
    first = window.gather_settings()
    window.apply_settings(first)
    second = window.gather_settings()
    assert second == first


def test_apply_settings_lands_values(
    qtbot, design_session, mock_devices, silence_dialogs
):
    window = SmaccWindow(design_session)
    qtbot.addWidget(window)
    settings = window.gather_settings()
    settings["volume_cap"] = 0.5
    settings["noise_color"] = "brown"
    settings["blink_color"] = "#abcdef"
    settings["cues"] = [{"name": "Buzz", "file": "", "volume": 0.3, "loop": True}]
    settings["devices"] = {
        "bindings": {
            "bedroom_out": mock_devices["outputs"][0],
            "bedroom_mic": mock_devices["inputs"][0],
            "blinkstick": mock_devices["blinksticks"][0][1],
        },
        "routing": {},
    }

    window.apply_settings(settings)
    got = window.gather_settings()
    assert got["volume_cap"] == pytest.approx(0.5)
    assert got["noise_color"] == "brown"
    assert got["blink_color"].lower() == "#abcdef"
    assert got["cues"][0]["name"] == "Buzz"
    assert got["devices"]["bindings"]["bedroom_out"] == mock_devices["outputs"][0]
    # The bound devices all match advertised hardware, so none are flagged missing.
    assert design_session.missing_devices == []


# ----- theme / lights and owned preferences ----------------------------------


def test_set_lights_toggles_state_and_label(
    qtbot, live_session, mock_devices, silence_dialogs
):
    # set_lights drives the lights state, the switch label, and the theme. The
    # offscreen platform doesn't reflect QStyleHints.colorScheme() back, so assert
    # the observable state + label (which only update via the apply_theme path).
    window = SmaccWindow(live_session)
    qtbot.addWidget(window)

    window.set_lights(False)
    assert window.lights_on is False
    assert "OFF" in window.lightswitchButton.text()

    window.set_lights(True)
    assert window.lights_on is True
    assert "ON" in window.lightswitchButton.text()


def test_preference_changes_reports_owned_keys(
    qtbot, live_session, mock_devices, silence_dialogs
):
    window = SmaccWindow(live_session)
    qtbot.addWidget(window)
    changes = window._preference_changes()
    assert set(changes) == {"always_on_top", "preview_levels", "window"}
    assert isinstance(changes["preview_levels"], list)
    assert set(changes["window"]) == {"x", "y", "w", "h"}
