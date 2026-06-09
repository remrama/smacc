"""Audio cue window: a multi-slot cue board (file/volume/loop per slot).

Each slot preloads its own sound with its own volume and loop setting, so a
protocol that uses several sounds (e.g. cue vs. sham) can keep them ready and
fire any one with a click. Playback is one-at-a-time (playing a slot stops
whatever was playing) on a sounddevice output stream routed to a chosen device,
with a shared fade-in/out. Slots can be added and removed on the fly — one is
always required, up to a generous cap — and the first slot autofills with a random
demo cue so a fresh study is immediately playable (#65).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import partial
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf
from PyQt6 import QtCore, QtWidgets

from .. import audio, utils
from ..session import SmaccSession
from ..utils import pick_random_demo_cue
from .base import (
    ModalityWindow,
    current_device_key,
    make_section_title,
    select_saved_device,
)

# One cue is always required; the upper bound is generous (a session typically
# uses 2-5) but capped so the grid and playback stay manageable (#65).
MIN_CUE_SLOTS = 1
MAX_CUE_SLOTS = 20
# Fallback output rate when a device's own rate can't be queried.
CUE_RATE = 44100


@dataclass
class CueSlot:
    """One preloaded cue: its decoded audio plus the row of widgets controlling it.

    Signal handlers bind to the slot *object*, never a row index, so adding or
    removing rows can't misroute another slot's controls. ``audio`` is the decoded
    mono float32 buffer at its native ``rate`` (resampled to the device rate when
    played); ``None`` until a valid file is loaded.
    """

    nameEdit: QtWidgets.QLineEdit
    fileEdit: QtWidgets.QLineEdit
    browseButton: QtWidgets.QPushButton
    volumeSpinBox: QtWidgets.QDoubleSpinBox
    loopCheckBox: QtWidgets.QCheckBox
    playButton: QtWidgets.QPushButton
    stopButton: QtWidgets.QPushButton
    removeButton: QtWidgets.QPushButton
    audio: np.ndarray | None = field(default=None)
    rate: int = field(default=0)


class AudioCueWindow(ModalityWindow):
    """Multi-slot cue board with a shared device + fade and per-slot play/stop."""

    TITLE = "Audio cue"

    def __init__(self, session: SmaccSession, parent: QtWidgets.QWidget | None = None):
        super().__init__(session, parent)
        # Shared fade (attack/release) durations in seconds; 0 == instant.
        self.cue_attack_s = 0.0
        self.cue_release_s = 0.0
        # One output stream at a time, driven by a CueMixer; a timer on the GUI
        # thread polls for the cue finishing (so the stop can be marked + UI reset).
        self._cue_stream: sd.OutputStream | None = None
        self._cue_mixer = audio.CueMixer()
        self._active_slot: CueSlot | None = None
        self._cue_timer = QtCore.QTimer(self)
        self._cue_timer.setInterval(30)  # ~33 Hz: finish detection, not playback
        self._cue_timer.timeout.connect(self._poll_cue)
        # Populated after the central widget exists so _rebuild_grid has its
        # header labels and add button to work with.
        self.slots: list[CueSlot] = []
        self.setCentralWidget(self._build())
        # Start with the one required slot, prefilled with a random demo so a fresh
        # study can play something immediately; a loaded study overrides it.
        self._add_initial_slot()

    # ----- construction ------------------------------------------------------

    def _make_slot(self, name: str) -> CueSlot:
        """Build one fully-wired cue slot and append it to ``self.slots``."""
        nameEdit = QtWidgets.QLineEdit(name, self)
        nameEdit.setMaximumWidth(90)
        fileEdit = QtWidgets.QLineEdit(self)
        fileEdit.setMinimumWidth(180)
        browseButton = QtWidgets.QPushButton("Browse", self)
        volumeSpinBox = QtWidgets.QDoubleSpinBox(self)
        volumeSpinBox.setRange(0, 1)  # software gain at unity-or-below (no clipping)
        volumeSpinBox.setSingleStep(0.01)
        volumeSpinBox.setMaximumWidth(70)
        loopCheckBox = QtWidgets.QCheckBox(self)
        loopCheckBox.setStatusTip("Repeat this cue until stopped.")
        loopCheckBox.setToolTip("Loop until stopped")
        playButton = QtWidgets.QPushButton("Play", self)
        stopButton = QtWidgets.QPushButton("Stop", self)
        removeButton = QtWidgets.QPushButton("✕", self)  # ✕
        removeButton.setMaximumWidth(28)
        removeButton.setStatusTip("Remove this cue.")
        removeButton.setToolTip("Remove this cue")
        slot = CueSlot(
            nameEdit,
            fileEdit,
            browseButton,
            volumeSpinBox,
            loopCheckBox,
            playButton,
            stopButton,
            removeButton,
        )
        self.slots.append(slot)  # append before wiring so handlers can resolve it
        fileEdit.textChanged.connect(partial(self.update_slot_source, slot))
        fileEdit.editingFinished.connect(partial(self.update_slot_source, slot))
        volumeSpinBox.valueChanged.connect(partial(self.update_slot_volume, slot))
        loopCheckBox.toggled.connect(partial(self.update_slot_loop, slot))
        browseButton.clicked.connect(partial(self.open_audio_selector, slot))
        playButton.clicked.connect(partial(self.play_slot, slot))
        stopButton.clicked.connect(partial(self.stop_slot, slot))
        removeButton.clicked.connect(partial(self.remove_slot, slot))
        volumeSpinBox.setValue(0.2)  # fires update_slot_volume
        return slot

    def _add_initial_slot(self) -> None:
        """Create the single required slot and prefill a random demo cue (#65)."""
        slot = self._make_slot("Cue 1")
        demo = pick_random_demo_cue(self.session.cues_dir)
        if demo is not None:
            slot.fileEdit.setText(str(demo))
        self._rebuild_grid()

    def _build(self) -> QtWidgets.QWidget:
        # Shared output device + fade controls.
        available_speakers_dropdown = QtWidgets.QComboBox()
        available_speakers_dropdown.setStatusTip("Select speakers for cues")
        available_speakers_dropdown.setPlaceholderText("No speaker devices were found.")
        available_speakers_dropdown.currentTextChanged.connect(self.set_new_cue_device)
        self.available_speakers_dropdown = available_speakers_dropdown
        self.refresh_available_speakers()

        attackSpinBox = QtWidgets.QDoubleSpinBox(self)
        attackSpinBox.setStatusTip(
            "Fade-in time for the cue, in seconds (0 = instant)."
        )
        attackSpinBox.setRange(0, 60)
        attackSpinBox.setSingleStep(0.1)
        attackSpinBox.setSuffix(" seconds")
        attackSpinBox.valueChanged.connect(self.update_cue_attack)
        attackSpinBox.setValue(0.0)
        self.attackSpinBox = attackSpinBox

        releaseSpinBox = QtWidgets.QDoubleSpinBox(self)
        releaseSpinBox.setStatusTip(
            "Fade-out time when stopping the cue, in seconds (0 = instant)."
        )
        releaseSpinBox.setRange(0, 60)
        releaseSpinBox.setSingleStep(0.1)
        releaseSpinBox.setSuffix(" seconds")
        releaseSpinBox.valueChanged.connect(self.update_cue_release)
        releaseSpinBox.setValue(0.0)
        self.releaseSpinBox = releaseSpinBox

        header = QtWidgets.QFormLayout()
        header.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        header.addRow("Device:", available_speakers_dropdown)
        header.addRow("Fade in:", attackSpinBox)
        header.addRow("Fade out:", releaseSpinBox)

        # "Now playing" indicator on top of the slot table (mixing-board style).
        self.nowPlayingLabel = QtWidgets.QLabel("■ stopped", self)  # ■
        self.nowPlayingLabel.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

        # Cue table: a persistent header row, then one rebuildable row per slot,
        # then an "add" row. The header labels and add button are created once and
        # reused across rebuilds, so a rebuild only reparents widgets (never deletes
        # them) and live slot controls survive untouched.
        self._grid = QtWidgets.QGridLayout()
        self._header_labels = [
            self._make_header_label(title)
            for title in ("Name", "Sound", "", "Vol", "Loop", "", "", "")
        ]
        self._addButton = QtWidgets.QPushButton("+ Add cue", self)
        self._addButton.setStatusTip(f"Add another cue (up to {MAX_CUE_SLOTS}).")
        self._addButton.setToolTip("Add another cue")
        self._addButton.clicked.connect(self.add_slot)
        self._rebuild_grid()

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(make_section_title("Audio cue"))
        layout.addLayout(header)
        layout.addWidget(self.nowPlayingLabel)
        layout.addLayout(self._grid)
        layout.addStretch(1)
        central = QtWidgets.QWidget()
        central.setLayout(layout)
        return central

    def _make_header_label(self, text: str) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel(text, self)
        label.setStyleSheet("font-weight: bold;")
        return label

    def _rebuild_grid(self) -> None:
        """Re-lay the cue table: header row, one row per slot, then the add row.

        Every widget here is persistent (the header labels, the add button, and
        each slot's controls), so clearing only reparents them out of the grid —
        nothing is deleted — and they're re-added in their new positions.
        """
        while self._grid.count():
            self._grid.takeAt(0)  # drop the layout item only; widgets are reused
        for col, label in enumerate(self._header_labels):
            self._grid.addWidget(label, 0, col)
        for row, slot in enumerate(self.slots, start=1):
            self._grid.addWidget(slot.nameEdit, row, 0)
            self._grid.addWidget(slot.fileEdit, row, 1)
            self._grid.addWidget(slot.browseButton, row, 2)
            self._grid.addWidget(slot.volumeSpinBox, row, 3)
            self._grid.addWidget(slot.loopCheckBox, row, 4)
            self._grid.addWidget(slot.playButton, row, 5)
            self._grid.addWidget(slot.stopButton, row, 6)
            self._grid.addWidget(slot.removeButton, row, 7)
            # The lone required slot can't be removed: keep the button in place (so
            # the column doesn't jump) but disabled.
            slot.removeButton.setEnabled(len(self.slots) > MIN_CUE_SLOTS)
        self._grid.addWidget(self._addButton, len(self.slots) + 1, 0, 1, 2)
        self._addButton.setEnabled(len(self.slots) < MAX_CUE_SLOTS)
        self._grid.setColumnStretch(1, 1)

    # ----- add / remove slots ------------------------------------------------

    def add_slot(self) -> None:
        """Append a new (empty) cue slot, up to the cap (#65)."""
        if len(self.slots) >= MAX_CUE_SLOTS:
            return
        slot = self._make_slot(f"Cue {len(self.slots) + 1}")
        self._rebuild_grid()
        self.adjustSize()
        self.session.log_interaction(f"Added cue '{slot.nameEdit.text()}'")

    def remove_slot(self, slot: CueSlot) -> None:
        """Remove a cue slot (never the last one), stopping it first (#65)."""
        if len(self.slots) <= MIN_CUE_SLOTS or slot not in self.slots:
            return
        name = slot.nameEdit.text()
        self.slots.remove(slot)
        self._destroy_slot_widgets(slot)
        self._rebuild_grid()
        self.adjustSize()
        self.session.log_interaction(f"Removed cue '{name}'")

    def _destroy_slot_widgets(self, slot: CueSlot) -> None:
        """Tear down a removed slot: silence it if playing, then free its widgets."""
        if self._active_slot is slot:
            self._finish_active(mark=False)  # silence without a spurious marker
        for widget in (
            slot.nameEdit,
            slot.fileEdit,
            slot.browseButton,
            slot.volumeSpinBox,
            slot.loopCheckBox,
            slot.playButton,
            slot.stopButton,
            slot.removeButton,
        ):
            widget.hide()  # leave no orphan visible before deferred deletion
            widget.deleteLater()

    def _resize_slots(self, count: int) -> None:
        """Grow/shrink the slot list to ``count`` (clamped to ``1..MAX``) (#65)."""
        count = max(MIN_CUE_SLOTS, min(count, MAX_CUE_SLOTS))
        while len(self.slots) < count:
            self._make_slot(f"Cue {len(self.slots) + 1}")
        while len(self.slots) > count:
            self._destroy_slot_widgets(self.slots.pop())
        self._rebuild_grid()

    # ----- shared device + fade ---------------------------------------------

    def refresh_available_speakers(self):
        """Populate the cue device menu with available WASAPI output devices."""
        self.available_speakers_dropdown.clear()
        host_api_name = "Windows WASAPI"
        host_api_names = [api["name"] for api in sd.query_hostapis()]
        hostapi = (
            host_api_names.index(host_api_name)
            if host_api_name in host_api_names
            else None
        )
        count = 0
        for device in sd.query_devices():
            if device["max_output_channels"] <= 0:
                continue
            if hostapi is not None and device["hostapi"] != hostapi:
                continue
            suffix = f", {host_api_name}" if hostapi is not None else ""
            self.available_speakers_dropdown.addItem(f"{device['name']}{suffix}")
            count += 1
        if count:
            self.available_speakers_dropdown.setCurrentIndex(0)
        else:
            self.session.show_error_popup("No audio devices found.", parent=self)

    def refresh_devices(self) -> None:
        """Re-enumerate speakers, keeping the current selection if still present."""
        combo = self.available_speakers_dropdown
        previous = current_device_key(combo)
        self.refresh_available_speakers()
        select_saved_device(combo, previous)

    def is_streaming(self) -> bool:
        """True while a cue is playing (an open output stream)."""
        return self._cue_stream is not None

    def set_new_cue_device(self, text: str) -> None:
        """Apply a newly selected output device; a playing cue is stopped first.

        A cue is a one-shot (unlike continuous noise), so rather than reopen the
        stream on the new device mid-cue, an active cue is stopped (and marked).
        """
        self.session.log_interaction(f"Cue device set to {text}")
        if self._active_slot is not None:
            self._finish_active()

    def _device_samplerate(self, device: str | None) -> int:
        """Best output sample rate for ``device`` (WASAPI opens only at its own)."""
        try:
            return int(sd.query_devices(device, "output")["default_samplerate"])
        except Exception:
            return CUE_RATE

    def update_cue_attack(self, value: float) -> None:
        """Set the shared cue fade-in (attack) time in seconds."""
        self.cue_attack_s = value
        self.session.log_interaction(f"Cue fade-in set to {value:.1f}s")

    def update_cue_release(self, value: float) -> None:
        """Set the shared cue fade-out (release) time in seconds."""
        self.cue_release_s = value
        self.session.log_interaction(f"Cue fade-out set to {value:.1f}s")

    # ----- per-slot controls -------------------------------------------------

    def open_audio_selector(self, slot: CueSlot) -> None:
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select a File",
            str(self.session.cues_dir),
            "Audio (*.wav *.mp3 *.flac *.ogg *.oga *.aif *.aiff);;All files (*)",
        )
        if filename:
            slot.fileEdit.setText(str(Path(filename)))

    def update_slot_source(self, slot: CueSlot) -> None:
        """Decode a slot's file into its mono float32 buffer (any format soundfile reads).

        Fired on every keystroke, so missing/partial paths just clear the buffer
        silently; only a genuine decode failure raises a popup.
        """
        filepath = slot.fileEdit.text().strip()
        if not filepath or not Path(filepath).is_file():
            slot.audio = None
            slot.rate = 0
            return
        try:
            data, file_rate = sf.read(filepath, dtype="float32")
        except Exception as err:
            slot.audio = None
            slot.rate = 0
            self.session.show_error_popup(
                "Could not load audio file", str(err), parent=self
            )
            return
        if data.ndim > 1:  # down-mix to mono
            data = data.mean(axis=1)
        slot.audio = np.ascontiguousarray(data, dtype=np.float32)
        slot.rate = int(file_rate)

    def update_slot_volume(self, slot: CueSlot, value: float | None = None) -> None:
        """Set a slot's volume (0-1) from its spinbox (live if it's playing)."""
        vol = slot.volumeSpinBox.value()
        if self._active_slot is slot:
            self._cue_mixer.volume = vol
        self.session.log_interaction(
            f"Cue '{slot.nameEdit.text()}' volume set to {vol:.2f}"
        )

    def update_slot_loop(self, slot: CueSlot, enabled: bool | None = None) -> None:
        """Set a slot's loop flag from its checkbox (live if it's playing)."""
        looping = slot.loopCheckBox.isChecked()
        if self._active_slot is slot:
            self._cue_mixer.loop = looping
        self.session.log_interaction(
            f"Cue '{slot.nameEdit.text()}' loop {'on' if looping else 'off'}"
        )

    def play_slot(self, slot: CueSlot) -> None:
        """Play one slot (stopping any other playing slot first) with fade-in."""
        if slot.audio is None or slot.audio.shape[0] == 0:
            return  # nothing loaded in this slot
        # One-at-a-time: cut whatever is playing. Mark a CueStopped only when a
        # *different* cue is replaced (re-playing the same slot is just a restart).
        if self._active_slot is not None:
            self._finish_active(mark=self._active_slot is not slot)
        device = self.available_speakers_dropdown.currentText() or None
        rate = self._device_samplerate(device)
        buffer = utils.resample_to(slot.audio, slot.rate, rate)
        self._cue_mixer.start(
            buffer,
            volume=slot.volumeSpinBox.value(),
            loop=slot.loopCheckBox.isChecked(),
            attack_samples=int(self.cue_attack_s * rate),
        )
        try:
            stream = sd.OutputStream(
                channels=1,
                samplerate=rate,
                device=device,
                callback=self._cue_callback,
            )
            stream.start()
        except Exception as err:
            self._cue_mixer.stop(release_samples=0)
            self.session.show_error_popup(
                "Could not start cue output", str(err), parent=self
            )
            return
        self._cue_stream = stream
        self._active_slot = slot
        self._cue_timer.start()
        self._set_now_playing(slot)
        self.session.emit_event("CueStarted", detail=slot.nameEdit.text())

    def stop_slot(self, slot: CueSlot) -> None:
        """Stop a slot (with fade-out) if it is the one currently playing."""
        if self._active_slot is not slot:
            return
        rate = int(self._cue_stream.samplerate) if self._cue_stream else 0
        self._cue_mixer.stop(release_samples=int(self.cue_release_s * rate))
        if self._cue_mixer.ended:  # instant stop (no release fade)
            self._finish_active()
        # Otherwise the release fade runs and _poll_cue finalizes it when done.

    def _cue_callback(self, outdata, frames, time, status) -> None:
        """sounddevice callback (audio thread): render the active cue block."""
        if status:
            self.session.logger.warning(f"Audio output status: {status}")
        outdata[:, 0] = self._cue_mixer.render(frames)

    def _poll_cue(self) -> None:
        """GUI-thread timer: finalize once the active cue has finished/faded out."""
        if self._active_slot is not None and self._cue_mixer.ended:
            self._finish_active()

    def _finish_active(self, mark: bool = True) -> None:
        """Tear down the cue stream and reset the UI; mark CueStopped when ``mark``."""
        slot = self._active_slot
        self._cue_timer.stop()
        if self._cue_stream is not None:
            self._cue_stream.abort()
            self._cue_stream.close()
            self._cue_stream = None
        self._active_slot = None
        self._set_now_playing_stopped()
        if mark and slot is not None:
            self.session.emit_event("CueStopped", detail=slot.nameEdit.text())

    def _set_now_playing(self, slot: CueSlot) -> None:
        looping = slot.loopCheckBox.isChecked()
        name = slot.nameEdit.text()
        self.nowPlayingLabel.setText(
            f"\U0001f501 {name} (looping)" if looping else f"▶ {name}"
        )
        self.nowPlayingLabel.setStyleSheet("color: red; font-weight: bold;")

    def _set_now_playing_stopped(self) -> None:
        self.nowPlayingLabel.setText("■ stopped")  # ■
        self.nowPlayingLabel.setStyleSheet("")

    # ----- settings state ----------------------------------------------------

    def gather_state(self) -> dict:
        return {
            "cue_device": current_device_key(self.available_speakers_dropdown),
            "cues": [
                {
                    "name": slot.nameEdit.text(),
                    "file": slot.fileEdit.text(),
                    "volume": slot.volumeSpinBox.value(),
                    "loop": slot.loopCheckBox.isChecked(),
                }
                for slot in self.slots
            ],
            "cue_attack": self.attackSpinBox.value(),
            "cue_release": self.releaseSpinBox.value(),
        }

    def apply_state(self, state: dict) -> None:
        saved = state.get("cue_device")
        if saved and not select_saved_device(self.available_speakers_dropdown, saved):
            self.session.note_missing_device("Cue output", saved)
        cues = state.get("cues")
        if isinstance(cues, list) and cues:
            self._resize_slots(len(cues))
            for slot, cue in zip(self.slots, cues, strict=False):
                self._apply_cue(slot, cue)
        elif state.get("cue_file") is not None or state.get("cue_volume") is not None:
            # Back-compat: a v1 single cue maps into the first slot.
            self._resize_slots(1)
            self._apply_cue(
                self.slots[0],
                {
                    "file": state.get("cue_file", ""),
                    "volume": state.get("cue_volume"),
                    "loop": state.get("cue_loop"),
                },
            )
        if (v := state.get("cue_attack")) is not None:
            self.attackSpinBox.setValue(float(v))
        if (v := state.get("cue_release")) is not None:
            self.releaseSpinBox.setValue(float(v))

    @staticmethod
    def _apply_cue(slot: CueSlot, cue: dict) -> None:
        if name := cue.get("name"):
            slot.nameEdit.setText(str(name))
        if (f := cue.get("file")) is not None:
            slot.fileEdit.setText(str(f))  # textChanged -> update_slot_source decodes
        if (v := cue.get("volume")) is not None:
            slot.volumeSpinBox.setValue(float(v))
        slot.loopCheckBox.setChecked(bool(cue.get("loop", False)))

    def cleanup(self) -> None:
        self._cue_timer.stop()
        if self._cue_stream is not None:
            self._cue_stream.abort()
            self._cue_stream.close()
            self._cue_stream = None
