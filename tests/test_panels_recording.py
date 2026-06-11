"""Tests for the dream-recording window: capture lifecycle, surveys, and state.

Headless like the other panel tests: sounddevice is stubbed (no hardware), but the
report WAV is written with the real soundfile into the live session's run folder,
so the on-disk artifact is exercised end to end.
"""

from __future__ import annotations

import numpy as np
import soundfile as sf

from smacc.panels import recording
from smacc.panels.recording import RecordingWindow


class _FakeInput:
    """Stand-in for sd.InputStream that records its lifecycle calls."""

    last: _FakeInput | None = None

    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs
        self.started = False
        self.aborted = False
        self.closed = False
        _FakeInput.last = self

    def start(self):
        self.started = True

    def abort(self):
        self.aborted = True

    def close(self):
        self.closed = True


def _stub_recorder(monkeypatch, stream_cls=_FakeInput, rate=8000.0):
    monkeypatch.setattr(
        recording.sd, "query_devices", lambda *a, **k: {"default_samplerate": rate}
    )
    monkeypatch.setattr(recording.sd, "InputStream", stream_cls)


def test_designer_disables_the_record_button(qtbot, design_session):
    window = RecordingWindow(design_session)
    qtbot.addWidget(window)
    assert not window.micrecordButton.isEnabled()
    window.cleanup()


def test_record_start_to_stop_writes_the_report_wav(
    qtbot, live_session, monkeypatch, silence_dialogs
):
    _stub_recorder(monkeypatch)
    window = RecordingWindow(live_session)
    qtbot.addWidget(window)

    window.micrecordButton.setChecked(True)
    window.start_or_stop_recording()
    assert window.n_report_counter == 1
    assert window.is_streaming()
    assert _FakeInput.last is not None and _FakeInput.last.started
    assert "recording" in window.recordingIndicatorLabel.text()

    # The audio thread delivers a block; it lands in the report file.
    window._record_callback(np.full((64, 1), 0.25, dtype="float32"), 64, None, None)

    window.micrecordButton.setChecked(False)
    window.start_or_stop_recording()
    assert not window.is_streaming()
    assert "idle" in window.recordingIndicatorLabel.text()
    path = live_session.session_dir / "report-01.wav"
    assert path.is_file()
    data, rate = sf.read(path)
    assert rate == 8000 and len(data) == 64
    window.cleanup()


def test_failed_start_reverts_button_and_leaves_no_numbering_gap(
    qtbot, live_session, monkeypatch, silence_dialogs
):
    def boom(*args, **kwargs):
        raise RuntimeError("device busy")

    _stub_recorder(monkeypatch, stream_cls=boom)
    window = RecordingWindow(live_session)
    qtbot.addWidget(window)

    window.micrecordButton.setChecked(True)
    window.start_or_stop_recording()
    assert not window.micrecordButton.isChecked()  # start failed -> reverted
    assert window.n_report_counter == 0
    assert not window.is_streaming()

    # The next (successful) attempt is still report 1 — no gap from the failure.
    _stub_recorder(monkeypatch)
    window.micrecordButton.setChecked(True)
    window.start_or_stop_recording()
    assert window.n_report_counter == 1
    window.micrecordButton.setChecked(False)
    window.start_or_stop_recording()
    assert (live_session.session_dir / "report-01.wav").is_file()
    window.cleanup()


def test_open_in_app_survey_opens_window_and_marks(qtbot, live_session, monkeypatch):
    window = RecordingWindow(live_session)
    qtbot.addWidget(window)
    emitted = []
    monkeypatch.setattr(
        live_session, "emit_event", lambda key, detail=None, **k: emitted.append(key)
    )
    lucid = window._survey_registry["lucid"]  # a bundled built-in
    window.open_survey_url(lucid.url)
    assert len(window._survey_windows) == 1
    assert emitted == ["SurveyOpened"]
    window.cleanup()
    assert window._survey_windows == []  # cleanup closes (and forgets) it


def test_open_web_survey_uses_the_browser(qtbot, live_session, monkeypatch):
    window = RecordingWindow(live_session)
    qtbot.addWidget(window)
    opened = []
    monkeypatch.setattr(
        recording.webbrowser, "open", lambda url, **k: opened.append(url)
    )
    window.open_survey_url("https://example.com/form", "Post survey")
    assert opened == ["https://example.com/form"]
    assert window._survey_windows == []  # no in-app window for a web URL
    window.cleanup()


def test_open_unknown_in_app_survey_shows_error_not_a_window(
    qtbot, live_session, silence_dialogs
):
    window = RecordingWindow(live_session)
    qtbot.addWidget(window)
    window.open_survey_url("smacc://survey/not-a-real-key")
    assert window._survey_windows == []
    window.cleanup()


def test_survey_state_round_trips_web_urls_only(qtbot, design_session):
    window = RecordingWindow(design_session)
    qtbot.addWidget(window)
    options = {"Post survey": "https://example.com/post"}
    window.apply_state(
        {"survey_options": options, "survey_url": options["Post survey"]}
    )
    state = window.gather_state()
    assert state["survey_options"] == options  # in-app smacc:// entries excluded
    assert state["survey_url"] == "https://example.com/post"
    window.cleanup()


def test_typed_url_wins_over_blank_preset(qtbot, design_session):
    window = RecordingWindow(design_session)
    qtbot.addWidget(window)
    window.surveyComboBox.setEditText("  example.com/typed  ")
    assert window.current_survey_url() == "example.com/typed"
    window.cleanup()
