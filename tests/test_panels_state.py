"""gather_state / apply_state round-trips for every modality panel.

Panels construct headlessly from a design session (no run folder, no hardware);
streams open only on play/record, not at construction. The Devices panel
enumerates hardware at build time, so it takes the ``mock_devices`` fixture. The
five stateful panels round-trip their persisted keys; the three that keep no
per-panel state (their config lives at the window/session level) just confirm an
empty contribution.
"""

from __future__ import annotations

import logging

import pytest

from smacc import winvolume
from smacc.panels.audio import AudioCueWindow
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


def test_visual_panel_round_trips(qtbot, design_session):
    panel = VisualWindow(design_session)
    qtbot.addWidget(panel)
    panel.apply_state({"blink_color": "#123456", "blink_length": 2.5})
    got = panel.gather_state()
    assert got["blink_color"].lower() == "#123456"
    assert got["blink_length"] == pytest.approx(2.5)


def test_volume_panel_round_trips_cap(qtbot, design_session, monkeypatch):
    # The read-only Windows volume read-out uses COM; stub it so the panel builds
    # deterministically off any audio endpoint.
    monkeypatch.setattr(winvolume, "endpoint_volume", lambda: None)
    monkeypatch.setattr(winvolume, "app_volume", lambda: None)
    panel = VolumeWindow(design_session)
    qtbot.addWidget(panel)
    panel.apply_state({"volume_cap": 0.50})
    assert panel.gather_state() == {"volume_cap": pytest.approx(0.50)}
    # apply_state also drives the live session cap (read by the audio callbacks).
    assert design_session.volume_cap == pytest.approx(0.50)


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


def test_intercom_panel_has_no_persisted_state(qtbot, design_session):
    panel = IntercomWindow(design_session)
    qtbot.addWidget(panel)
    assert panel.gather_state() == {}


def test_devices_panel_has_no_persisted_state(qtbot, design_session, mock_devices):
    panel = DevicesWindow(design_session)
    qtbot.addWidget(panel)
    assert panel.gather_state() == {}
