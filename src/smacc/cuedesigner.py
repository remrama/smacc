"""The Cue designer: build a simple tone cue and export it as a WAV (#77, #137).

Reached from the launcher's **Design cues** button — a standalone tool (like
Analyze), not a session panel, since authoring a cue is a design-time task with no
markers, devices, or run folder. You lay out a short sequence of **tone** and
**silence** segments (the simple beeps/chimes a cueing study actually uses, 1-30 s),
optionally repeat the pattern into a pip train, watch the live waveform, preview it
on the default output, and export a PCM-16 WAV. Exported into a study's ``cues``
folder, the file is immediately pickable from the Audio cue board.

The DSP lives in :mod:`smacc.synth`; this window is just the editor around it.
Preview reuses :class:`smacc.audio.CueMixer` so playback matches the cue board's
fade/finish behavior, but with no volume cap or routing — the designer runs
independently of any session (see #77). The WAV is the lab-facing artifact the cue
board plays; the editable design itself saves and reopens as a small JSON file
(:class:`smacc.synth.CueDesign`, #137), so a cue can be nudged tomorrow instead of
rebuilt from scratch.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import partial
from pathlib import Path

import numpy as np
import sounddevice as sd
from PyQt6 import QtCore, QtGui, QtWidgets, sip

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
# How long the waveform/duration refresh waits after the last edit before
# re-rendering the cue (spinbox scrubbing stays smooth; a render is a few ms).
RENDER_DEBOUNCE_MS = 150

DESIGN_FILE_FILTER = "Cue design (*.json)"

_TONE = "Tone"
_SILENCE = "Silence"


def make_presets() -> list[tuple[str, synth.CueDesign]]:
    """The starting-point designs offered by the preset picker.

    Fresh objects each call, so an applied preset can never alias the editor's
    state. The two shapes cover most cueing studies: a single decaying chime, and
    the classic pip train (one short tone repeated with gaps).
    """
    return [
        (
            "Single chime",
            synth.CueDesign(
                segments=[
                    synth.ToneSegment(freq=800, duration=1.0, level=0.5, decay=True)
                ],
                name="chime",
            ),
        ),
        (
            "Pip train",
            synth.CueDesign(
                segments=[synth.ToneSegment(freq=500, duration=0.1, level=0.5)],
                name="pips",
                repeat_count=3,
                repeat_gap=0.2,
            ),
        ),
    ]


class WaveformView(QtWidgets.QLabel):
    """Min/max-envelope view of the rendered cue, one column per pixel.

    Pure display: the window hands it the latest rendered buffer (debounced) and
    it draws with palette colors so it follows the app theme. The envelope — not
    the raw wave — is what cue design needs at a glance: levels, decays, gaps,
    repeats, and fades.

    The drawing happens off-screen into a pixmap shown by this QLabel (the same
    pattern as the Visual cue swatch) rather than in a ``paintEvent`` override —
    a queued paint can be delivered while the widget is being torn down, and a
    Python paint handler at that moment aborts the process (seen intermittently
    in offscreen CI runs). A pixmap never paints on a live widget, so there is no
    such window.
    """

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(90)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        self._samples: np.ndarray = np.zeros(0, dtype=np.float32)

    def set_samples(self, samples: np.ndarray) -> None:
        """Show ``samples`` (mono float32 in ``[-1, 1]``); empty clears the wave."""
        self._samples = samples
        self._redraw()

    def resizeEvent(self, event: QtGui.QResizeEvent | None) -> None:
        super().resizeEvent(event)
        if not sip.isdeleted(self):  # resizes can also land mid-teardown
            self._redraw()

    def _redraw(self) -> None:
        """Render the envelope into a fresh pixmap sized to the current widget."""
        width = max(1, self.width())
        height = max(1, self.height())
        pixmap = QtGui.QPixmap(width, height)
        palette = self.palette()
        pixmap.fill(palette.color(QtGui.QPalette.ColorRole.Base))
        painter = QtGui.QPainter(pixmap)
        mid_y = height / 2
        painter.setPen(palette.color(QtGui.QPalette.ColorRole.Mid))
        painter.drawLine(QtCore.QLineF(0, mid_y, width, mid_y))
        n = self._samples.shape[0]
        if n:
            # Column boundaries into the sample buffer; each column draws the
            # min..max span of its slice (a slice may be empty when n < width).
            edges = np.linspace(0, n, num=width + 1).astype(np.int64)
            painter.setPen(palette.color(QtGui.QPalette.ColorRole.Highlight))
            half = mid_y - 2
            for x in range(width):
                lo, hi = int(edges[x]), int(edges[x + 1])
                if hi <= lo:
                    hi = min(lo + 1, n)
                chunk = self._samples[lo:hi]
                if chunk.size == 0:
                    continue
                top = mid_y - float(chunk.max()) * half
                bottom = mid_y - float(chunk.min()) * half
                painter.drawLine(QtCore.QLineF(x, top, x, bottom))
        painter.end()
        self.setPixmap(pixmap)


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
        # Default directory for the file dialogs (a study's cues folder when known).
        self._cues_dir = Path(cues_dir) if cues_dir is not None else None
        # The active preview (mixer + its output stream), or None when stopped. A
        # GUI-thread timer polls the mixer so a finished preview resets the UI.
        self._preview: tuple[audio.CueMixer, sd.OutputStream] | None = None
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(30)  # ~33 Hz: finish detection, not playback
        self._timer.timeout.connect(self._poll_preview)
        # Debounce for the waveform re-render; the duration label updates
        # immediately (it's arithmetic), only the render is deferred.
        self._renderTimer = QtCore.QTimer(self)
        self._renderTimer.setSingleShot(True)
        self._renderTimer.setInterval(RENDER_DEBOUNCE_MS)
        self._renderTimer.timeout.connect(self._refresh_waveform)
        self._presets = make_presets()
        self.rows: list[SegmentRow] = []
        self.setWindowTitle("SMACC — Cue designer")
        if LOGO_PATH.is_file():
            self.setWindowIcon(QtGui.QIcon(str(LOGO_PATH)))
        self._build()
        self._add_row()  # start with the one required segment (a tone)
        self._refresh_waveform()  # draw the initial design without the debounce lag
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
            "export a WAV into your study's cues folder. Save the design to keep "
            "it editable.",
            self,
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        # Preset seeds, name (seeds the export filename), and the master shaping
        # shared by the whole cue: fades, normalize, and the pattern repeat.
        self.presetCombo = QtWidgets.QComboBox(self)
        self.presetCombo.addItem("Choose a preset…")
        for label, _design in self._presets:
            self.presetCombo.addItem(label)
        self.presetCombo.setStatusTip(
            "Replace the design with a common starting point."
        )
        self.presetCombo.activated.connect(self._on_preset_activated)

        self.nameEdit = QtWidgets.QLineEdit("cue", self)
        self.nameEdit.setStatusTip("Name for the exported cue file.")

        self.fadeInSpin = self._seconds_spin("Whole-cue fade-in (0 = none).")
        self.fadeOutSpin = self._seconds_spin("Whole-cue fade-out (0 = none).")
        self.normalizeCheck = QtWidgets.QCheckBox("Normalize", self)
        self.normalizeCheck.setStatusTip(
            "Scale the cue up to a consistent peak level before fading."
        )

        self.repeatSpin = QtWidgets.QSpinBox(self)
        self.repeatSpin.setRange(1, 50)
        self.repeatSpin.setSuffix(" ×")
        self.repeatSpin.setStatusTip(
            "Repeat the whole segment pattern this many times (a pip train)."
        )
        self.repeatGapSpin = self._seconds_spin("Silence between pattern repeats.")
        self.repeatGapSpin.setEnabled(False)  # meaningless until repeats > 1

        self.fadeInSpin.valueChanged.connect(self._schedule_refresh)
        self.fadeOutSpin.valueChanged.connect(self._schedule_refresh)
        self.normalizeCheck.toggled.connect(self._schedule_refresh)
        self.repeatSpin.valueChanged.connect(self._on_repeat_changed)
        self.repeatGapSpin.valueChanged.connect(self._schedule_refresh)

        header = QtWidgets.QFormLayout()
        header.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        header.addRow("Preset:", self.presetCombo)
        header.addRow("Name:", self.nameEdit)
        header.addRow("Fade in:", self.fadeInSpin)
        header.addRow("Fade out:", self.fadeOutSpin)
        header.addRow("", self.normalizeCheck)
        header.addRow("Repeat:", self.repeatSpin)
        header.addRow("Repeat gap:", self.repeatGapSpin)
        layout.addLayout(header)

        # Segment table: a persistent header row, then one rebuildable row per
        # segment, then the add row. Header labels and the add button are built once
        # and reused, so a rebuild only reparents widgets (never deletes them). The
        # table lives in a scroll area so adding rows never resizes the window —
        # the waveform and transport below stay put.
        grid_host = QtWidgets.QWidget(self)
        self._grid = QtWidgets.QGridLayout(grid_host)
        self._grid.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        self._header_labels = [
            self._header_label(text)
            for text in ("Type", "Freq", "Duration", "Level", "Decay", "")
        ]
        self._addButton = QtWidgets.QPushButton("+ Add segment", self)
        self._addButton.setStatusTip(f"Add another segment (up to {MAX_SEGMENTS}).")
        self._addButton.clicked.connect(self.add_segment)
        scroll = QtWidgets.QScrollArea(self)
        scroll.setWidget(grid_host)
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(150)
        layout.addWidget(scroll, 1)

        self.durationLabel = QtWidgets.QLabel(self)
        self.durationLabel.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.durationLabel)

        self.waveformView = WaveformView(self)
        layout.addWidget(self.waveformView)

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

        # Files: the editable design (JSON) and the lab-facing artifact (WAV).
        self.openButton = QtWidgets.QPushButton("Open design…", self)
        self.openButton.setStatusTip("Load a saved cue design (JSON) for editing.")
        self.openButton.clicked.connect(self.open_design)
        self.saveButton = QtWidgets.QPushButton("Save design…", self)
        self.saveButton.setStatusTip("Save this design (JSON) so it stays editable.")
        self.saveButton.clicked.connect(self.save_design)
        self.exportButton = QtWidgets.QPushButton("Export WAV…", self)
        self.exportButton.setStatusTip("Render the cue and save it as a WAV file.")
        self.exportButton.clicked.connect(self.export)
        files = QtWidgets.QHBoxLayout()
        files.addWidget(self.openButton)
        files.addWidget(self.saveButton)
        files.addWidget(self.exportButton)
        layout.addLayout(files)

        self.statusBar()
        self.setCentralWidget(central)
        self.resize(560, 680)

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
        freqSpin.valueChanged.connect(self._schedule_refresh)
        durationSpin.valueChanged.connect(self._schedule_refresh)
        levelSpin.valueChanged.connect(self._schedule_refresh)
        decayCheck.toggled.connect(self._schedule_refresh)
        removeButton.clicked.connect(partial(self.remove_segment, row))
        self._sync_row_enabled(row)
        return row

    def _on_type_changed(self, row: SegmentRow, _text: str) -> None:
        self._sync_row_enabled(row)
        self._schedule_refresh()

    def _sync_row_enabled(self, row: SegmentRow) -> None:
        """Enable the tone-only controls only when the row is a tone."""
        tone = row.is_tone()
        row.freqSpin.setEnabled(tone)
        row.levelSpin.setEnabled(tone)
        row.decayCheck.setEnabled(tone)

    def _add_row(self) -> None:
        self._make_row()
        self._rebuild_grid()
        self._schedule_refresh()

    def add_segment(self) -> None:
        """Append a new segment row, up to the cap."""
        if len(self.rows) >= MAX_SEGMENTS:
            return
        self._add_row()

    def remove_segment(self, row: SegmentRow) -> None:
        """Remove a segment row (never the last one)."""
        if len(self.rows) <= MIN_SEGMENTS or row not in self.rows:
            return
        self.rows.remove(row)
        self._destroy_row_widgets(row)
        self._rebuild_grid()
        self._schedule_refresh()

    def _destroy_row_widgets(self, row: SegmentRow) -> None:
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

    # ----- design state -------------------------------------------------------

    def _design(self) -> synth.CueDesign:
        """The complete design currently described by the editor."""
        return synth.CueDesign(
            segments=[row.to_segment() for row in self.rows],
            name=self.nameEdit.text().strip() or "cue",
            fade_in=self.fadeInSpin.value(),
            fade_out=self.fadeOutSpin.value(),
            normalize=self.normalizeCheck.isChecked(),
            repeat_count=self.repeatSpin.value(),
            repeat_gap=self.repeatGapSpin.value(),
        )

    def _apply_design(self, design: synth.CueDesign) -> None:
        """Load ``design`` into the editor, replacing the rows and master settings."""
        self.nameEdit.setText(design.name)
        self.fadeInSpin.setValue(design.fade_in)
        self.fadeOutSpin.setValue(design.fade_out)
        self.normalizeCheck.setChecked(design.normalize)
        self.repeatSpin.setValue(design.repeat_count)
        self.repeatGapSpin.setValue(design.repeat_gap)
        for row in list(self.rows):
            self._destroy_row_widgets(row)
        self.rows.clear()
        for seg in design.segments:
            row = self._make_row()
            if isinstance(seg, synth.ToneSegment):
                row.typeCombo.setCurrentText(_TONE)
                row.freqSpin.setValue(seg.freq)
                row.levelSpin.setValue(seg.level)
                row.decayCheck.setChecked(seg.decay)
            else:
                row.typeCombo.setCurrentText(_SILENCE)
            row.durationSpin.setValue(seg.duration)
        self._rebuild_grid()
        self._schedule_refresh()

    def _on_repeat_changed(self, count: int) -> None:
        self.repeatGapSpin.setEnabled(count > 1)
        self._schedule_refresh()

    def _on_preset_activated(self, index: int) -> None:
        """Seed the editor from a preset (after confirming the replacement)."""
        self.presetCombo.setCurrentIndex(0)  # stays a picker, not a state display
        if index <= 0:
            return
        label, design = self._presets[index - 1]
        clicked = QtWidgets.QMessageBox.question(
            self,
            "Cue designer",
            f'Replace the current design with the "{label}" preset?',
        )
        if clicked == QtWidgets.QMessageBox.StandardButton.Yes:
            self._apply_design(design)

    def _schedule_refresh(self, *_args) -> None:
        """Update the duration label now; debounce the waveform re-render."""
        total = self._design().total_duration()
        self.durationLabel.setText(f"Total length: {total:.2f} s")
        self._renderTimer.start()

    def _refresh_waveform(self) -> None:
        """Render the current design and hand it to the waveform view."""
        self.waveformView.set_samples(self._design().render(EXPORT_RATE))

    # ----- render / preview / export -----------------------------------------

    def _render(self, rate: int) -> np.ndarray:
        return self._design().render(rate)

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

    # ----- design files / export ----------------------------------------------

    def _start_dir(self) -> Path:
        return self._cues_dir if self._cues_dir is not None else Path.home()

    def save_design(self) -> None:
        """Save the editable design as a JSON file (next to the WAVs by default)."""
        design = self._design()
        default = str(self._start_dir() / f"{design.name}.json")
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save cue design", default, DESIGN_FILE_FILTER
        )
        if not path:
            return
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(
                json.dumps(design.to_dict(), indent=2), encoding="utf-8"
            )
        except Exception as err:  # write failure
            self._warn("Could not save the design.", str(err))
            return
        status_bar = self.statusBar()
        assert status_bar is not None
        status_bar.showMessage(f"Saved {Path(path).name}", 5000)

    def open_design(self) -> None:
        """Load a saved design file into the editor."""
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open cue design", str(self._start_dir()), DESIGN_FILE_FILTER
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            design = synth.CueDesign.from_dict(data)
        except Exception as err:  # unreadable / not a design file
            self._warn("Could not open the design.", str(err))
            return
        if len(design.segments) > MAX_SEGMENTS:
            self._warn(
                "Design has too many segments.",
                f"This designer supports up to {MAX_SEGMENTS} segments.",
            )
            return
        self._apply_design(design)
        status_bar = self.statusBar()
        assert status_bar is not None
        status_bar.showMessage(f"Opened {Path(path).name}", 5000)

    def export(self) -> None:
        """Render at the fixed export rate and save the cue as a WAV file."""
        design = self._design()
        buffer = design.render(EXPORT_RATE)
        if not np.any(buffer):  # empty, all-silence, or zero-level
            self._warn("Nothing to export.", "Add a tone segment first.")
            return
        default = str(self._start_dir() / f"{design.name}.wav")
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
        self._renderTimer.stop()  # no debounced render into a closing window
        self.stop_preview()
        if event is not None:
            event.accept()
        self.closed.emit()
