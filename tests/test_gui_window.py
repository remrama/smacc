"""Tests for the main window (SmaccWindow) — the whole GUI, built headless.

Constructing SmaccWindow builds every panel (incl. the hardware-enumerating
Devices window) and the menu/log/editor scaffolding, so these tests take
``mock_devices`` and ``silence_dialogs``. The autouse winvolume stub keeps the
embedded Volume panel off the Windows COM volume API. The settings round-trip is
the save/load contract: gather → apply → gather must be a fixed point.
"""

from __future__ import annotations

import pytest

from smacc import gui, paths, triggers, winvolume
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
        "visual_cues",
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


def test_session_file_menu_offers_save_as(
    qtbot, live_session, mock_devices, silence_dialogs, monkeypatch
):
    # A live session can snapshot its current settings to a SMACC file from
    # File → Save SMACC file as… (wired to the existing export path). The class
    # is patched *before* construction — the menu action captures the bound
    # method then, and the real one would block on a modal file dialog.
    called: list[bool] = []
    monkeypatch.setattr(
        SmaccWindow, "export_settings", lambda self: called.append(True) or True
    )
    window = SmaccWindow(live_session)
    qtbot.addWidget(window)
    save_as = next(
        (
            a
            for a in window.menuBar().actions()[0].menu().actions()
            if a.text().replace("&", "") == "Save SMACC file as…"
        ),
        None,
    )
    assert save_as is not None
    save_as.trigger()
    assert called == [True]


def test_devices_refresh_button_runs_window_rescan(
    qtbot, live_session, mock_devices, silence_dialogs, monkeypatch
):
    # The Devices window's Refresh button (and its F5 shortcut) must drive the
    # window rescan, not a parallel one. Stub the real rescan (it would re-init
    # PortAudio) on the class so the wired-up connection hits it.
    calls: list[bool] = []
    monkeypatch.setattr(
        SmaccWindow, "refresh_all_devices", lambda self: calls.append(True)
    )
    window = SmaccWindow(live_session)
    qtbot.addWidget(window)
    window.devices_window.refresh_requested.emit()
    assert calls == [True]


def test_hotplug_rescan_is_debounced_through_a_single_shot_timer(
    qtbot, live_session, mock_devices, silence_dialogs, monkeypatch
):
    # Windows fires device-change signals in bursts; each rescan re-inits
    # PortAudio, and doing that dozens of times back-to-back has crashed the app.
    # The signals must therefore only restart a single-shot timer, with the
    # rescan running once when the timer fires.
    calls: list[bool] = []
    monkeypatch.setattr(
        SmaccWindow, "_on_devices_hotplug", lambda self: calls.append(True)
    )
    window = SmaccWindow(live_session)
    qtbot.addWidget(window)
    timer = window._hotplug_timer
    assert timer.isSingleShot()
    assert timer.interval() >= 500  # long enough to outlast a signal burst
    # A burst of change signals leaves the timer pending without rescanning…
    timer.start()
    timer.start()
    timer.start()
    assert timer.isActive()
    assert calls == []
    # …and the rescan runs exactly once when the quiet-period timer fires.
    timer.stop()
    timer.timeout.emit()
    assert calls == [True]


# ----- default settings are protected from overwrite -------------------------


def test_is_default_settings_distinguishes_paths(tmp_path):
    assert paths.is_default_settings(paths.DEFAULT_SETTINGS_PATH)
    assert paths.is_default_settings(str(paths.DEFAULT_SETTINGS_PATH))
    assert not paths.is_default_settings(tmp_path / "mine.smacc")


def test_editor_save_of_default_redirects_to_save_as(
    qtbot, design_session, mock_devices, silence_dialogs, monkeypatch
):
    # Editing the seeded default and hitting Save must go to Save-As, never an
    # in-place overwrite of default.smacc (it's SMACC's known-good template).
    window = SmaccWindow(design_session)
    qtbot.addWidget(window)
    window.settings_path = str(paths.DEFAULT_SETTINGS_PATH)
    called: list[bool] = []
    monkeypatch.setattr(window, "export_settings", lambda: called.append(True) or True)
    assert window.save_settings_in_place() is True
    assert called == [True]


def test_write_settings_refuses_the_default_path(
    qtbot, design_session, mock_devices, silence_dialogs
):
    # Even if default.smacc is hand-picked in the Save-As dialog, writing is refused.
    window = SmaccWindow(design_session)
    qtbot.addWidget(window)
    assert window._write_settings(str(paths.DEFAULT_SETTINGS_PATH)) is False


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
    settings["visual_cues"] = [{"name": "Glow", "color": "#abcdef"}]
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
    assert got["visual_cues"][0]["name"] == "Glow"
    assert got["visual_cues"][0]["color"] == "#abcdef"
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


def test_hue_config_round_trips_through_settings(
    qtbot, design_session, mock_devices, silence_dialogs, monkeypatch
):
    from smacc import hue

    # The post-load device re-enumeration must not hit the network.
    monkeypatch.setattr(hue, "targets", lambda cfg: [])
    window = SmaccWindow(design_session)
    qtbot.addWidget(window)
    state = window.gather_settings()
    assert state["hue"] == {"bridge_ip": "", "app_key": ""}
    state["hue"] = {"bridge_ip": "192.168.1.50", "app_key": "k"}
    window.apply_settings(state)
    assert window.gather_settings()["hue"]["bridge_ip"] == "192.168.1.50"
    assert design_session.hue_config.configured
