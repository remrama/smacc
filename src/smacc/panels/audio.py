"""Audio cue window: a mixer console of per-cue channel strips (#289).

Each cue is a vertical strip — name, sound file, a volume fader (with a precise
spinbox), and icon transport buttons (play / stop / loop-toggle / remove) — laid
side by side like a mixing desk, with a master strip on the right for the level
meters and the shared fade-in/out. A strip preloads its own sound with its own
volume and loop setting, so a protocol that uses several sounds (e.g. cue vs. sham)
can keep them ready and fire any one with a click. Playback is one-at-a-time
(playing a strip stops whatever was playing) on a sounddevice output stream routed
to a chosen device. Strips can be added and removed on the fly — one is always
required, up to a generous cap — and a fresh study opens with two strips, each
autofilled with a distinct random demo so it is immediately playable (#65).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import partial
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf
from PyQt6 import QtCore, QtWidgets

from .. import audio, devices, utils
from ..session import SmaccSession
from ..utils import pick_random_demo_cues
from .base import (
    PanelWindow,
    describe_action,
    make_section_title,
    require_device,
    resolve_device,
    restore_spin_value,
)
from .meter import InputLevelMeter, LevelMeter

# One cue is always required; the upper bound is generous (a session typically
# uses 2-5) but capped so the console and playback stay manageable (#65). A fresh
# study opens with two strips, each prefilled with a distinct demo.
MIN_CUE_SLOTS = 1
INITIAL_CUE_SLOTS = 2
MAX_CUE_SLOTS = 20
# Fallback output rate when a device's own rate can't be queried.
CUE_RATE = 44100
# Width of one channel strip; narrow enough to line several up like a mixer (#289).
CUE_STRIP_WIDTH = 108
# Square icon size for the transport buttons (play/stop/loop/remove).
CUE_ICON_SIZE = 18


@dataclass
class CueSlot:
    """One preloaded cue: its decoded audio plus the channel strip controlling it.

    Signal handlers bind to the slot *object*, never a position, so adding or
    removing strips can't misroute another slot's controls. ``audio`` is the
    decoded mono float32 buffer at its native ``rate`` (resampled to the device
    rate when played); ``None`` until a valid file is loaded. ``file_path`` is the
    chosen sound's full path (the compact ``fileButton`` shows only its stem).
    """

    strip: QtWidgets.QFrame
    nameEdit: QtWidgets.QLineEdit
    fileButton: QtWidgets.QPushButton
    volumeSlider: QtWidgets.QSlider
    volumeSpinBox: QtWidgets.QDoubleSpinBox
    loopButton: QtWidgets.QPushButton
    playButton: QtWidgets.QPushButton
    stopButton: QtWidgets.QPushButton
    removeButton: QtWidgets.QPushButton
    file_path: str = field(default="")
    audio: np.ndarray | None = field(default=None)
    rate: int = field(default=0)


@dataclass
class CueOutput:
    """One open output for a playing cue: its mixer plus the stream rendering it.

    A cue normally has one (the cue device); a routed monitor adds a second on the
    control-room device, fed by its own mixer so the two play independently.
    """

    mixer: audio.CueMixer
    stream: sd.OutputStream


class AudioCueWindow(PanelWindow):
    """Multi-slot cue board with a shared device + fade and per-slot play/stop."""

    TITLE = "Audio cue"

    def __init__(self, session: SmaccSession, parent: QtWidgets.QWidget | None = None):
        super().__init__(session, parent)
        # Shared fade (attack/release) durations in seconds; 0 == instant.
        self.cue_attack_s = 0.0
        self.cue_release_s = 0.0
        # The active cue's outputs (cue device + optional monitor), each with its
        # own mixer. A GUI-thread timer polls the primary output for the cue
        # finishing (so the stop can be marked + the UI reset).
        self._outputs: list[CueOutput] = []
        self._active_slot: CueSlot | None = None
        self._cue_timer = QtCore.QTimer(self)
        self._cue_timer.setInterval(30)  # ~33 Hz: finish detection, not playback
        self._cue_timer.timeout.connect(self._poll_cue)
        # Monitoring meters (#37), built before _build(): the latter calls
        # refresh_device_indicator(), which touches the room-monitor widgets. The
        # output "sending" meter is fed the level of each block the cue callback emits.
        self._out_level_db = audio.FLOOR_DBFS
        self.outMeter = LevelMeter(self)
        self.roomMeter = InputLevelMeter(self)
        self.monitorCheckBox = QtWidgets.QCheckBox(self)
        self.monitorDeviceLabel = QtWidgets.QLabel(self)
        # Populated after the central widget exists so _rebuild_strips has its
        # strip row and add button to work with.
        self.slots: list[CueSlot] = []
        self.setCentralWidget(self._build())
        # Start with two strips, each prefilled with a random demo so a fresh study
        # can play something immediately; a loaded study overrides them.
        self._add_initial_slots()

    # ----- construction ------------------------------------------------------

    def _make_slot(self, name: str) -> CueSlot:
        """Build one fully-wired cue channel strip and append it to ``self.slots``.

        A vertical strip stacks (top to bottom) the name, a compact file button, a
        vertical volume fader synced to a precise spinbox, and the icon transport
        buttons (play / stop / loop-toggle / remove) — the mixer channel of #289.
        """
        strip = QtWidgets.QFrame(self)
        strip.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        strip.setFixedWidth(CUE_STRIP_WIDTH)
        strip.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Expanding
        )

        nameEdit = QtWidgets.QLineEdit(name, strip)
        nameEdit.setStatusTip("Name this cue (shown in the EEG marker).")
        fileButton = QtWidgets.QPushButton(strip)
        fileButton.setStatusTip("Choose this cue's sound file.")
        volumeSlider = QtWidgets.QSlider(QtCore.Qt.Orientation.Vertical, strip)
        volumeSlider.setRange(0, 100)  # mirrors the 0-1 spinbox at 0.01 resolution
        volumeSlider.setStatusTip("Cue volume (fader).")
        volumeSpinBox = QtWidgets.QDoubleSpinBox(strip)
        volumeSpinBox.setRange(0, 1)  # software gain at unity-or-below (no clipping)
        volumeSpinBox.setSingleStep(0.01)
        # Transport buttons: icon-only, stacked like a mixer channel's foot (#289).
        # The loop button is a depressable toggle (lit while looping).
        loopButton = self._make_icon_button(
            QtWidgets.QStyle.StandardPixmap.SP_BrowserReload,
            "Loop",
            "Repeat this cue until stopped.",
            checkable=True,
        )
        playButton = self._make_icon_button(
            QtWidgets.QStyle.StandardPixmap.SP_MediaPlay,
            "Play",
            "Play this cue.",
        )
        stopButton = self._make_icon_button(
            QtWidgets.QStyle.StandardPixmap.SP_MediaStop,
            "Stop",
            "Stop this cue.",
        )
        removeButton = self._make_icon_button(
            QtWidgets.QStyle.StandardPixmap.SP_TrashIcon,
            "Remove",
            "Remove this cue.",
        )

        box = QtWidgets.QVBoxLayout(strip)
        box.setContentsMargins(4, 4, 4, 4)
        box.addWidget(nameEdit)
        box.addWidget(fileButton)
        box.addWidget(volumeSlider, 1, QtCore.Qt.AlignmentFlag.AlignHCenter)
        box.addWidget(volumeSpinBox)
        box.addWidget(playButton)
        box.addWidget(stopButton)
        box.addWidget(loopButton)
        box.addWidget(removeButton)

        slot = CueSlot(
            strip,
            nameEdit,
            fileButton,
            volumeSlider,
            volumeSpinBox,
            loopButton,
            playButton,
            stopButton,
            removeButton,
        )
        self.slots.append(slot)  # append before wiring so handlers can resolve it
        # The spinbox stays the source of truth (state + live volume); the fader
        # just rides it. Setting the spinbox echoes to the fader (signals blocked);
        # dragging the fader sets the spinbox (signals live, so volume updates).
        volumeSpinBox.valueChanged.connect(partial(self.update_slot_volume, slot))
        volumeSpinBox.valueChanged.connect(partial(self._sync_slider_from_spin, slot))
        volumeSlider.valueChanged.connect(partial(self._sync_spin_from_slider, slot))
        loopButton.toggled.connect(partial(self.update_slot_loop, slot))
        fileButton.clicked.connect(partial(self.open_audio_selector, slot))
        playButton.clicked.connect(partial(self.play_slot, slot))
        stopButton.clicked.connect(partial(self.stop_slot, slot))
        removeButton.clicked.connect(partial(self.remove_slot, slot))
        volumeSpinBox.setValue(0.2)  # fires update_slot_volume + fader sync
        self.set_slot_file(slot, "")  # label the empty file button
        return slot

    def _make_icon_button(
        self,
        pixmap: QtWidgets.QStyle.StandardPixmap,
        label: str,
        status: str,
        *,
        checkable: bool = False,
    ) -> QtWidgets.QPushButton:
        """Build a compact icon-only transport button from a Qt standard icon.

        Standard icons keep this asset-free and theme-aware; ``label`` is the
        tooltip/accessible name (no visible text), ``status`` the status-bar hint.
        A checkable button (the loop toggle) gets a bold "armed" fill, since
        Fusion's default sunken look is too subtle to read across a strip at 3 a.m.
        """
        button = QtWidgets.QPushButton(self)
        style = self.style()
        assert style is not None  # a realized widget always has a style
        button.setIcon(style.standardIcon(pixmap))
        button.setIconSize(QtCore.QSize(CUE_ICON_SIZE, CUE_ICON_SIZE))
        button.setToolTip(label)
        button.setStatusTip(status)
        button.setAccessibleName(label)
        button.setCheckable(checkable)
        if checkable:
            # palette(highlight/highlighted-text) follows the theme; the checked
            # fill makes an armed loop obvious at a glance, not just sunken.
            button.setStyleSheet(
                "QPushButton:checked {"
                " background-color: palette(highlight);"
                " border: 1px solid palette(highlight); }"
            )
        return button

    def _add_initial_slots(self) -> None:
        """Open with two cue strips, each prefilled with a distinct demo (#65, #289)."""
        demos = pick_random_demo_cues(self.session.cues_dir, INITIAL_CUE_SLOTS)
        for i in range(INITIAL_CUE_SLOTS):
            slot = self._make_slot(f"Cue {len(self.slots) + 1}")
            if i < len(demos):
                self.set_slot_file(slot, str(demos[i]))
        self._rebuild_strips()

    def _build(self) -> QtWidgets.QWidget:
        # Shared cue output device (chosen in the Devices window); the fade controls
        # live in the master strip.
        self.deviceLabel = QtWidgets.QLabel(self)
        self.deviceLabel.setStatusTip("Set in the Devices window (Play audio cue).")
        self.refresh_device_indicator()
        self.attackSpinBox = self._make_fade_spin(
            "Fade-in time for the cue, in seconds (0 = instant).",
            self.update_cue_attack,
        )
        self.releaseSpinBox = self._make_fade_spin(
            "Fade-out time when stopping the cue, in seconds (0 = instant).",
            self.update_cue_release,
        )

        header = QtWidgets.QFormLayout()
        header.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        header.addRow("Device:", self.deviceLabel)

        # "Now playing" indicator across the top (mixing-board style).
        self.nowPlayingLabel = QtWidgets.QLabel("■ stopped", self)  # ■
        self.nowPlayingLabel.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

        # Channel strips: one rebuildable QFrame per slot in a left-to-right row,
        # then the persistent "add" button. A rebuild only reparents the strips
        # (never deletes them), so live controls survive untouched.
        self._stripRow = QtWidgets.QHBoxLayout()
        self._addButton = QtWidgets.QPushButton("+ Add cue", self)
        self._addButton.setStatusTip(f"Add another cue (up to {MAX_CUE_SLOTS}).")
        self._addButton.setToolTip("Add another cue")
        self._addButton.clicked.connect(self.add_slot)
        self._rebuild_strips()

        # The strip row scrolls horizontally so the cap of 20 cues can't blow out
        # the window width; the usual 2-5 fit without a scrollbar.
        stripHost = QtWidgets.QWidget()
        stripHost.setLayout(self._stripRow)
        scroll = QtWidgets.QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(stripHost)
        scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setMinimumSize(360, 320)

        console = QtWidgets.QHBoxLayout()
        console.addWidget(scroll, 1)
        console.addWidget(self._build_master())

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(make_section_title("Audio cue"))
        layout.addLayout(header)
        layout.addWidget(self.nowPlayingLabel)
        layout.addLayout(console, 1)
        central = QtWidgets.QWidget()
        central.setLayout(layout)
        return central

    def _make_fade_spin(self, status: str, handler) -> QtWidgets.QDoubleSpinBox:
        """Build a shared fade (attack/release) spinbox in seconds."""
        spin = QtWidgets.QDoubleSpinBox(self)
        spin.setStatusTip(status)
        spin.setRange(0, 60)
        spin.setSingleStep(0.1)
        spin.setSuffix(" seconds")
        spin.valueChanged.connect(handler)
        spin.setValue(0.0)
        return spin

    def _rebuild_strips(self) -> None:
        """Re-lay the channel-strip row: one strip per slot, then the add button.

        Every strip is a persistent widget, so clearing only reparents the layout
        items out — nothing is deleted — and they're re-added in order, followed by
        the add button and a trailing stretch that keeps strips left-packed.
        """
        while self._stripRow.count():
            self._stripRow.takeAt(0)  # drop the layout item only; strips are reused
        for slot in self.slots:
            self._stripRow.addWidget(slot.strip)
            # The lone required slot can't be removed: keep the button (so the strip
            # doesn't reflow) but disabled.
            slot.removeButton.setEnabled(len(self.slots) > MIN_CUE_SLOTS)
        self._stripRow.addWidget(self._addButton, 0, QtCore.Qt.AlignmentFlag.AlignTop)
        self._addButton.setEnabled(len(self.slots) < MAX_CUE_SLOTS)
        self._stripRow.addStretch(1)

    # ----- add / remove slots ------------------------------------------------

    def add_slot(self) -> None:
        """Append a new (empty) cue strip, up to the cap (#65)."""
        if len(self.slots) >= MAX_CUE_SLOTS:
            return
        slot = self._make_slot(f"Cue {len(self.slots) + 1}")
        self._rebuild_strips()
        self.session.log_interaction(f"Added cue '{slot.nameEdit.text()}'")

    def remove_slot(self, slot: CueSlot) -> None:
        """Remove a cue strip (never the last one), stopping it first (#65)."""
        if len(self.slots) <= MIN_CUE_SLOTS or slot not in self.slots:
            return
        name = slot.nameEdit.text()
        self.slots.remove(slot)
        self._destroy_slot_widgets(slot)
        self._rebuild_strips()
        self.session.log_interaction(f"Removed cue '{name}'")

    def _destroy_slot_widgets(self, slot: CueSlot) -> None:
        """Tear down a removed slot: silence it if playing, then free its strip."""
        if self._active_slot is slot:
            self._finish_active(mark=False)  # silence without a spurious marker
        slot.strip.hide()  # leave no orphan visible before deferred deletion
        slot.strip.deleteLater()  # the strip's child widgets go with it

    def _resize_slots(self, count: int) -> None:
        """Grow/shrink the slot list to ``count`` (clamped to ``1..MAX``) (#65)."""
        count = max(MIN_CUE_SLOTS, min(count, MAX_CUE_SLOTS))
        while len(self.slots) < count:
            self._make_slot(f"Cue {len(self.slots) + 1}")
        while len(self.slots) > count:
            self._destroy_slot_widgets(self.slots.pop())
        self._rebuild_strips()

    # ----- shared device + fade ---------------------------------------------

    def refresh_device_indicator(self) -> None:
        """Show where cue output resolves, plus the monitor route when enabled."""
        text = describe_action(self.session, "play_audio_cue")
        if self.session.devices.equipment_for("listen_audio_cue"):
            text += (
                f"   •   monitor: {describe_action(self.session, 'listen_audio_cue')}"
            )
        self.deviceLabel.setText(text)
        self.monitorDeviceLabel.setText(
            describe_action(self.session, "monitor_bedroom_noise")
        )
        self._restart_room_monitor_if_active()

    def is_streaming(self) -> bool:
        """True while a cue is playing or the room monitor mic is open."""
        return bool(self._outputs) or self.roomMeter.is_active()

    def _device_samplerate(self, device: int | str | None) -> int:
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
            self.set_slot_file(slot, str(Path(filename)))

    def set_slot_file(self, slot: CueSlot, path: str) -> None:
        """Point a slot at a sound file: label its button and decode the audio.

        The compact button shows only the file's stem (full path on hover); the
        path is kept on the slot for playback and settings. An empty/missing path
        just clears the buffer silently; only a genuine decode failure raises a popup.
        """
        path = path.strip()
        slot.file_path = path
        name = Path(path).stem if path else ""
        avail = CUE_STRIP_WIDTH - 20  # leave room for the button's frame/padding
        elided = slot.fileButton.fontMetrics().elidedText(
            name, QtCore.Qt.TextElideMode.ElideMiddle, avail
        )
        slot.fileButton.setText(elided or "Choose sound…")
        slot.fileButton.setToolTip(path or "Choose this cue's sound file")
        if not path or not Path(path).is_file():
            slot.audio = None
            slot.rate = 0
            return
        try:
            data, file_rate = sf.read(path, dtype="float32")
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

    def _sync_slider_from_spin(self, slot: CueSlot, value: float | None = None) -> None:
        """Echo the spinbox onto the fader (signals blocked, so it doesn't loop back)."""
        target = round(slot.volumeSpinBox.value() * 100)
        if slot.volumeSlider.value() != target:
            slot.volumeSlider.blockSignals(True)
            slot.volumeSlider.setValue(target)
            slot.volumeSlider.blockSignals(False)

    def _sync_spin_from_slider(self, slot: CueSlot, value: int | None = None) -> None:
        """Drive the spinbox from a fader drag (live, so update_slot_volume fires)."""
        target = slot.volumeSlider.value() / 100
        if abs(slot.volumeSpinBox.value() - target) >= 1e-9:
            slot.volumeSpinBox.setValue(target)

    def update_slot_volume(self, slot: CueSlot, value: float | None = None) -> None:
        """Set a slot's volume (0-1) from its spinbox (live if it's playing)."""
        vol = slot.volumeSpinBox.value()
        if self._active_slot is slot:
            for out in self._outputs:
                out.mixer.volume = vol
        self.session.log_interaction(
            f"Cue '{slot.nameEdit.text()}' volume set to {vol:.2f}", debug=True
        )

    def update_slot_loop(self, slot: CueSlot, enabled: bool | None = None) -> None:
        """Set a slot's loop flag from its loop toggle button (live if it's playing)."""
        looping = slot.loopButton.isChecked()
        if self._active_slot is slot:
            for out in self._outputs:
                out.mixer.loop = looping
        self.session.log_interaction(
            f"Cue '{slot.nameEdit.text()}' loop {'on' if looping else 'off'}"
        )

    def play_slot(self, slot: CueSlot) -> None:
        """Play one slot (stopping any other playing slot first) with fade-in.

        Routes to the cue device, plus a second output on the control-room monitor
        when ``listen_audio_cue`` is routed to a different device (the cue fan-out).
        """
        if slot.audio is None or slot.audio.shape[0] == 0:
            return  # nothing loaded in this slot
        # One-at-a-time: cut whatever is playing. Mark a CueStopped only when a
        # *different* cue is replaced (re-playing the same slot is just a restart).
        if self._active_slot is not None:
            self._finish_active(mark=self._active_slot is not slot)
        device = require_device(
            self.session,
            "play_audio_cue",
            devices.OUTPUT,
            failure="Could not play the cue.",
            parent=self,
        )
        if device is None:
            return
        primary = self._open_output(slot, device)
        if primary is None:
            return  # primary failed (error already shown)
        self._outputs = [primary]
        monitor_device = resolve_device(
            self.session.devices.device_for("listen_audio_cue"), devices.OUTPUT
        )
        if monitor_device is not None and monitor_device != device:
            monitor = self._open_output(slot, monitor_device, optional=True)
            if monitor is not None:
                self._outputs.append(monitor)
        self._active_slot = slot
        self._cue_timer.start()
        self._set_now_playing(slot)
        # Mark the cue at its estimated onset: the sound reaches the speaker about one
        # output buffer after the stream starts, so pass that reported buffer latency.
        self.session.emit_event(
            "CueStarted",
            detail=slot.nameEdit.text(),
            onset_offset=float(primary.stream.latency),
        )

    def _open_output(
        self, slot: CueSlot, device: int | str | None, *, optional: bool = False
    ) -> CueOutput | None:
        """Open one cue output (mixer + stream) on ``device``; ``None`` on failure.

        A failed *optional* (monitor) output is swallowed so the primary cue still
        plays; a failed primary output surfaces an error.
        """
        rate = self._device_samplerate(device)
        assert slot.audio is not None  # play_slot returns early for an unloaded slot
        mixer = audio.CueMixer()
        mixer.start(
            utils.resample_to(slot.audio, slot.rate, rate),
            volume=slot.volumeSpinBox.value(),
            loop=slot.loopButton.isChecked(),
            attack_samples=int(self.cue_attack_s * rate),
        )
        try:
            stream = sd.OutputStream(
                channels=1,
                samplerate=rate,
                device=device,
                latency=self.session.output_latency,
                callback=partial(self._render_output, mixer),
            )
            stream.start()
        except Exception as err:
            if not optional:
                self.session.show_error_popup(
                    "Could not start cue output", str(err), parent=self
                )
            return None
        return CueOutput(mixer, stream)

    def stop_slot(self, slot: CueSlot) -> None:
        """Stop a slot (with fade-out) if it is the one currently playing."""
        if self._active_slot is not slot or not self._outputs:
            return
        for out in self._outputs:
            out.mixer.stop(
                release_samples=int(self.cue_release_s * out.stream.samplerate)
            )
        if self._outputs[0].mixer.ended:  # instant stop (no release fade)
            self._finish_active()
        # Otherwise the release fade runs and _poll_cue finalizes it when done.

    def _render_output(self, mixer, outdata, frames, time, status) -> None:
        """sounddevice callback (audio thread): render one output's cue block."""
        if status:
            self.session.logger.warning(f"Audio output status: {status}")
        # The master safety cap is the single final gain stage (read live).
        outdata[:, 0] = mixer.render(frames) * self.session.volume_cap
        # Stash the level actually sent (post-cap) for the "sending" meter (#37).
        self._out_level_db = audio.rms_dbfs(outdata[:, 0])

    def _poll_cue(self) -> None:
        """GUI-thread timer: drive the output meter, then finalize once the cue ends."""
        self.outMeter.show_level(self._out_level_db)
        if (
            self._active_slot is not None
            and self._outputs
            and self._outputs[0].mixer.ended
        ):
            self._finish_active()

    def _finish_active(self, mark: bool = True) -> None:
        """Tear down the cue's outputs and reset the UI; mark CueStopped when ``mark``."""
        slot = self._active_slot
        self._cue_timer.stop()
        for out in self._outputs:
            out.stream.abort()
            out.stream.close()
        self._outputs = []
        self._active_slot = None
        self._set_now_playing_stopped()
        self.outMeter.clear_level()
        self._out_level_db = audio.FLOOR_DBFS
        if mark and slot is not None:
            self.session.emit_event("CueStopped", detail=slot.nameEdit.text())

    def _set_now_playing(self, slot: CueSlot) -> None:
        looping = slot.loopButton.isChecked()
        name = slot.nameEdit.text()
        base = f"\U0001f501 {name} (looping)" if looping else f"▶ {name}"
        monitor = " + monitor" if len(self._outputs) > 1 else ""
        self.nowPlayingLabel.setText(base + monitor)
        self.nowPlayingLabel.setStyleSheet("color: red; font-weight: bold;")

    def _set_now_playing_stopped(self) -> None:
        self.nowPlayingLabel.setText("■ stopped")  # ■
        self.nowPlayingLabel.setStyleSheet("")

    # ----- master strip / monitoring (#37, #289) ----------------------------

    def _build_master(self) -> QtWidgets.QWidget:
        """Build the master strip: the Sending + Bedroom meters and the shared fades.

        'Sending' shows the level SMACC emits — a deterministic diagnostic, but blind
        to a muted or unplugged speaker. 'Bedroom' is the objective acoustic check: a
        mic in the room, the only thing that confirms the cue was actually audible.
        Its mic is the Room-monitor route (a dedicated mic, or the bedroom mic).
        """
        heading = QtWidgets.QLabel("Master", self)
        heading.setStyleSheet("font-weight: bold;")

        self.outMeter.setStatusTip(
            "Level SMACC is sending to the cue output — confirms emission, not that "
            "the bedroom speaker actually sounded."
        )
        self.monitorCheckBox.setStatusTip(
            "Open the bedroom monitor mic to confirm the cue is audible in the room "
            "(set its device in the Devices window)."
        )
        self.monitorCheckBox.setToolTip("Listen on the bedroom monitor mic")
        self.monitorCheckBox.toggled.connect(self.toggle_room_monitor)
        self.monitorDeviceLabel.setStatusTip(
            "Set in the Devices window (Monitor bedroom noise)."
        )
        self.monitorDeviceLabel.setWordWrap(True)

        roomRow = QtWidgets.QHBoxLayout()
        roomRow.addWidget(self.monitorCheckBox)
        roomRow.addWidget(self.roomMeter)

        meters = QtWidgets.QFormLayout()
        meters.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        meters.addRow("Sending:", self.outMeter)
        meters.addRow("Bedroom:", roomRow)
        meters.addRow("Monitor mic:", self.monitorDeviceLabel)

        fades = QtWidgets.QFormLayout()
        fades.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        fades.addRow("Fade in:", self.attackSpinBox)
        fades.addRow("Fade out:", self.releaseSpinBox)

        box = QtWidgets.QVBoxLayout()
        box.addWidget(heading)
        box.addLayout(meters)
        box.addSpacing(8)
        box.addLayout(fades)
        box.addStretch(1)

        master = QtWidgets.QFrame(self)
        master.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        master.setMaximumWidth(260)
        master.setLayout(box)
        return master

    def toggle_room_monitor(self, enabled: bool) -> None:
        """Start/stop the bedroom monitor-mic meter (the objective acoustic check)."""
        self.session.log_interaction(f"Cue room monitor {'on' if enabled else 'off'}")
        if enabled:
            device = require_device(
                self.session,
                "monitor_bedroom_noise",
                devices.INPUT,
                failure="Could not open the room monitor.",
                parent=self,
            )
            if device is None:
                self.monitorCheckBox.setChecked(False)
                return
            try:
                self.roomMeter.start(device)
            except Exception as exc:  # PortAudio errors, no device, busy, etc.
                self.session.show_error_popup(
                    "Could not open the room monitor.", str(exc), parent=self
                )
                self.monitorCheckBox.setChecked(False)
        else:
            self.roomMeter.stop()

    def _restart_room_monitor_if_active(self) -> None:
        """Re-open the room monitor on the current device if it's running."""
        if self.roomMeter.is_active():
            self.toggle_room_monitor(False)
            self.toggle_room_monitor(True)

    # ----- settings state ----------------------------------------------------

    def gather_state(self) -> dict:
        return {
            "cues": [
                {
                    "name": slot.nameEdit.text(),
                    "file": slot.file_path,
                    "volume": slot.volumeSpinBox.value(),
                    "loop": slot.loopButton.isChecked(),
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
        if (v := state.get("cue_attack")) is not None:
            restore_spin_value(self.attackSpinBox, v)
        if (v := state.get("cue_release")) is not None:
            restore_spin_value(self.releaseSpinBox, v)

    def _apply_cue(self, slot: CueSlot, cue: dict) -> None:
        if name := cue.get("name"):
            slot.nameEdit.setText(str(name))
        if (f := cue.get("file")) is not None:
            self.set_slot_file(slot, str(f))  # labels the button and decodes
        if (v := cue.get("volume")) is not None:
            restore_spin_value(slot.volumeSpinBox, v)  # fires the fader sync
        slot.loopButton.setChecked(bool(cue.get("loop", False)))

    def cleanup(self) -> None:
        self._cue_timer.stop()
        for out in self._outputs:
            out.stream.abort()
            out.stream.close()
        self._outputs = []
        self.roomMeter.stop()
