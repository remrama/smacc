"""gather_state / apply_state round-trips for every modality panel.

Panels construct headlessly from a design session (no run folder, no hardware);
streams open only on play/record, not at construction. The Devices panel
enumerates hardware at build time, so it takes the ``mock_devices`` fixture. The
stateful panels round-trip their persisted keys; the panels that keep no per-panel
state (their config lives at the window/session level) just confirm an empty
contribution.
"""

from __future__ import annotations

import logging

import pytest

from smacc import winvolume
from smacc.panels.audio import AudioCueWindow
from smacc.panels.biocals import BiocalsWindow
from smacc.panels.devices import DevicesWindow
from smacc.panels.events import EventsWindow
from smacc.panels.intercom import IntercomWindow
from smacc.panels.noise import NoiseWindow
from smacc.panels.recording import RecordingWindow
from smacc.panels.visual import VisualWindow
from smacc.panels.volume import VolumeWindow

# ----- stateful panels -------------------------------------------------------


def test_audio_panel_round_trips_cues_and_envelope(qtbot, design_session):
    panel = AudioCueWindow(design_session)
    qtbot.addWidget(panel)
    state = {
        "cues": [
            {"name": "Alarm", "file": "", "volume": 0.40, "loop": True},
            {"name": "Chime", "file": "", "volume": 0.20, "loop": False},
        ],
        "cue_attack": 0.5,
        "cue_release": 1.5,
    }
    panel.apply_state(state)
    got = panel.gather_state()
    assert got["cue_attack"] == pytest.approx(0.5)
    assert got["cue_release"] == pytest.approx(1.5)
    assert len(got["cues"]) == 2
    assert got["cues"][0]["name"] == "Alarm"
    assert got["cues"][0]["volume"] == pytest.approx(0.40)
    assert got["cues"][0]["loop"] is True
    assert got["cues"][1]["name"] == "Chime"
    assert got["cues"][1]["loop"] is False


def test_audio_panel_ignores_malformed_numeric_settings(qtbot, design_session):
    panel = AudioCueWindow(design_session)
    qtbot.addWidget(panel)
    before = panel.gather_state()
    panel.apply_state(
        {
            "cues": [{"name": "Bad numbers", "file": "", "volume": "loud"}],
            "cue_attack": "fast",
            "cue_release": object(),
        }
    )
    got = panel.gather_state()
    assert got["cue_attack"] == before["cue_attack"]
    assert got["cue_release"] == before["cue_release"]
    assert got["cues"][0]["volume"] == before["cues"][0]["volume"]


def test_noise_panel_round_trips(qtbot, design_session):
    panel = NoiseWindow(design_session)
    qtbot.addWidget(panel)
    state = {
        "noise_volume": 0.30,
        "noise_color": "pink",
        "noise_source": "file",
        "noise_file": "loop.wav",
    }
    panel.apply_state(state)
    got = panel.gather_state()
    assert got["noise_volume"] == pytest.approx(0.30)
    assert got["noise_color"] == "pink"
    assert got["noise_source"] == "file"
    assert got["noise_file"] == "loop.wav"


def test_noise_panel_ignores_malformed_numeric_settings(qtbot, design_session):
    panel = NoiseWindow(design_session)
    qtbot.addWidget(panel)
    before = panel.gather_state()["noise_volume"]
    panel.apply_state({"noise_volume": "loud"})
    assert panel.gather_state()["noise_volume"] == before


def test_recording_panel_round_trips_surveys(qtbot, design_session):
    panel = RecordingWindow(design_session)
    qtbot.addWidget(panel)
    state = {
        "survey_url": "https://survey.example/post",
        "survey_options": {"Post survey": "https://survey.example/post"},
    }
    panel.apply_state(state)
    got = panel.gather_state()
    assert got["survey_url"] == "https://survey.example/post"
    assert got["survey_options"] == {"Post survey": "https://survey.example/post"}


def test_recording_panel_offers_builtin_surveys_without_persisting_them(
    qtbot, design_session
):
    """Built-ins (#114) show in the dropdown and menu but never enter the study."""
    panel = RecordingWindow(design_session)
    qtbot.addWidget(panel)
    available = panel.available_surveys()
    assert available.get("DLQ") == "smacc://survey/dlq"
    # Selecting a built-in persists as the chosen survey_url…
    panel.apply_state({"survey_url": "smacc://survey/dlq", "survey_options": {}})
    got = panel.gather_state()
    assert got["survey_url"] == "smacc://survey/dlq"
    # …but built-ins stay out of the persisted preset mapping.
    assert got["survey_options"] == {}


def test_intercom_panel_round_trips_chat_presets(qtbot, design_session):
    # The Intercom panel persists the shared chat quick-reply presets (#112).
    panel = IntercomWindow(design_session)
    qtbot.addWidget(panel)
    panel.apply_state(
        {
            "chat_experimenter_presets": ["Are you awake?"],
            "chat_participant_presets": ["Yes", "No"],
        }
    )
    got = panel.gather_state()
    assert got["chat_experimenter_presets"] == ["Are you awake?"]
    assert got["chat_participant_presets"] == ["Yes", "No"]


def test_intercom_meters_track_each_live_bridge(qtbot, design_session):
    # Each direction has a level meter fed from its bridge's input callback; an
    # idle direction's meter reads empty, a live one shows the stashed level.
    panel = IntercomWindow(design_session)
    qtbot.addWidget(panel)
    panel._render_levels()
    assert panel.talkMeter.value() == 0  # both idle
    assert panel.listenMeter.value() == 0
    # Simulate a live talk bridge whose callback measured a -20 dBFS block.
    panel._talk._input = object()  # active() keys off an open stream
    panel._talk.level_db = -20.0
    panel._render_levels()
    assert panel.talkMeter.value() > 0
    assert "-20 dBFS" in panel.talkMeter.format()
    assert panel.listenMeter.value() == 0  # listen still idle
    panel._talk._input = None


def test_visual_panel_round_trips(qtbot, design_session):
    panel = VisualWindow(design_session)
    qtbot.addWidget(panel)
    panel.apply_state(
        {
            "visual_cues": [
                {
                    "name": "TLR pulse",
                    "color": "#123456",
                    "brightness": 0.7,
                    "pattern": "pulse",
                    "rate": 2.0,
                    "length": 2.5,
                    "loop": True,
                },
                {"name": "Sham", "color": "#ffffff"},
            ],
            "visual_attack": 0.5,
            "visual_release": 1.5,
        }
    )
    got = panel.gather_state()
    cue, sham = got["visual_cues"]
    assert cue["name"] == "TLR pulse"
    assert cue["color"] == "#123456"
    assert cue["brightness"] == pytest.approx(0.7)
    assert cue["pattern"] == "pulse"
    assert cue["rate"] == pytest.approx(2.0)
    assert cue["length"] == pytest.approx(2.5)
    assert cue["loop"] is True
    assert sham["name"] == "Sham"
    assert sham["color"] == "#ffffff"
    assert sham["pattern"] == "steady"  # unspecified fields keep their defaults
    assert got["visual_attack"] == pytest.approx(0.5)
    assert got["visual_release"] == pytest.approx(1.5)


def test_visual_panel_ignores_malformed_numeric_settings(qtbot, design_session):
    panel = VisualWindow(design_session)
    qtbot.addWidget(panel)
    before = panel.gather_state()
    panel.apply_state(
        {
            "visual_cues": [
                {
                    "name": "Bad numbers",
                    "brightness": "bright",
                    "rate": object(),
                    "length": "long",
                }
            ],
            "visual_attack": "fast",
            "visual_release": "slow",
        }
    )
    got = panel.gather_state()
    assert got["visual_attack"] == before["visual_attack"]
    assert got["visual_release"] == before["visual_release"]
    assert got["visual_cues"][0]["brightness"] == before["visual_cues"][0]["brightness"]
    assert got["visual_cues"][0]["rate"] == before["visual_cues"][0]["rate"]
    assert got["visual_cues"][0]["length"] == before["visual_cues"][0]["length"]


def test_volume_panel_round_trips_cap(qtbot, design_session, monkeypatch):
    # The read-only Windows volume read-out uses COM; stub it so the panel builds
    # deterministically off any audio endpoint.
    monkeypatch.setattr(winvolume, "endpoint_volume", lambda: None)
    monkeypatch.setattr(winvolume, "app_volume", lambda: None)
    panel = VolumeWindow(design_session)
    qtbot.addWidget(panel)
    panel.apply_state({"volume_cap": 0.50, "output_latency": "low"})
    assert panel.gather_state() == {
        "volume_cap": pytest.approx(0.50),
        "output_latency": "low",
    }
    # apply_state also drives the live session state: the cap (read by the audio
    # callbacks) and the latency mode (read when a stimulus stream opens).
    assert design_session.volume_cap == pytest.approx(0.50)
    assert design_session.output_latency == "low"


def test_volume_panel_ignores_malformed_numeric_settings(
    qtbot, design_session, monkeypatch
):
    monkeypatch.setattr(winvolume, "endpoint_volume", lambda: None)
    monkeypatch.setattr(winvolume, "app_volume", lambda: None)
    panel = VolumeWindow(design_session)
    qtbot.addWidget(panel)
    before = panel.gather_state()["volume_cap"]
    panel.apply_state({"volume_cap": "full"})
    assert panel.gather_state()["volume_cap"] == before
    assert design_session.volume_cap == before


def test_biocals_panel_round_trips_stack(qtbot, design_session):
    panel = BiocalsWindow(design_session)
    qtbot.addWidget(panel)
    state = {
        "biocals": {
            "voice_volume": 0.25,
            "rows": [
                # eyes_closed twice: rows are instances, repeats are legitimate.
                {
                    "biocal": "eyes_closed",
                    "sequence": True,
                    "voice": False,
                    "duration": 45,
                },
                {
                    "biocal": "lrlr_open",
                    "sequence": True,
                    "voice": True,
                    "duration": 20,
                },
                {
                    "biocal": "eyes_closed",
                    "sequence": False,
                    "voice": True,
                    "duration": 30,
                },
            ],
        }
    }
    panel.apply_state(state)
    got = panel.gather_state()["biocals"]
    assert got["voice_volume"] == pytest.approx(0.25)
    assert [r["biocal"] for r in got["rows"]] == [
        "eyes_closed",
        "lrlr_open",
        "eyes_closed",
    ]
    assert got["rows"][0] == {
        "biocal": "eyes_closed",
        "sequence": True,
        "voice": False,
        "duration": 45,
    }
    assert got["rows"][1]["duration"] == 20


def test_biocals_panel_keeps_default_stack_for_older_studies(qtbot, design_session):
    # A pre-v7 state has no biocals block; the default 18-row stack stands.
    panel = BiocalsWindow(design_session)
    qtbot.addWidget(panel)
    panel.apply_state({"noise_volume": 0.3})
    assert len(panel.gather_state()["biocals"]["rows"]) == 18
    # A block without rows (the shipped default.smacc) also keeps the stack.
    panel.apply_state({"biocals": {"voice_volume": 0.4}})
    got = panel.gather_state()["biocals"]
    assert len(got["rows"]) == 18
    assert got["voice_volume"] == pytest.approx(0.4)


def _capture_session_log(session) -> list[logging.LogRecord]:
    """Attach a recording handler to a session's logger and return its record list.

    The session logger sets ``propagate=False`` (and design mode only has a
    NullHandler), so pytest's ``caplog`` — which captures on the root logger —
    never sees these records; capture on the logger directly instead.
    """
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    session.logger.addHandler(_Capture())
    return records


def test_volume_panel_logs_windows_levels_on_refresh(
    qtbot, design_session, monkeypatch
):
    # Each actual read of the Windows volumes is logged at INFO for reproducibility.
    monkeypatch.setattr(winvolume, "endpoint_volume", lambda: 0.85)
    monkeypatch.setattr(winvolume, "app_volume", lambda: 0.50)
    panel = VolumeWindow(design_session)  # constructor calls refresh_levels() once
    qtbot.addWidget(panel)
    records = _capture_session_log(design_session)
    panel.refresh_levels()
    windows_lines = [
        r for r in records if r.getMessage().startswith("Windows output volume:")
    ]
    assert windows_lines, "a refresh should log the read Windows volumes"
    record = windows_lines[-1]
    assert record.levelno == logging.INFO
    assert "endpoint 85%" in record.getMessage()
    assert "SMACC mixer 50%" in record.getMessage()


def test_volume_panel_refresh_reports_unavailable_levels(
    qtbot, design_session, monkeypatch
):
    # When the COM read fails (non-Windows / no endpoint), the log says so rather
    # than crashing on a None percentage.
    monkeypatch.setattr(winvolume, "endpoint_volume", lambda: None)
    monkeypatch.setattr(winvolume, "app_volume", lambda: None)
    panel = VolumeWindow(design_session)
    qtbot.addWidget(panel)
    records = _capture_session_log(design_session)
    panel.refresh_levels()
    messages = [r.getMessage() for r in records]
    assert (
        "Windows output volume: endpoint unavailable, SMACC mixer unavailable"
        in messages
    )


# ----- stateless panels (their config lives at window/session level) ---------


def test_events_panel_has_no_persisted_state(qtbot, design_session):
    panel = EventsWindow(design_session)
    qtbot.addWidget(panel)
    assert panel.gather_state() == {}


def test_devices_panel_has_no_persisted_state(qtbot, design_session, mock_devices):
    panel = DevicesWindow(design_session)
    qtbot.addWidget(panel)
    assert panel.gather_state() == {}


# ----- per-window always-on-top (ModalityWindow base) ------------------------


def test_tool_window_always_on_top_toggle(qtbot, design_session):
    panel = NoiseWindow(design_session)
    qtbot.addWidget(panel)
    assert panel.is_always_on_top() is False  # default off
    # Every window binds the same window-scoped shortcut to its own toggle.
    assert panel._always_on_top_action.shortcut().toString() == "Ctrl+T"
    panel.set_always_on_top(True)
    assert panel.is_always_on_top() is True
    assert panel._always_on_top_action.isChecked() is True
    # The window flag tracks the toggle.
    from PyQt6 import QtCore

    assert bool(panel.windowFlags() & QtCore.Qt.WindowType.WindowStaysOnTopHint)
    panel.set_always_on_top(False)
    assert panel.is_always_on_top() is False
    assert not bool(panel.windowFlags() & QtCore.Qt.WindowType.WindowStaysOnTopHint)


def test_tool_window_stays_visible_across_always_on_top_toggle(qtbot, design_session):
    """Toggling always-on-top must not hide a visible window (regression).

    setWindowFlag natively hides the window, so the re-show guard has to read
    visibility before applying the flag — checking after always saw False and the
    window vanished on every toggle.
    """
    panel = NoiseWindow(design_session)
    qtbot.addWidget(panel)
    panel.show()
    qtbot.waitExposed(panel)
    panel.toggle_always_on_top(True)
    assert panel.isVisible()
    panel.toggle_always_on_top(False)
    assert panel.isVisible()
    # A hidden window must stay hidden when settings application toggles the flag.
    panel.hide()
    panel.set_always_on_top(True)
    assert not panel.isVisible()


def test_tool_window_file_menu_close_hides_the_window(qtbot, design_session):
    # Every tool window carries File → Close window (Ctrl+W); closing only hides
    # the window (the session keeps running), exactly like the title-bar X.
    panel = NoiseWindow(design_session)
    qtbot.addWidget(panel)
    panel.show()
    qtbot.waitExposed(panel)
    close = next(
        (
            a
            for a in panel.menuBar().actions()[0].menu().actions()
            if a.text().replace("&", "") == "Close window"
        ),
        None,
    )
    assert close is not None
    assert close.shortcut().toString() == "Ctrl+W"
    close.trigger()
    assert not panel.isVisible()
    panel.show()  # reopens with its state intact, like the launcher buttons do
    assert panel.isVisible()
