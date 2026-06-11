"""Tests for the Cue designer window (#77).

Headless Qt (offscreen, via conftest). Preview would open a sounddevice stream, so
the one preview test stubs ``sd.OutputStream``/``sd.query_devices``; everything else
exercises the pure row model and the file export (no hardware).
"""

from __future__ import annotations

import json

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


def test_duration_label_includes_repeats(qtbot):
    win = CueDesignerWindow()
    qtbot.addWidget(win)
    win.rows[0].durationSpin.setValue(1.0)
    win.repeatSpin.setValue(3)
    win.repeatGapSpin.setValue(0.5)
    assert "4.00 s" in win.durationLabel.text()  # 3 × 1.0 + 2 × 0.5


def test_repeat_gap_enabled_only_when_repeating(qtbot):
    win = CueDesignerWindow()
    qtbot.addWidget(win)
    assert not win.repeatGapSpin.isEnabled()
    win.repeatSpin.setValue(2)
    assert win.repeatGapSpin.isEnabled()
    win.repeatSpin.setValue(1)
    assert not win.repeatGapSpin.isEnabled()


def test_waveform_tracks_the_design(qtbot):
    win = CueDesignerWindow()
    qtbot.addWidget(win)
    assert win.waveformView._samples.size > 0  # drawn on open, before any debounce
    win.rows[0].durationSpin.setValue(0.25)
    win._refresh_waveform()  # debounced in the app; forced here
    assert win.waveformView._samples.shape == (EXPORT_RATE // 4,)
    pixmap = win.waveformView.pixmap()
    assert not pixmap.isNull()  # the envelope actually rendered


def test_close_stops_the_pending_waveform_render(qtbot):
    win = CueDesignerWindow()
    qtbot.addWidget(win)
    win.rows[0].durationSpin.setValue(0.2)  # schedules a debounced render
    assert win._renderTimer.isActive()
    win.close()
    assert not win._renderTimer.isActive()


def test_save_and_open_design_round_trip(qtbot, tmp_path, monkeypatch):
    win = CueDesignerWindow(cues_dir=tmp_path)
    qtbot.addWidget(win)
    win.nameEdit.setText("pips")
    win.rows[0].freqSpin.setValue(600)
    win.rows[0].durationSpin.setValue(0.1)
    win.rows[0].levelSpin.setValue(0.4)
    win.rows[0].decayCheck.setChecked(True)
    win.add_segment()
    win.rows[1].typeCombo.setCurrentText("Silence")
    win.rows[1].durationSpin.setValue(0.05)
    win.fadeOutSpin.setValue(0.1)
    win.normalizeCheck.setChecked(True)
    win.repeatSpin.setValue(3)
    win.repeatGapSpin.setValue(0.2)
    saved = win._design()

    out = tmp_path / "pips.json"
    monkeypatch.setattr(
        cuedesigner.QtWidgets.QFileDialog,
        "getSaveFileName",
        lambda *a, **k: (str(out), ""),
    )
    win.save_design()
    assert out.is_file()

    win2 = CueDesignerWindow(cues_dir=tmp_path)
    qtbot.addWidget(win2)
    monkeypatch.setattr(
        cuedesigner.QtWidgets.QFileDialog,
        "getOpenFileName",
        lambda *a, **k: (str(out), ""),
    )
    win2.open_design()
    assert win2._design() == saved


def test_open_design_warns_on_garbage_and_keeps_state(qtbot, tmp_path, monkeypatch):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    win = CueDesignerWindow(cues_dir=tmp_path)
    qtbot.addWidget(win)
    warned: list = []
    monkeypatch.setattr(win, "_warn", lambda *a, **k: warned.append(a))
    monkeypatch.setattr(
        cuedesigner.QtWidgets.QFileDialog,
        "getOpenFileName",
        lambda *a, **k: (str(bad), ""),
    )
    win.open_design()
    assert warned
    assert len(win.rows) == MIN_SEGMENTS  # editor untouched


def test_open_design_refuses_too_many_segments(qtbot, tmp_path, monkeypatch):
    design = synth.CueDesign(
        segments=[synth.ToneSegment(440, 0.1)] * (MAX_SEGMENTS + 1)
    )
    path = tmp_path / "big.json"
    path.write_text(json.dumps(design.to_dict()), encoding="utf-8")
    win = CueDesignerWindow(cues_dir=tmp_path)
    qtbot.addWidget(win)
    warned: list = []
    monkeypatch.setattr(win, "_warn", lambda *a, **k: warned.append(a))
    monkeypatch.setattr(
        cuedesigner.QtWidgets.QFileDialog,
        "getOpenFileName",
        lambda *a, **k: (str(path), ""),
    )
    win.open_design()
    assert warned
    assert len(win.rows) == MIN_SEGMENTS


def test_preset_seeds_the_editor_after_confirm(qtbot, monkeypatch):
    win = CueDesignerWindow()
    qtbot.addWidget(win)
    monkeypatch.setattr(
        cuedesigner.QtWidgets.QMessageBox,
        "question",
        lambda *a, **k: cuedesigner.QtWidgets.QMessageBox.StandardButton.Yes,
    )
    labels = [label for label, _ in win._presets]
    win._on_preset_activated(labels.index("Pip train") + 1)  # +1 for the placeholder
    assert win.nameEdit.text() == "pips"
    assert win.repeatSpin.value() == 3
    assert win.repeatGapSpin.value() == 0.2
    assert win.presetCombo.currentIndex() == 0  # picker resets


def test_preset_declined_leaves_the_editor_alone(qtbot, monkeypatch):
    win = CueDesignerWindow()
    qtbot.addWidget(win)
    before = win._design()
    monkeypatch.setattr(
        cuedesigner.QtWidgets.QMessageBox,
        "question",
        lambda *a, **k: cuedesigner.QtWidgets.QMessageBox.StandardButton.No,
    )
    win._on_preset_activated(1)
    assert win._design() == before


def test_export_renders_the_repeat_train(qtbot, tmp_path, monkeypatch):
    win = CueDesignerWindow(cues_dir=tmp_path)
    qtbot.addWidget(win)
    win.rows[0].durationSpin.setValue(0.5)
    win.repeatSpin.setValue(2)
    win.repeatGapSpin.setValue(0.5)
    out = tmp_path / "train.wav"
    monkeypatch.setattr(
        cuedesigner.QtWidgets.QFileDialog,
        "getSaveFileName",
        lambda *a, **k: (str(out), ""),
    )
    monkeypatch.setattr(
        cuedesigner.QtWidgets.QMessageBox, "information", lambda *a, **k: None
    )
    win.export()
    rate, data = read(out)
    assert rate == EXPORT_RATE
    assert data.shape[0] == int(1.5 * EXPORT_RATE)  # 2 × 0.5 s tones + 0.5 s gap


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
