"""Tests for the main window (SmaccWindow) — the whole GUI, built headless.

Constructing SmaccWindow builds every panel (incl. the hardware-enumerating
Devices window) and the menu/log/editor scaffolding, so these tests take
``mock_devices`` and ``silence_dialogs``. The autouse winvolume stub keeps the
embedded Volume panel off the Windows COM volume API. The settings round-trip is
the save/load contract: gather → apply → gather must be a fixed point.
"""

from __future__ import annotations

import pytest

from smacc import gui, triggers, winvolume
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


def test_devices_refresh_button_runs_window_rescan(
    qtbot, live_session, mock_devices, silence_dialogs, monkeypatch
):
    # The Devices window's Refresh button must drive the same rescan as
    # File ▸ Refresh devices (F5), not a parallel one. Stub the real rescan (it
    # would re-init PortAudio) on the class so the wired-up connection hits it.
    calls: list[bool] = []
    monkeypatch.setattr(
        SmaccWindow, "refresh_all_devices", lambda self: calls.append(True)
    )
    window = SmaccWindow(live_session)
    qtbot.addWidget(window)
    window.devices_window.refresh_requested.emit()
    assert calls == [True]


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


def test_edit_trigger_output_applies_and_persists_config(
    qtbot, design_session, mock_devices, silence_dialogs, monkeypatch
):
    new_cfg = triggers.TriggerConfig(enabled=True, transport="serial", port="COM4")

    class _StubDialog:
        def __init__(self, *args, **kwargs):
            pass

        def exec(self):
            return 1  # accepted

        def get_config(self):
            return new_cfg

    monkeypatch.setattr(gui, "TriggerOutputDialog", _StubDialog)
    window = SmaccWindow(design_session)
    qtbot.addWidget(window)
    window.edit_trigger_output()
    assert window.session.trigger_config == new_cfg
    # The chosen config travels with the rest of the settings.
    assert window.gather_settings()["trigger_output"]["port"] == "COM4"


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


# ----- interface choices carried by the .smacc settings -----------------------


def test_gather_settings_includes_interface_choices(
    qtbot, live_session, mock_devices, silence_dialogs
):
    window = SmaccWindow(live_session)
    qtbot.addWidget(window)
    state = window.gather_settings()
    # Carried in the portable settings file so they travel with the study.
    assert isinstance(state["preview_levels"], list)
    assert state["always_on_top"] is False  # main window, default off
    # A per-tool always-on-top map keyed by panel key (default all off).
    assert set(state["tool_always_on_top"]) == set(window.panels)
    assert all(v is False for v in state["tool_always_on_top"].values())


def test_default_interface_choices_when_settings_omit_them(
    qtbot, live_session, mock_devices, silence_dialogs
):
    # A study that omits preview_levels/always_on_top; the defaults must stand.
    window = SmaccWindow(live_session)
    qtbot.addWidget(window)
    state = window.gather_settings()
    state.pop("preview_levels")
    state.pop("always_on_top")
    state.pop("tool_always_on_top")
    window.apply_settings(state)
    # Default preview levels are INFO and above (all but DEBUG).
    assert window.gather_settings()["preview_levels"] == [
        "INFO",
        "WARNING",
        "ERROR",
        "CRITICAL",
    ]
    assert window.gather_settings()["always_on_top"] is False


def test_interface_choices_round_trip_through_settings(
    qtbot, live_session, mock_devices, silence_dialogs
):
    window = SmaccWindow(live_session)
    qtbot.addWidget(window)
    state = window.gather_settings()
    state["preview_levels"] = ["DEBUG", "INFO"]
    state["always_on_top"] = True
    state["tool_always_on_top"] = dict.fromkeys(window.panels, False)
    state["tool_always_on_top"]["events"] = True
    window.apply_settings(state)
    got = window.gather_settings()
    assert got["preview_levels"] == ["DEBUG", "INFO"]
    assert got["always_on_top"] is True
    assert got["tool_always_on_top"]["events"] is True
    # The main window's flag and the events tool's flag both followed the settings.
    assert window._always_on_top_action.isChecked() is True
    assert window.panels["events"].is_always_on_top() is True


def test_editor_preserves_preview_levels_round_trip(
    qtbot, design_session, mock_devices, silence_dialogs
):
    # The editor has no live preview pane, but it must not wipe a study's
    # preview_levels on save — it round-trips the loaded value verbatim.
    window = SmaccWindow(design_session)
    qtbot.addWidget(window)
    state = window.gather_settings()
    state["preview_levels"] = ["DEBUG", "WARNING"]
    window.apply_settings(state)
    assert window.gather_settings()["preview_levels"] == ["DEBUG", "WARNING"]


# ----- per-window geometry persistence (machine-local preferences.yaml) -------


def test_tool_window_geometry_persists_and_restores(
    qtbot, tmp_path, monkeypatch, mock_devices, silence_dialogs
):
    # Geometry is stored machine-local; point the prefs file at a temp path so the
    # test never touches the real one.
    prefs_path = tmp_path / "preferences.yaml"
    monkeypatch.setattr(gui, "preferences_path", prefs_path)

    from smacc.session import SmaccSession

    monkeypatch.setattr(
        SmaccSession,
        "init_lsl_stream",
        lambda self, *a, **k: setattr(self, "outlet", None),
    )

    first = SmaccWindow(SmaccSession(tmp_path / "data", design=False))
    qtbot.addWidget(first)
    first._open_panel("volume")  # places + marks it positioned
    first.panels["volume"].move(321, 234)
    first._teardown_panels()  # persists each opened panel's geometry
    first.session.close()

    # A fresh window reads the saved geometry and reopens the tool there.
    second = SmaccWindow(SmaccSession(tmp_path / "data", design=False))
    qtbot.addWidget(second)
    second._open_panel("volume")
    assert second.panels["volume"].x() == 321
    assert second.panels["volume"].y() == 234
    second._teardown_panels()
    second.session.close()
