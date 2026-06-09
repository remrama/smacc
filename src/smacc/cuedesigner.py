"""The Cue designer: build a simple tone cue and export it as a WAV (#77).

Reached from the launcher's **Design cues** button — a standalone tool (like
Analyze), not a session panel, since authoring a cue is a design-time task with no
markers, devices, or run folder. You lay out a short sequence of **tone** and
**silence** segments (the simple beeps/chimes a cueing study actually uses, 1-30 s),
preview it on the default output, and export a PCM-16 WAV. Exported into a study's
``cues`` folder, the file is immediately pickable from the Audio cue board.

The DSP lives in :mod:`smacc.synth`; this window is just the editor around it.
Preview reuses :class:`smacc.audio.CueMixer` so playback matches the cue board's
fade/finish behavior, but with no volume cap or routing — the designer runs
independently of any session (see #77). WAV-only: a design isn't persisted.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from pathlib import Path

import numpy as np
import sounddevice as sd
from PyQt6 import QtCore, QtGui, QtWidgets

from . import audio, synth
from .panels.base import make_section_title
from .paths import LOGO_PATH
from .toolwindow import ToolWindow

# One segment is always required; the cap keeps the grid and a previewed buffer
# manageable (a 30 s cue rarely needs more than a handful of segments).
MIN_SEGMENTS = 1
MAX_SEGMENTS = 64
# WAV files are written at a fixed, device-independent rate; the cue board
# resamples to whatever output device it plays on. Preview uses the device rate.
EXPORT_RATE = synth.DEFAULT_RATE

_TONE = "Tone"
_SILENCE = "Silence"


@dataclass
class SegmentRow:
    """One row of the segment table: its type plus the widgets controlling it.

    Handlers bind to the row *object*, never an index, so adding/removing rows can't
    misroute another row's controls (the same discipline the cue board uses).
    """

    typeCombo: QtWidgets.QComboBox
    freqSpin: QtWidgets.QDoubleSpinBox
    durationSpin: QtWidgets.QDoubleSpinBox
    levelSpin: QtWidgets.QDoubleSpinBox
    decayCheck: QtWidgets.QCheckBox
    removeButton: QtWidgets.QPushButton

    def is_tone(self) -> bool:
        return self.typeCombo.currentText() == _TONE

    def to_segment(self) -> synth.Segment:
        """Build the pure-DSP segment this row describes."""
        duration = self.durationSpin.value()
        if self.is_tone():
            return synth.ToneSegment(
                freq=self.freqSpin.value(),
                duration=duration,
                level=self.levelSpin.value(),
                decay=self.decayCheck.isChecked(),
            )
        return synth.SilenceSegment(duration=duration)


class CueDesignerWindow(ToolWindow):
    """Lay out tone/silence segments, preview them, and export a WAV cue."""

    def __init__(self, cues_dir: str | Path | None = None) -> None:
        super().__init__()
        # Default directory for the export dialog (a study's cues folder when known).
        self._cues_dir = Path(cues_dir) if cues_dir is not None else None
        # The active preview (mixer + its output stream), or None when stopped. A
        # GUI-thread timer polls the mixer so a finished preview resets the UI.
        self._preview: tuple[audio.CueMixer, sd.OutputStream] | None = None
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(30)  # ~33 Hz: finish detection, not playback
        self._timer.timeout.connect(self._poll_preview)
        self.rows: list[SegmentRow] = []
        self.setWindowTitle("SMACC — Cue designer")
        if LOGO_PATH.is_file():
            self.setWindowIcon(QtGui.QIcon(str(LOGO_PATH)))
        self._build()
        self._add_row()  # start with the one required segment (a tone)
        self.show()  # the launcher hides itself and relies on the tool showing itself

    # ----- construction ------------------------------------------------------

    def _build(self) -> None:
        central = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)
        layout.addWidget(make_section_title("Cue designer"))

        intro = QtWidgets.QLabel(
            "Build a short cue from tone and silence segments, preview it, then "
            "export a WAV into your study's cues folder.",
            self,
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        # Name (seeds the export filename) + master shaping shared by the whole cue.
        self.nameEdit = QtWidgets.QLineEdit("cue", self)
        self.nameEdit.setStatusTip("Name for the exported cue file.")

        self.fadeInSpin = self._seconds_spin("Whole-cue fade-in (0 = none).")
        self.fadeOutSpin = self._seconds_spin("Whole-cue fade-out (0 = none).")
        self.normalizeCheck = QtWidgets.QCheckBox("Normalize", self)
        self.normalizeCheck.setStatusTip(
            "Scale the cue up to a consistent peak level before fading."
        )

        header = QtWidgets.QFormLayout()
        header.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        header.addRow("Name:", self.nameEdit)
        header.addRow("Fade in:", self.fadeInSpin)
        header.addRow("Fade out:", self.fadeOutSpin)
        header.addRow("", self.normalizeCheck)
        layout.addLayout(header)

        # Segment table: a persistent header row, then one rebuildable row per
        # segment, then the add row. Header labels and the add button are built once
        # and reused, so a rebuild only reparents widgets (never deletes them).
        self._grid = QtWidgets.QGridLayout()
        self._header_labels = [
            self._header_label(text)
            for text in ("Type", "Freq", "Duration", "Level", "Decay", "")
        ]
        self._addButton = QtWidgets.QPushButton("+ Add segment", self)
        self._addButton.setStatusTip(f"Add another segment (up to {MAX_SEGMENTS}).")
        self._addButton.clicked.connect(self.add_segment)
        layout.addLayout(self._grid)

        self.durationLabel = QtWidgets.QLabel(self)
        self.durationLabel.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.durationLabel)

        # Transport: preview on the default output, stop, and the now-playing line.
        self.previewButton = QtWidgets.QPushButton("Preview", self)
        self.previewButton.setStatusTip("Play the cue on the default output device.")
        self.previewButton.clicked.connect(self.preview)
        self.stopButton = QtWidgets.QPushButton("Stop", self)
        self.stopButton.setStatusTip("Stop the preview.")
        self.stopButton.clicked.connect(self.stop_preview)
        transport = QtWidgets.QHBoxLayout()
        transport.addWidget(self.previewButton)
        transport.addWidget(self.stopButton)
        layout.addLayout(transport)

        self.statusLabel = QtWidgets.QLabel("■ stopped", self)
        self.statusLabel.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.statusLabel)

        self.exportButton = QtWidgets.QPushButton("Export WAV…", self)
        self.exportButton.setStatusTip("Render the cue and save it as a WAV file.")
        self.exportButton.clicked.connect(self.export)
        layout.addWidget(self.exportButton)

        layout.addStretch(1)
        self.statusBar()
        self.setCentralWidget(central)
        self.resize(560, 520)

    def _seconds_spin(self, tip: str) -> QtWidgets.QDoubleSpinBox:
        spin = QtWidgets.QDoubleSpinBox(self)
        spin.setRange(0, 10)
        spin.setSingleStep(0.1)
        spin.setSuffix(" s")
        spin.setStatusTip(tip)
        return spin

    def _header_label(self, text: str) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel(text, self)
        label.setStyleSheet("font-weight: bold;")
        return label

    # ----- segment rows ------------------------------------------------------

    def _make_row(self) -> SegmentRow:
        """Build one fully-wired segment row and append it to ``self.rows``."""
        typeCombo = QtWidgets.QComboBox(self)
        typeCombo.addItems([_TONE, _SILENCE])
        typeCombo.setStatusTip("Tone (a sine beep) or a gap of silence.")

        freqSpin = QtWidgets.QDoubleSpinBox(self)
        freqSpin.setRange(20, 20000)
        freqSpin.setDecimals(0)
        freqSpin.setSingleStep(10)
        freqSpin.setValue(440)
        freqSpin.setSuffix(" Hz")
        freqSpin.setStatusTip("Tone frequency in hertz.")

        durationSpin = QtWidgets.QDoubleSpinBox(self)
        durationSpin.setRange(0.01, 60)
        durationSpin.setDecimals(2)
        durationSpin.setSingleStep(0.1)
        durationSpin.setValue(1.0)
        durationSpin.setSuffix(" s")
        durationSpin.setStatusTip("Segment length in seconds.")

        levelSpin = QtWidgets.QDoubleSpinBox(self)
        levelSpin.setRange(0, 1)
        levelSpin.setDecimals(2)
        levelSpin.setSingleStep(0.05)
        levelSpin.setValue(0.5)
        levelSpin.setStatusTip("Tone level (0-1, software gain at or below unity).")

        decayCheck = QtWidgets.QCheckBox(self)
        decayCheck.setStatusTip("Apply a bell-like exponential decay across the tone.")
        decayCheck.setToolTip("Bell-like decay")

        removeButton = QtWidgets.QPushButton("✕", self)
        removeButton.setMaximumWidth(28)
        removeButton.setStatusTip("Remove this segment.")
        removeButton.setToolTip("Remove this segment")

        row = SegmentRow(
            typeCombo, freqSpin, durationSpin, levelSpin, decayCheck, removeButton
        )
        self.rows.append(row)  # append before wiring so handlers can resolve it
        typeCombo.currentTextChanged.connect(partial(self._on_type_changed, row))
        durationSpin.valueChanged.connect(self._refresh_duration_label)
        removeButton.clicked.connect(partial(self.remove_segment, row))
        self._sync_row_enabled(row)
        return row

    def _on_type_changed(self, row: SegmentRow, _text: str) -> None:
        self._sync_row_enabled(row)

    def _sync_row_enabled(self, row: SegmentRow) -> None:
        """Enable the tone-only controls only when the row is a tone."""
        tone = row.is_tone()
        row.freqSpin.setEnabled(tone)
        row.levelSpin.setEnabled(tone)
        row.decayCheck.setEnabled(tone)

    def _add_row(self) -> None:
        self._make_row()
        self._rebuild_grid()
        self._refresh_duration_label()

    def add_segment(self) -> None:
        """Append a new segment row, up to the cap."""
        if len(self.rows) >= MAX_SEGMENTS:
            return
        self._add_row()
        self.adjustSize()

    def remove_segment(self, row: SegmentRow) -> None:
        """Remove a segment row (never the last one)."""
        if len(self.rows) <= MIN_SEGMENTS or row not in self.rows:
            return
        self.rows.remove(row)
        for widget in (
            row.typeCombo,
            row.freqSpin,
            row.durationSpin,
            row.levelSpin,
            row.decayCheck,
            row.removeButton,
        ):
            widget.hide()
            widget.deleteLater()
        self._rebuild_grid()
        self._refresh_duration_label()
        self.adjustSize()

    def _rebuild_grid(self) -> None:
        """Re-lay the segment table: header row, one row per segment, then add row."""
        while self._grid.count():
            self._grid.takeAt(0)  # drop the layout item only; widgets are reused
        for col, label in enumerate(self._header_labels):
            self._grid.addWidget(label, 0, col)
        for r, row in enumerate(self.rows, start=1):
            self._grid.addWidget(row.typeCombo, r, 0)
            self._grid.addWidget(row.freqSpin, r, 1)
            self._grid.addWidget(row.durationSpin, r, 2)
            self._grid.addWidget(row.levelSpin, r, 3)
            self._grid.addWidget(row.decayCheck, r, 4)
            self._grid.addWidget(row.removeButton, r, 5)
            # The lone required row can't be removed: keep the button (so the column
            # doesn't jump) but disabled.
            row.removeButton.setEnabled(len(self.rows) > MIN_SEGMENTS)
        self._grid.addWidget(self._addButton, len(self.rows) + 1, 0, 1, 2)
        self._addButton.setEnabled(len(self.rows) < MAX_SEGMENTS)

    def _refresh_duration_label(self) -> None:
        total = synth.total_duration([row.to_segment() for row in self.rows])
        self.durationLabel.setText(f"Total length: {total:.2f} s")

    # ----- render / preview / export -----------------------------------------

    def _segments(self) -> list[synth.Segment]:
        return [row.to_segment() for row in self.rows]

    def _render(self, rate: int) -> np.ndarray:
        return synth.render_sequence(
            self._segments(),
            rate=rate,
            fade_in=self.fadeInSpin.value(),
            fade_out=self.fadeOutSpin.value(),
            normalize=self.normalizeCheck.isChecked(),
        )

    def _device_rate(self) -> int:
        """Best output sample rate for the default device (fallback to the export rate)."""
        try:
            return int(sd.query_devices(None, "output")["default_samplerate"])
        except Exception:
            return EXPORT_RATE

    def preview(self) -> None:
        """Render the cue and play it once on the default output device."""
        self.stop_preview()
        rate = self._device_rate()
        buffer = self._render(rate)
        if not np.any(buffer):  # empty, all-silence, or zero-level
            self._warn("Nothing to preview.", "Add a tone segment first.")
            return
        mixer = audio.CueMixer()
        mixer.start(buffer, loop=False)
        try:
            stream = sd.OutputStream(
                channels=1,
                samplerate=rate,
                callback=partial(self._render_callback, mixer),
            )
            stream.start()
        except Exception as err:  # PortAudio / no device
            self._warn("Could not start preview.", str(err))
            return
        self._preview = (mixer, stream)
        self._timer.start()
        self._set_playing(True)

    def _render_callback(self, mixer, outdata, frames, time, status) -> None:
        """sounddevice callback (audio thread): render one preview block (no cap)."""
        outdata[:, 0] = mixer.render(frames)

    def _poll_preview(self) -> None:
        """GUI-thread timer: reset once the previewed cue has finished."""
        if self._preview is not None and self._preview[0].ended:
            self.stop_preview()

    def stop_preview(self) -> None:
        """Stop and tear down the preview stream, if any."""
        self._timer.stop()
        if self._preview is not None:
            _, stream = self._preview
            stream.abort()
            stream.close()
            self._preview = None
        self._set_playing(False)

    def _set_playing(self, playing: bool) -> None:
        if playing:
            self.statusLabel.setText("▶ previewing")
            self.statusLabel.setStyleSheet("color: red; font-weight: bold;")
        else:
            self.statusLabel.setText("■ stopped")
            self.statusLabel.setStyleSheet("")

    def export(self) -> None:
        """Render at the fixed export rate and save the cue as a WAV file."""
        buffer = self._render(EXPORT_RATE)
        if not np.any(buffer):  # empty, all-silence, or zero-level
            self._warn("Nothing to export.", "Add a tone segment first.")
            return
        name = self.nameEdit.text().strip() or "cue"
        start_dir = self._cues_dir if self._cues_dir is not None else Path.home()
        default = str(start_dir / f"{name}.wav")
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export cue (WAV)", default, "WAV audio (*.wav)"
        )
        if not path:
            return
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            synth.export_wav(path, buffer, EXPORT_RATE)
        except Exception as err:  # write / encode failure
            self._warn("Could not export the cue.", str(err))
            return
        status_bar = self.statusBar()
        assert status_bar is not None
        status_bar.showMessage(f"Saved {Path(path).name}", 5000)
        QtWidgets.QMessageBox.information(self, "Cue designer", f"Saved cue to\n{path}")

    # ----- helpers / lifecycle ----------------------------------------------

    def _warn(self, short: str, detail: str | None = None) -> None:
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        box.setWindowTitle("Cue designer")
        box.setText(short)
        if detail is not None:
            box.setInformativeText(detail)
        box.exec()

    def closeEvent(self, event: QtGui.QCloseEvent | None) -> None:
        """Stop any preview and hand control back to the launcher."""
        self.stop_preview()
        if event is not None:
            event.accept()
        self.closed.emit()
