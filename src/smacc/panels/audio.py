"""Audio cue window: a multi-slot cue board (file/volume/loop per slot).

Each slot preloads its own sound with its own volume and loop setting, so a
protocol that uses several sounds (e.g. cue vs. sham) can keep them ready and
fire any one with a click. Playback is one-at-a-time (playing a slot stops
whatever was playing); fade-in/out is shared at the panel level.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path

from PyQt5 import QtCore, QtMultimedia, QtWidgets

from ..session import SmaccSession
from ..utils import ensure_wav
from .base import ModalityWindow, make_section_title

N_CUE_SLOTS = 4


@dataclass
class CueSlot:
    """One preloaded cue: its player plus the row of widgets that control it."""

    index: int
    player: QtMultimedia.QSoundEffect
    nameEdit: QtWidgets.QLineEdit
    fileEdit: QtWidgets.QLineEdit
    browseButton: QtWidgets.QPushButton
    volumeSpinBox: QtWidgets.QDoubleSpinBox
    loopCheckBox: QtWidgets.QCheckBox
    playButton: QtWidgets.QPushButton
    stopButton: QtWidgets.QPushButton
    was_playing: bool = field(default=False)


class AudioCueWindow(ModalityWindow):
    """Multi-slot cue board with a shared device + fade and per-slot play/stop."""

    TITLE = "Audio cue"

    def __init__(self, session: SmaccSession, parent: QtWidgets.QWidget | None = None):
        super().__init__(session, parent)
        # Scratch dir for WAVs decoded from compressed cue files (removed on close).
        self._cue_cache_dir = Path(tempfile.mkdtemp(prefix="smacc-cues-"))
        # Shared fade (attack/release) durations in seconds; 0 == instant.
        self.cue_attack_s = 0.0
        self.cue_release_s = 0.0
        self._cue_fade_anim: QtCore.QPropertyAnimation | None = None
        self._playing_index: int | None = None
        # Populated incrementally so the per-slot signal handlers (fired by the
        # initial setValue below) can already index self.slots.
        self.slots: list[CueSlot] = []
        self._make_slots()
        self.setCentralWidget(self._build())

    # ----- construction ------------------------------------------------------

    def _make_slots(self) -> None:
        for i in range(N_CUE_SLOTS):
            player = QtMultimedia.QSoundEffect()
            player.setLoopCount(1)
            nameEdit = QtWidgets.QLineEdit(f"Cue {i + 1}", self)
            nameEdit.setMaximumWidth(90)
            fileEdit = QtWidgets.QLineEdit(self)
            fileEdit.setMinimumWidth(180)
            browseButton = QtWidgets.QPushButton("Browse", self)
            volumeSpinBox = QtWidgets.QDoubleSpinBox(self)
            volumeSpinBox.setRange(0, 1)  # QSoundEffect only allows 0-1
            volumeSpinBox.setSingleStep(0.01)
            volumeSpinBox.setMaximumWidth(70)
            loopCheckBox = QtWidgets.QCheckBox(self)
            loopCheckBox.setStatusTip("Repeat this cue until stopped.")
            loopCheckBox.setToolTip("Loop until stopped")
            playButton = QtWidgets.QPushButton("Play", self)
            stopButton = QtWidgets.QPushButton("Stop", self)
            slot = CueSlot(
                i,
                player,
                nameEdit,
                fileEdit,
                browseButton,
                volumeSpinBox,
                loopCheckBox,
                playButton,
                stopButton,
            )
            self.slots.append(slot)  # append before wiring so handlers can index it
            player.playingChanged.connect(partial(self.on_slot_playing_change, i))
            fileEdit.textChanged.connect(partial(self.update_slot_source, i))
            fileEdit.editingFinished.connect(partial(self.update_slot_source, i))
            volumeSpinBox.valueChanged.connect(partial(self.update_slot_volume, i))
            loopCheckBox.toggled.connect(partial(self.update_slot_loop, i))
            browseButton.clicked.connect(partial(self.open_audio_selector, i))
            playButton.clicked.connect(partial(self.play_slot, i))
            stopButton.clicked.connect(partial(self.stop_slot, i))
            volumeSpinBox.setValue(0.2)  # fires update_slot_volume -> player

    def _build(self) -> QtWidgets.QWidget:
        # Shared device + fade controls.
        available_speakers_dropdown = QtWidgets.QComboBox()
        available_speakers_dropdown.setPlaceholderText("No speaker devices were found.")
        # Qt5's QSoundEffect has no output-device selection, so this picker can't
        # route cues. Disabled (but populated) until the playback engine is moved
        # onto a backend that supports device selection; see the follow-up issue.
        available_speakers_dropdown.setEnabled(False)
        available_speakers_dropdown.setStatusTip(
            "Device selection isn't supported for cues yet; they play on the system "
            "default output."
        )
        available_speakers_dropdown.setToolTip(
            "Qt5 can't route cue playback to a specific device; cues use the system "
            "default output."
        )
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
        header.setLabelAlignment(QtCore.Qt.AlignRight)
        header.addRow("Device:", available_speakers_dropdown)
        header.addRow("Fade in:", attackSpinBox)
        header.addRow("Fade out:", releaseSpinBox)

        # "Now playing" indicator on top of the slot table (mixing-board style).
        self.nowPlayingLabel = QtWidgets.QLabel("■ stopped", self)
        self.nowPlayingLabel.setAlignment(QtCore.Qt.AlignCenter)

        # Cue table: a header row + one row per slot.
        grid = QtWidgets.QGridLayout()
        for col, title in enumerate(["Name", "Sound", "Vol", "Loop", "", ""]):
            label = QtWidgets.QLabel(title, self)
            label.setStyleSheet("font-weight: bold;")
            grid.addWidget(label, 0, col)
        for slot in self.slots:
            row = slot.index + 1
            grid.addWidget(slot.nameEdit, row, 0)
            sound = QtWidgets.QHBoxLayout()
            sound.addWidget(slot.fileEdit)
            sound.addWidget(slot.browseButton)
            grid.addLayout(sound, row, 1)
            grid.addWidget(slot.volumeSpinBox, row, 2)
            grid.addWidget(slot.loopCheckBox, row, 3)
            grid.addWidget(slot.playButton, row, 4)
            grid.addWidget(slot.stopButton, row, 5)
        grid.setColumnStretch(1, 1)

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(make_section_title("Audio cue"))
        layout.addLayout(header)
        layout.addWidget(self.nowPlayingLabel)
        layout.addLayout(grid)
        layout.addStretch(1)
        central = QtWidgets.QWidget()
        central.setLayout(layout)
        return central

    # ----- shared device + fade ---------------------------------------------

    def refresh_available_speakers(self):
        """Populate the device dropdown with available audio outputs."""
        self.available_speakers_dropdown.clear()
        devices = QtMultimedia.QAudioDeviceInfo.availableDevices(
            QtMultimedia.QAudio.AudioOutput
        )
        devices = [d for d in devices if d.realm() != "default"]
        for device in devices:
            device_name = device.deviceName()
            device_realm = device.realm()  # differentiates the default-output dupe
            device_str = f"{device_name} [{device_realm}]"
            self.available_speakers_dropdown.addItem(device_str)
        if devices:
            self.available_speakers_dropdown.setCurrentIndex(0)
        else:
            self.session.show_error_popup("No audio devices found.", parent=self)

    def update_cue_attack(self, value: float) -> None:
        """Set the shared cue fade-in (attack) time in seconds."""
        self.cue_attack_s = value
        self.session.log_interaction(f"Cue fade-in set to {value:.1f}s")

    def update_cue_release(self, value: float) -> None:
        """Set the shared cue fade-out (release) time in seconds."""
        self.cue_release_s = value
        self.session.log_interaction(f"Cue fade-out set to {value:.1f}s")

    def _fade_volume(
        self,
        player: QtMultimedia.QSoundEffect,
        start: float,
        end: float,
        seconds: float,
    ) -> QtCore.QPropertyAnimation:
        """Animate ``player``'s volume from ``start`` to ``end``."""
        anim = QtCore.QPropertyAnimation(player, b"volume", self)
        anim.setDuration(int(seconds * 1000))
        anim.setStartValue(float(start))
        anim.setEndValue(float(end))
        anim.start()
        self._cue_fade_anim = anim  # one-at-a-time, so a single ref is enough
        return anim

    # ----- per-slot controls -------------------------------------------------

    def open_audio_selector(self, index: int) -> None:
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select a File",
            str(self.session.cues_dir),
            "Audio (*.wav *.mp3 *.flac *.ogg *.oga *.aif *.aiff);;All files (*)",
        )
        if filename:
            self.slots[index].fileEdit.setText(str(Path(filename)))

    def update_slot_source(self, index: int) -> None:
        """Set a slot player's source from its file line edit.

        Non-WAV files are decoded to a cached WAV first, since QSoundEffect only
        plays uncompressed WAV. Fired on every keystroke, so missing/partial paths
        are skipped silently; only a genuine decode failure raises a popup.
        """
        player = self.slots[index].player
        filepath = self.slots[index].fileEdit.text().strip()
        if not filepath or not Path(filepath).is_file():
            player.setSource(QtCore.QUrl())  # clear: nothing loaded
            return
        try:
            wav = ensure_wav(Path(filepath), self._cue_cache_dir)
        except Exception as err:
            player.setSource(QtCore.QUrl())
            self.session.show_error_popup(
                "Could not load audio file", str(err), parent=self
            )
            return
        player.setSource(QtCore.QUrl.fromLocalFile(str(wav)))

    def update_slot_volume(self, index: int, value: float | None = None) -> None:
        """Set a slot player's volume (0-1) from its spinbox."""
        slot = self.slots[index]
        vol = slot.volumeSpinBox.value()
        slot.player.setVolume(vol)
        self.session.log_interaction(
            f"Cue '{slot.nameEdit.text()}' volume set to {vol:.2f}"
        )

    def update_slot_loop(self, index: int, enabled: bool | None = None) -> None:
        """Set a slot player's loop count from its checkbox."""
        slot = self.slots[index]
        looping = slot.loopCheckBox.isChecked()
        count = QtMultimedia.QSoundEffect.Infinite if looping else 1
        slot.player.setLoopCount(count)
        self.session.log_interaction(
            f"Cue '{slot.nameEdit.text()}' loop {'on' if looping else 'off'}"
        )

    def play_slot(self, index: int) -> None:
        """Play one slot (stopping any other playing slot first) with fade-in."""
        slot = self.slots[index]
        if not slot.fileEdit.text().strip():
            return  # nothing loaded in this slot
        # One-at-a-time: stop whatever else is playing (fires its CueStopped).
        if self._playing_index is not None and self._playing_index != index:
            self.slots[self._playing_index].player.stop()
        self._playing_index = index
        target = slot.volumeSpinBox.value()
        if self.cue_attack_s > 0:
            slot.player.setVolume(0.0)
            slot.player.play()
            self._fade_volume(slot.player, 0.0, target, self.cue_attack_s)
        else:
            slot.player.setVolume(target)
            slot.player.play()
        self.session.emit_event("CueStarted", detail=slot.nameEdit.text())

    def stop_slot(self, index: int) -> None:
        """Stop a slot (with fade-out) if it is the one currently playing."""
        slot = self.slots[index]
        if not slot.player.isPlaying():
            return
        if self.cue_release_s > 0:
            anim = self._fade_volume(
                slot.player, slot.player.volume(), 0.0, self.cue_release_s
            )
            anim.finished.connect(slot.player.stop)
        else:
            slot.player.stop()

    def on_slot_playing_change(self, index: int) -> None:
        """Track each slot's play/stop edges: update the label, emit markers.

        CueStarted is emitted by play_slot (the user action); here we detect the
        playing->stopped edge per slot to emit CueStopped, so a natural end (a
        non-looping cue finishing) is marked too, with no double-fire.
        """
        slot = self.slots[index]
        playing = slot.player.isPlaying()
        if playing and not slot.was_playing:
            slot.was_playing = True
            self._playing_index = index
            looping = slot.loopCheckBox.isChecked()
            name = slot.nameEdit.text()
            self.nowPlayingLabel.setText(
                f"\U0001f501 {name} (looping)" if looping else f"▶ {name}"
            )
            self.nowPlayingLabel.setStyleSheet("color: red; font-weight: bold;")
        elif not playing and slot.was_playing:
            slot.was_playing = False
            self.session.emit_event("CueStopped", detail=slot.nameEdit.text())
            if self._playing_index == index:
                self._playing_index = None
                self.nowPlayingLabel.setText("■ stopped")
                self.nowPlayingLabel.setStyleSheet("")

    # ----- settings state ----------------------------------------------------

    def gather_state(self) -> dict:
        return {
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
        cues = state.get("cues")
        if isinstance(cues, list):
            for slot, cue in zip(self.slots, cues, strict=False):
                self._apply_cue(slot, cue)
        elif state.get("cue_file") is not None or state.get("cue_volume") is not None:
            # Back-compat: a v1 single cue maps into the first slot.
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
            slot.fileEdit.setText(str(f))
        if (v := cue.get("volume")) is not None:
            slot.volumeSpinBox.setValue(float(v))
        slot.loopCheckBox.setChecked(bool(cue.get("loop", False)))

    def cleanup(self) -> None:
        for slot in self.slots:
            slot.player.stop()
        shutil.rmtree(self._cue_cache_dir, ignore_errors=True)
