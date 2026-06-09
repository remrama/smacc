"""Audio cue window: a multi-slot cue board (file/volume/loop per slot).

Each slot preloads its own sound with its own volume and loop setting, so a
protocol that uses several sounds (e.g. cue vs. sham) can keep them ready and
fire any one with a click. Playback is one-at-a-time (playing a slot stops
whatever was playing); fade-in/out is shared at the panel level. Slots can be
added and removed on the fly — one is always required, up to a generous cap — and
the first slot autofills with a random demo cue so a fresh study is immediately
playable (#65).
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import cast

from PyQt6 import QtCore, QtMultimedia, QtWidgets

from ..session import SmaccSession
from ..utils import ensure_wav, pick_random_demo_cue
from .base import ModalityWindow, make_section_title

# One cue is always required; the upper bound is generous (a session typically
# uses 2-5) but capped so the grid and playback stay manageable (#65).
MIN_CUE_SLOTS = 1
MAX_CUE_SLOTS = 20


@dataclass
class CueSlot:
    """One preloaded cue: its player plus the row of widgets that control it.

    Signal handlers bind to the slot *object*, never a row index, so adding or
    removing rows can't misroute another slot's controls.
    """

    player: QtMultimedia.QSoundEffect
    nameEdit: QtWidgets.QLineEdit
    fileEdit: QtWidgets.QLineEdit
    browseButton: QtWidgets.QPushButton
    volumeSpinBox: QtWidgets.QDoubleSpinBox
    loopCheckBox: QtWidgets.QCheckBox
    playButton: QtWidgets.QPushButton
    stopButton: QtWidgets.QPushButton
    removeButton: QtWidgets.QPushButton
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
        self._playing_slot: CueSlot | None = None
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
        player = QtMultimedia.QSoundEffect()
        player.setLoopCount(1)
        nameEdit = QtWidgets.QLineEdit(name, self)
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
        removeButton = QtWidgets.QPushButton("✕", self)  # ✕
        removeButton.setMaximumWidth(28)
        removeButton.setStatusTip("Remove this cue.")
        removeButton.setToolTip("Remove this cue")
        slot = CueSlot(
            player,
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
        player.playingChanged.connect(partial(self.on_slot_playing_change, slot))
        fileEdit.textChanged.connect(partial(self.update_slot_source, slot))
        fileEdit.editingFinished.connect(partial(self.update_slot_source, slot))
        volumeSpinBox.valueChanged.connect(partial(self.update_slot_volume, slot))
        loopCheckBox.toggled.connect(partial(self.update_slot_loop, slot))
        browseButton.clicked.connect(partial(self.open_audio_selector, slot))
        playButton.clicked.connect(partial(self.play_slot, slot))
        stopButton.clicked.connect(partial(self.stop_slot, slot))
        removeButton.clicked.connect(partial(self.remove_slot, slot))
        volumeSpinBox.setValue(0.2)  # fires update_slot_volume -> player
        return slot

    def _add_initial_slot(self) -> None:
        """Create the single required slot and prefill a random demo cue (#65)."""
        slot = self._make_slot("Cue 1")
        demo = pick_random_demo_cue(self.session.cues_dir)
        if demo is not None:
            slot.fileEdit.setText(str(demo))
        self._rebuild_grid()

    def _build(self) -> QtWidgets.QWidget:
        # Shared device + fade controls.
        available_speakers_dropdown = QtWidgets.QComboBox()
        available_speakers_dropdown.setPlaceholderText("No speaker devices were found.")
        # Cue playback (QSoundEffect) isn't routed to a chosen device yet, so this
        # picker is populated for reference but disabled until cue playback moves
        # onto the unified sounddevice engine; see the follow-up issue.
        available_speakers_dropdown.setEnabled(False)
        available_speakers_dropdown.setStatusTip(
            "Device selection isn't supported for cues yet; they play on the system "
            "default output."
        )
        available_speakers_dropdown.setToolTip(
            "Cue playback can't be routed to a specific device yet; cues use the "
            "system default output."
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
        """Tear down a removed slot: silence it, drop late signals, free widgets."""
        if self._playing_slot is slot:
            self._playing_slot = None
            self._set_now_playing_stopped()
        # Drop the playing-edge connection before deleting so a late edge can't fire
        # into a half-torn-down slot, then stop any sound it was making.
        try:
            slot.player.playingChanged.disconnect()
        except TypeError:
            pass  # nothing connected
        slot.player.stop()
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
        """Populate the (disabled) device dropdown with available audio outputs.

        QSoundEffect can't route to a chosen device, so this list is shown for
        reference only (the picker is disabled); it mirrors Qt's current outputs.
        """
        self.available_speakers_dropdown.clear()
        for device in QtMultimedia.QMediaDevices.audioOutputs():
            self.available_speakers_dropdown.addItem(device.description())
        if self.available_speakers_dropdown.count():
            self.available_speakers_dropdown.setCurrentIndex(0)

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
        """Set a slot player's source from its file line edit.

        Non-WAV files are decoded to a cached WAV first, since QSoundEffect only
        plays uncompressed WAV. Fired on every keystroke, so missing/partial paths
        are skipped silently; only a genuine decode failure raises a popup.
        """
        player = slot.player
        filepath = slot.fileEdit.text().strip()
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

    def update_slot_volume(self, slot: CueSlot, value: float | None = None) -> None:
        """Set a slot player's volume (0-1) from its spinbox."""
        vol = slot.volumeSpinBox.value()
        slot.player.setVolume(vol)
        self.session.log_interaction(
            f"Cue '{slot.nameEdit.text()}' volume set to {vol:.2f}"
        )

    def update_slot_loop(self, slot: CueSlot, enabled: bool | None = None) -> None:
        """Set a slot player's loop count from its checkbox."""
        looping = slot.loopCheckBox.isChecked()
        # QSoundEffect.Loop is a plain Enum here; its .value is the int (-2) that
        # setLoopCount expects (mypy mistypes the member, so coerce to int).
        infinite = cast(int, QtMultimedia.QSoundEffect.Loop.Infinite.value)
        count = infinite if looping else 1
        slot.player.setLoopCount(count)
        self.session.log_interaction(
            f"Cue '{slot.nameEdit.text()}' loop {'on' if looping else 'off'}"
        )

    def play_slot(self, slot: CueSlot) -> None:
        """Play one slot (stopping any other playing slot first) with fade-in."""
        if not slot.fileEdit.text().strip():
            return  # nothing loaded in this slot
        # One-at-a-time: stop whatever else is playing (fires its CueStopped).
        if self._playing_slot is not None and self._playing_slot is not slot:
            self._playing_slot.player.stop()
        self._playing_slot = slot
        target = slot.volumeSpinBox.value()
        if self.cue_attack_s > 0:
            slot.player.setVolume(0.0)
            slot.player.play()
            self._fade_volume(slot.player, 0.0, target, self.cue_attack_s)
        else:
            slot.player.setVolume(target)
            slot.player.play()
        self.session.emit_event("CueStarted", detail=slot.nameEdit.text())

    def stop_slot(self, slot: CueSlot) -> None:
        """Stop a slot (with fade-out) if it is the one currently playing."""
        if not slot.player.isPlaying():
            return
        if self.cue_release_s > 0:
            anim = self._fade_volume(
                slot.player, slot.player.volume(), 0.0, self.cue_release_s
            )
            anim.finished.connect(slot.player.stop)
        else:
            slot.player.stop()

    def on_slot_playing_change(self, slot: CueSlot) -> None:
        """Track each slot's play/stop edges: update the label, emit markers.

        CueStarted is emitted by play_slot (the user action); here we detect the
        playing->stopped edge per slot to emit CueStopped, so a natural end (a
        non-looping cue finishing) is marked too, with no double-fire.
        """
        if slot not in self.slots:
            return  # a removed slot's late signal; ignore
        playing = slot.player.isPlaying()
        if playing and not slot.was_playing:
            slot.was_playing = True
            self._playing_slot = slot
            looping = slot.loopCheckBox.isChecked()
            name = slot.nameEdit.text()
            self.nowPlayingLabel.setText(
                f"\U0001f501 {name} (looping)" if looping else f"▶ {name}"
            )
            self.nowPlayingLabel.setStyleSheet("color: red; font-weight: bold;")
        elif not playing and slot.was_playing:
            slot.was_playing = False
            self.session.emit_event("CueStopped", detail=slot.nameEdit.text())
            if self._playing_slot is slot:
                self._playing_slot = None
                self._set_now_playing_stopped()

    def _set_now_playing_stopped(self) -> None:
        self.nowPlayingLabel.setText("■ stopped")  # ■
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
            slot.fileEdit.setText(str(f))
        if (v := cue.get("volume")) is not None:
            slot.volumeSpinBox.setValue(float(v))
        slot.loopCheckBox.setChecked(bool(cue.get("loop", False)))

    def cleanup(self) -> None:
        for slot in self.slots:
            slot.player.stop()
        shutil.rmtree(self._cue_cache_dir, ignore_errors=True)
