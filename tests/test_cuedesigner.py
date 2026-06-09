"""Tests for the Cue designer window (#77).

Headless Qt (offscreen, via conftest). Preview would open a sounddevice stream, so
the one preview test stubs ``sd.OutputStream``/``sd.query_devices``; everything else
exercises the pure row model and the file export (no hardware).
"""

from __future__ import annotations

from scipy.io.wavfile import read

from smacc import cuedesigner, synth
from smacc.cuedesigner import (
    EXPORT_RATE,
    MAX_SEGMENTS,
    MIN_SEGMENTS,
    CueDesignerWindow,
)


def test_starts_with_one_required_tone_row(qtbot):
    win = CueDesignerWindow()
    qtbot.addWidget(win)
    assert len(win.rows) == MIN_SEGMENTS
    assert win.rows[0].is_tone()
    assert not win.rows[0].removeButton.isEnabled()  # the lone row can't be removed


def test_add_and_remove_segments(qtbot):
    win = CueDesignerWindow()
    qtbot.addWidget(win)
    win.add_segment()
    assert len(win.rows) == 2
    assert win.rows[0].removeButton.isEnabled()  # now removable
    win.remove_segment(win.rows[1])
    assert len(win.rows) == 1
    assert not win.rows[0].removeButton.isEnabled()


def test_add_segment_respects_cap(qtbot):
    win = CueDesignerWindow()
    qtbot.addWidget(win)
    for _ in range(MAX_SEGMENTS + 5):
        win.add_segment()
    assert len(win.rows) == MAX_SEGMENTS


def test_silence_row_disables_tone_controls(qtbot):
    win = CueDesignerWindow()
    qtbot.addWidget(win)
    row = win.rows[0]
    row.typeCombo.setCurrentText("Silence")
    assert not row.freqSpin.isEnabled()
    assert not row.levelSpin.isEnabled()
    assert not row.decayCheck.isEnabled()
    assert isinstance(row.to_segment(), synth.SilenceSegment)


def test_tone_row_builds_tone_segment(qtbot):
    win = CueDesignerWindow()
    qtbot.addWidget(win)
    row = win.rows[0]
    row.freqSpin.setValue(523)
    row.durationSpin.setValue(0.5)
    row.levelSpin.setValue(0.3)
    seg = row.to_segment()
    assert isinstance(seg, synth.ToneSegment)
    assert seg.freq == 523
    assert seg.duration == 0.5
    assert seg.level == 0.3


def test_duration_label_tracks_segments(qtbot):
    win = CueDesignerWindow()
    qtbot.addWidget(win)
    win.rows[0].durationSpin.setValue(2.0)
    win.add_segment()
    win.rows[1].durationSpin.setValue(0.5)
    assert "2.50 s" in win.durationLabel.text()


def test_export_writes_a_wav(qtbot, tmp_path, monkeypatch):
    win = CueDesignerWindow(cues_dir=tmp_path)
    qtbot.addWidget(win)
    out = tmp_path / "mycue.wav"
    monkeypatch.setattr(
        cuedesigner.QtWidgets.QFileDialog,
        "getSaveFileName",
        lambda *a, **k: (str(out), ""),
    )
    monkeypatch.setattr(
        cuedesigner.QtWidgets.QMessageBox, "information", lambda *a, **k: None
    )
    win.export()
    assert out.is_file()
    rate, data = read(out)
    assert rate == EXPORT_RATE
    assert data.shape[0] > 0


def test_export_warns_and_skips_when_silent(qtbot, tmp_path, monkeypatch):
    win = CueDesignerWindow(cues_dir=tmp_path)
    qtbot.addWidget(win)
    win.rows[0].typeCombo.setCurrentText("Silence")  # no tones -> silent render
    warned: list = []
    saved: list = []
    monkeypatch.setattr(win, "_warn", lambda *a, **k: warned.append(a))

    def fake_save(*a, **k):
        saved.append(True)
        return ("", "")

    monkeypatch.setattr(cuedesigner.QtWidgets.QFileDialog, "getSaveFileName", fake_save)
    win.export()
    assert warned  # warned the user
    assert not saved  # returned before opening the save dialog


def test_preview_opens_then_stop_closes_stream(qtbot, monkeypatch):
    win = CueDesignerWindow()
    qtbot.addWidget(win)

    class FakeStream:
        instances: list = []

        def __init__(self, *a, **k):
            self.aborted = False
            self.closed = False
            FakeStream.instances.append(self)

        def start(self):
            pass

        def abort(self):
            self.aborted = True

        def close(self):
            self.closed = True

    monkeypatch.setattr(cuedesigner.sd, "OutputStream", FakeStream)
    monkeypatch.setattr(
        cuedesigner.sd, "query_devices", lambda *a, **k: {"default_samplerate": 44100}
    )
    win.preview()
    assert win._preview is not None
    win.stop_preview()
    assert win._preview is None
    assert FakeStream.instances[0].aborted
    assert FakeStream.instances[0].closed
