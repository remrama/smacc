"""Behavior of the Biocals window around its run engine (headless, no audio).

Voice playback needs an output device, so these tests run with the voice
checkbox off (or with the voice files absent, exercising the skip-to-window
fallback); the engine's own timing/marker matrix lives in test_biocals.py.
Markers are asserted via the session logger — emit_event always writes there.
"""

from __future__ import annotations

import logging

from smacc import biocals
from smacc.panels.biocals import BiocalsWindow


def _capture(session) -> list[logging.LogRecord]:
    """Record the session logger (propagate=False keeps caplog blind to it)."""
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    session.logger.addHandler(_Capture())
    return records


def _messages(records: list[logging.LogRecord]) -> list[str]:
    return [r.getMessage() for r in records]


def _make_panel(qtbot, session) -> BiocalsWindow:
    panel = BiocalsWindow(session)
    qtbot.addWidget(panel)
    return panel


class FakeClock:
    def __init__(self, t: float = 100.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def test_default_stack_builds(qtbot, headless_session):
    panel = _make_panel(qtbot, headless_session)
    assert [row.key for row in panel.rows] == [r.key for r in biocals.default_rows()]
    assert panel.rows[0].seqCheckBox.isChecked()  # standard: in the sequence
    lrlr = next(row for row in panel.rows if row.key == "lrlr_open")
    assert not lrlr.seqCheckBox.isChecked()  # lucid-dreaming: opt-in
    assert all(row.voiceCheckBox.isChecked() for row in panel.rows)
    assert panel.countdownLabel.text() == "00:00:00"
    assert panel.sequenceButton.isEnabled()


def test_press_runs_and_press_again_cancels(qtbot, headless_session):
    panel = _make_panel(qtbot, headless_session)
    records = _capture(headless_session)
    row = panel.rows[0]  # Eyes Open
    row.voiceCheckBox.setChecked(False)
    panel._on_row_button(row)
    assert row.button.isChecked()
    assert panel._run.phase == biocals.WINDOW
    assert "Biocal: Eyes Open - portcode 110" in _messages(records)
    # The stack is frozen while something runs.
    assert not panel._addButton.isEnabled()
    assert not panel.rows[0].removeButton.isEnabled()
    panel._on_row_button(row)  # cancel
    assert not row.button.isChecked()
    assert not panel._run.active
    assert "Biocal cancelled: Eyes Open - portcode 107" in _messages(records)
    assert panel._addButton.isEnabled()


def test_missing_voice_skips_straight_to_the_window(
    qtbot, headless_session, monkeypatch, tmp_path
):
    # Voice enabled but no recording anywhere (override nor bundle): warn, then
    # open the task window immediately — a lost WAV must never block a calibration.
    monkeypatch.setattr(
        "smacc.panels.biocals.resolve_biocal_voice",
        lambda filename: tmp_path / filename,  # an empty dir == no recording
    )
    panel = _make_panel(qtbot, headless_session)
    records = _capture(headless_session)
    row = panel.rows[0]
    assert row.voiceCheckBox.isChecked()
    panel._on_row_button(row)
    assert panel._run.phase == biocals.WINDOW
    messages = _messages(records)
    assert "Biocal announced: Eyes Open" in messages
    assert any(m.startswith("Biocal voice unavailable") for m in messages)
    assert "Biocal: Eyes Open - portcode 110" in messages


def test_sequence_runs_skips_and_completes(qtbot, headless_session):
    panel = _make_panel(qtbot, headless_session)
    clock = FakeClock()
    panel._run = biocals.BiocalRun(clock)  # deterministic time
    records = _capture(headless_session)
    for row in panel.rows:
        row.seqCheckBox.setChecked(False)
        row.voiceCheckBox.setChecked(False)
    first, second = panel.rows[0], panel.rows[1]
    first.seqCheckBox.setChecked(True)
    second.seqCheckBox.setChecked(True)
    panel._on_sequence_button()
    assert panel.sequenceButton.isChecked()
    assert panel.sequenceButton.text() == "Stop sequence"
    assert first.button.isChecked() and not second.button.isChecked()
    # Pressing the *active* row's button mid-sequence skips just that item.
    panel._on_row_button(first)
    assert not first.button.isChecked() and second.button.isChecked()
    assert "Biocal cancelled: Eyes Open - portcode 107" in _messages(records)
    # Other rows are inert while the sequence runs.
    panel._on_row_button(panel.rows[5])
    assert panel._run.item is not None and panel._run.item.token is second
    assert not panel.rows[5].button.isChecked()
    # Let the second item's window run out; the sequence closes itself.
    clock.t += second.durationSpin.value() + 1
    panel._poll()
    assert not panel._run.active
    assert not panel.sequenceButton.isChecked()
    assert panel.sequenceButton.text() == "Play sequence"
    messages = _messages(records)
    assert "Biocal completed: Eyes Closed - portcode 108" in messages
    assert "Biocal sequence stopped: completed - portcode 106" in messages


def test_sequence_button_aborts_the_rest(qtbot, headless_session):
    panel = _make_panel(qtbot, headless_session)
    records = _capture(headless_session)
    for row in panel.rows:
        row.voiceCheckBox.setChecked(False)
    panel._on_sequence_button()  # standard rows are checked by default
    assert panel._run.in_sequence
    panel._on_sequence_button()  # abort
    assert not panel._run.active
    messages = _messages(records)
    assert "Biocal sequence stopped: cancelled - portcode 106" in messages
    assert all(not row.button.isChecked() for row in panel.rows)


def test_stack_editing_reorders_adds_and_removes(qtbot, headless_session):
    panel = _make_panel(qtbot, headless_session)
    second = panel.rows[1]
    panel._move_row(second, -1)
    assert panel.rows[0] is second
    panel._remove_row(second)
    assert second not in panel.rows and len(panel.rows) == 17
    panel._addCombo.setCurrentIndex(0)  # Eyes Open
    panel._add_clicked()
    assert panel.rows[-1].key == "eyes_open"
    assert len(panel.rows) == 18


def test_cleanup_cancels_an_active_run_honestly(qtbot, headless_session):
    panel = _make_panel(qtbot, headless_session)
    records = _capture(headless_session)
    row = panel.rows[0]
    row.voiceCheckBox.setChecked(False)
    panel._on_row_button(row)
    panel.cleanup()
    assert not panel._run.active
    assert "Biocal cancelled: Eyes Open - portcode 107" in _messages(records)
