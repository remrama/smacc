"""Tests for the main window (SmaccWindow) — the whole GUI, built headless.

Constructing SmaccWindow builds every panel (incl. the hardware-enumerating
Devices window) and the menu/log/editor scaffolding, so these tests take
``mock_devices`` and ``silence_dialogs``. The autouse winvolume stub keeps the
embedded Volume panel off the Windows COM volume API. The settings round-trip is
the save/load contract: gather → apply → gather must be a fixed point.
"""

from __future__ import annotations

import pytest
from PyQt6 import QtWidgets

from smacc import gui, paths, preferences, triggers, winvolume
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
            "bedroom_speaker": mock_devices["outputs"][0],
            "bedroom_mic_1": mock_devices["inputs"][0],
            "blinkstick_light": mock_devices["blinksticks"][0][1],
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
    assert got["devices"]["bindings"]["bedroom_speaker"] == mock_devices["outputs"][0]
    # The bound devices all match advertised hardware, so none are flagged missing.
    assert design_session.missing_devices == []


def test_markers_window_applies_and_persists_trigger_config(
    qtbot, design_session, mock_devices, silence_dialogs, monkeypatch
):
    # The Markers tool window owns the transport config now (no menu dialog).
    monkeypatch.setattr(
        triggers, "list_serial_ports", lambda: [("COM4", "Trigger box")]
    )
    window = SmaccWindow(design_session)
    qtbot.addWidget(window)
    markers = window.panels["markers"]
    markers._load_trigger_config(
        triggers.TriggerConfig(enabled=True, transport="serial", port="COM4")
    )
    markers.apply()
    assert window.session.trigger_config.enabled is True
    assert window.session.trigger_config.port == "COM4"
    # The chosen config travels with the rest of the settings.
    assert window.gather_settings()["trigger_output"]["port"] == "COM4"


def test_markers_apply_rebuilds_the_event_grid(
    qtbot, design_session, mock_devices, silence_dialogs
):
    # Applying a registry change in the Markers window re-renders the event grid
    # (its buttons' tooltips carry each event's code + routing).
    window = SmaccWindow(design_session)
    qtbot.addWidget(window)
    markers = window.panels["markers"]
    i = next(i for i, e in enumerate(markers._events) if e.key == "REMDetected")
    markers._code_spins[i].setValue(99)
    markers.apply()
    grid = window.panels["events"]
    # findChildren still sees the replaced button (deleteLater is only serviced
    # by an event loop), so assert the rebuilt one exists rather than indexing.
    assert any(
        "code 99" in b.toolTip()
        for b in grid.findChildren(QtWidgets.QPushButton)
        if b.text().startswith("REM detected")
    )


def test_grid_add_event_refreshes_the_markers_staging(
    qtbot, design_session, mock_devices, silence_dialogs, monkeypatch
):
    from smacc import dialogs

    window = SmaccWindow(design_session)
    qtbot.addWidget(window)
    monkeypatch.setattr(dialogs.AddEventDialog, "exec", lambda self: True)
    monkeypatch.setattr(
        dialogs.AddEventDialog,
        "get_inputs",
        lambda self: ("Door knock", 150, "", False),
    )
    window.panels["events"].add_custom_event()
    markers = window.panels["markers"]
    assert any(e.label == "Door knock" for e in markers._events)


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


def test_preview_clock_toggle_switches_format_and_persists(
    qtbot, tmp_path, monkeypatch, mock_devices, silence_dialogs
):
    # The 12-hour/24-hour preview clock is a machine preference: toggling it swaps
    # the live formatter and writes preferences.yaml (not the .smacc study file).
    prefs_path = tmp_path / "preferences.yaml"
    monkeypatch.setattr(gui, "preferences_path", prefs_path)

    from smacc.session import SmaccSession

    monkeypatch.setattr(
        SmaccSession,
        "init_lsl_stream",
        lambda self, *a, **k: setattr(self, "outlet", None),
    )
    window = SmaccWindow(SmaccSession(tmp_path / "data", design=False))
    qtbot.addWidget(window)

    # Defaults to 24-hour: the menu item is unchecked and the formatter is 24h.
    assert window._preview_clock_action.isChecked() is False
    assert window.preview_handler.formatter.datefmt == "%H:%M:%S"

    window._preview_clock_action.trigger()  # → 12-hour (AM/PM)

    assert window.preview_handler.formatter.datefmt == "%I:%M:%S %p"
    saved = preferences.load_preferences(prefs_path)
    assert saved["log_preview_clock"] == "12h"

    window.session.close()


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


# ----- editor close prompts only when there are unsaved changes (#183) --------


def _watch_close_prompt(monkeypatch):
    """Record the editor's "save before closing?" prompt instead of blocking."""
    prompts: list[str] = []

    def fake_exec(self):
        prompts.append(self.text())
        return QtWidgets.QMessageBox.StandardButton.Discard

    monkeypatch.setattr(QtWidgets.QMessageBox, "exec", fake_exec)
    return prompts


def test_editor_close_without_changes_skips_prompt(
    qtbot, design_session, mock_devices, silence_dialogs, monkeypatch
):
    window = SmaccWindow(design_session)
    qtbot.addWidget(window)
    prompts = _watch_close_prompt(monkeypatch)
    assert window.close() is True
    assert prompts == []


def test_editor_close_after_edit_prompts(
    qtbot, design_session, mock_devices, silence_dialogs, monkeypatch
):
    window = SmaccWindow(design_session)
    qtbot.addWidget(window)
    # Session metadata is part of the saved file (File → Session info…).
    window.session.metadata["notes"] = "tweaked"
    prompts = _watch_close_prompt(monkeypatch)
    assert window.close() is True  # Discard → still closes
    assert len(prompts) == 1


def test_editor_close_after_undone_edit_skips_prompt(
    qtbot, design_session, mock_devices, silence_dialogs, monkeypatch
):
    # State equality (not an edit-signal flag) is the dirty check, so editing
    # and then undoing back to the original counts as clean.
    window = SmaccWindow(design_session)
    qtbot.addWidget(window)
    original = window.session.metadata.get("notes", "")
    window.session.metadata["notes"] = "tweaked"
    window.session.metadata["notes"] = original
    prompts = _watch_close_prompt(monkeypatch)
    assert window.close() is True
    assert prompts == []


def test_editor_save_marks_clean(
    qtbot, design_session, mock_devices, silence_dialogs, monkeypatch, tmp_path
):
    window = SmaccWindow(design_session)
    qtbot.addWidget(window)
    window.session.metadata["notes"] = "tweaked"
    assert window._write_settings(str(tmp_path / "study.smacc")) is True
    prompts = _watch_close_prompt(monkeypatch)
    assert window.close() is True
    assert prompts == []


# ----- metadata precedence: the start-of-session prompt wins (#184) -----------


def test_live_session_keeps_prompted_metadata_over_file_metadata(
    qtbot, live_session, mock_devices, silence_dialogs
):
    # The start-of-session prompt (already prefilled from the file) owns the
    # metadata; loading the file must not overwrite or restore values, or a
    # field the operator edited/cleared in the prompt would silently revert.
    live_session.metadata.update({"subject": "tonight", "session": ""})
    window = SmaccWindow(live_session)
    qtbot.addWidget(window)
    window._apply_loaded_settings(
        window.gather_settings(), {"subject": "template", "session": "ses-9"}
    )
    assert live_session.metadata["subject"] == "tonight"
    assert live_session.metadata["session"] == ""


def test_editor_adopts_loaded_file_metadata(
    qtbot, design_session, mock_devices, silence_dialogs
):
    # The editor has no start prompt; a loaded file's metadata lands so it can
    # be viewed/edited and saved back.
    window = SmaccWindow(design_session)
    qtbot.addWidget(window)
    window._apply_loaded_settings(window.gather_settings(), {"subject": "template"})
    assert design_session.metadata["subject"] == "template"
