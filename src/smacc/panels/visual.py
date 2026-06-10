"""Visual cue window: a multi-slot light board (color/pattern/length per slot).

The visual sibling of the audio cue board (#86/#87): each slot is one light cue —
a color at a brightness, shown steady or pulsed/flashed at a rate in Hz — with its
own length and loop flag, so a protocol that uses several lights (e.g. cue vs.
sham) can keep them ready and fire any one with a click. Playback is one-at-a-time
on the device the visual_out route resolves to — a BlinkStick over USB, or a
Philips Hue light/group over the bridge (#53) — shaped by a shared brightness
fade-in/out and driven by a ~30 Hz QTimer ticking the pure
:class:`smacc.lights.LightEngine`, so the rest of the GUI stays live throughout.
Device writes run on a :class:`smacc.lights.FrameWriter` thread (a Hue write is an
HTTP round-trip), and flash is refused on backends that can't honor it.
Start/stop are marked with the ``VisualStarted``/``VisualStopped`` registry events
(detail: the slot name), every stop path turns the light off (including app quit),
and a "sending" swatch mirrors the exact frame on the device — the visual analog
of the audio board's sending meter. Slots can be added and removed on the fly;
one is always required.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from functools import partial

from PyQt6 import QtCore, QtGui, QtWidgets

from .. import hue, lights
from ..session import SmaccSession
from .base import (
    ModalityWindow,
    describe_target,
    make_section_title,
    restore_spin_value,
)

# One light cue is always required; the cap is lower than the audio board's 20
# because rows are wide and a light protocol rarely needs more than a few variants.
MIN_LIGHT_SLOTS = 1
MAX_LIGHT_SLOTS = 10
# Above this pattern rate the panel shows the photosensitivity/reliability warning.
RATE_WARN_HZ = 10.0
# UI ceiling: beyond ~20 Hz a square wave needs more USB updates than the stick's
# HID timing reliably delivers, so higher settings would just be sold, not shown.
RATE_MAX_HZ = 20.0

_PATTERN_LABELS = (
    (lights.STEADY, "Steady"),
    (lights.PULSE, "Pulse"),
    (lights.FLASH, "Flash"),
)


def _swatch_pixmap(rgb: lights.RGB, size: int = 22) -> QtGui.QPixmap:
    """A small color square with a gray border (so black/white still read)."""
    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(QtGui.QColor(*rgb))
    painter = QtGui.QPainter(pixmap)
    painter.setPen(QtGui.QColor("#808080"))
    painter.drawRect(0, 0, size - 1, size - 1)
    painter.end()
    return pixmap


@dataclass
class LightSlot:
    """One light cue: its color plus the row of widgets controlling it.

    Signal handlers bind to the slot *object*, never a row index, so adding or
    removing rows can't misroute another slot's controls (the audio board's
    CueSlot approach). ``rgb`` is the cue color; everything else lives in the
    widgets and is read at play time.
    """

    nameEdit: QtWidgets.QLineEdit
    colorButton: QtWidgets.QPushButton
    brightnessSpinBox: QtWidgets.QDoubleSpinBox
    patternCombo: QtWidgets.QComboBox
    rateSpinBox: QtWidgets.QDoubleSpinBox
    lengthSpinBox: QtWidgets.QDoubleSpinBox
    loopCheckBox: QtWidgets.QCheckBox
    playButton: QtWidgets.QPushButton
    stopButton: QtWidgets.QPushButton
    removeButton: QtWidgets.QPushButton
    rgb: lights.RGB = field(default=(255, 0, 0))


class VisualWindow(ModalityWindow):
    """Multi-slot light board with a shared device + fade and per-slot play/stop."""

    TITLE = "Visual cue"
    # ~30 Hz frames: ample headroom for the pulse/flash patterns at allowed rates.
    TICK_MS = 33

    def __init__(self, session: SmaccSession, parent: QtWidgets.QWidget | None = None):
        super().__init__(session, parent)
        # Shared brightness fade (attack/release) durations in seconds; 0 == instant.
        self.visual_attack_s = 0.0
        self.visual_release_s = 0.0
        # Backend resolved from the visual_out role; the one a playing cue is bound
        # to is held separately, so re-routing applies from the next Play (like an
        # audio cue keeping the stream it opened).
        self._backend: lights.LightBackend | None = None
        self._active_backend: lights.LightBackend | None = None
        self._active_slot: LightSlot | None = None
        # Frames go to the device through a writer thread: a Hue write is an HTTP
        # round-trip (~100 ms), far too slow for the GUI thread at the tick rate.
        self._writer: lights.FrameWriter | None = None
        self._engine = lights.LightEngine()
        self._clock = time.monotonic  # injectable for deterministic tests
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(self.TICK_MS)
        self._timer.timeout.connect(self._tick)
        # Populated after the central widget exists so _rebuild_grid has its
        # header labels and add button to work with.
        self.slots: list[LightSlot] = []
        self.setCentralWidget(self._build())
        self._add_initial_slot()

    # ----- construction ------------------------------------------------------

    def _make_slot(self, name: str) -> LightSlot:
        """Build one fully-wired light slot and append it to ``self.slots``."""
        nameEdit = QtWidgets.QLineEdit(name, self)
        nameEdit.setMaximumWidth(90)
        colorButton = QtWidgets.QPushButton(self)
        colorButton.setMaximumWidth(36)
        colorButton.setStatusTip("Pick this cue's color.")
        colorButton.setToolTip("Pick this cue's color")
        brightnessSpinBox = QtWidgets.QDoubleSpinBox(self)
        brightnessSpinBox.setRange(0, 1)
        brightnessSpinBox.setSingleStep(0.01)
        brightnessSpinBox.setMaximumWidth(70)
        brightnessSpinBox.setStatusTip("Brightness scale for this cue (0–1).")
        patternCombo = QtWidgets.QComboBox(self)
        for key, label in _PATTERN_LABELS:
            patternCombo.addItem(label, key)
        patternCombo.setStatusTip(
            "How the light behaves while on: constant, a smooth pulse, or an "
            "on/off flash at the chosen rate."
        )
        rateSpinBox = QtWidgets.QDoubleSpinBox(self)
        rateSpinBox.setRange(0.1, RATE_MAX_HZ)
        rateSpinBox.setSingleStep(0.1)
        rateSpinBox.setSuffix(" Hz")
        rateSpinBox.setMaximumWidth(85)
        rateSpinBox.setStatusTip(
            f"Pulse/flash rate. Above {RATE_WARN_HZ:.0f} Hz: photosensitivity "
            "risk, and USB timing degrades — see the docs."
        )
        rateSpinBox.setEnabled(False)  # steady by default; pattern enables it
        lengthSpinBox = QtWidgets.QDoubleSpinBox(self)
        lengthSpinBox.setRange(0, 600)
        lengthSpinBox.setSingleStep(0.1)
        lengthSpinBox.setSuffix(" s")
        lengthSpinBox.setStatusTip(
            "How long the light stays on, in seconds (ignored while Loop is on)."
        )
        loopCheckBox = QtWidgets.QCheckBox(self)
        loopCheckBox.setStatusTip("Repeat this cue until stopped.")
        loopCheckBox.setToolTip("Loop until stopped")
        playButton = QtWidgets.QPushButton("Play", self)
        stopButton = QtWidgets.QPushButton("Stop", self)
        removeButton = QtWidgets.QPushButton("✕", self)  # ✕
        removeButton.setMaximumWidth(28)
        removeButton.setStatusTip("Remove this cue.")
        removeButton.setToolTip("Remove this cue")
        slot = LightSlot(
            nameEdit,
            colorButton,
            brightnessSpinBox,
            patternCombo,
            rateSpinBox,
            lengthSpinBox,
            loopCheckBox,
            playButton,
            stopButton,
            removeButton,
        )
        self.slots.append(slot)  # append before wiring so handlers can resolve it
        colorButton.clicked.connect(partial(self.pick_slot_color, slot))
        brightnessSpinBox.valueChanged.connect(
            partial(self.update_slot_brightness, slot)
        )
        patternCombo.currentIndexChanged.connect(
            partial(self.update_slot_pattern, slot)
        )
        rateSpinBox.valueChanged.connect(partial(self.update_slot_rate, slot))
        loopCheckBox.toggled.connect(partial(self.update_slot_loop, slot))
        playButton.clicked.connect(partial(self.play_slot, slot))
        stopButton.clicked.connect(partial(self.stop_slot, slot))
        removeButton.clicked.connect(partial(self.remove_slot, slot))
        brightnessSpinBox.setValue(1.0)  # fires update_slot_brightness
        rateSpinBox.setValue(1.0)
        lengthSpinBox.setValue(1.0)
        colorButton.setIcon(QtGui.QIcon(_swatch_pixmap(slot.rgb)))
        colorButton.setIconSize(QtCore.QSize(22, 22))
        return slot

    def _add_initial_slot(self) -> None:
        """Create the single required slot (red/steady: playable out of the box)."""
        self._make_slot("Light 1")
        self._rebuild_grid()

    def _build(self) -> QtWidgets.QWidget:
        # Shared device (chosen in the Devices window) + fade controls.
        self.deviceLabel = QtWidgets.QLabel(self)
        self.deviceLabel.setStatusTip(
            "Set in the Devices window (BlinkStick or Philips Hue role)."
        )
        self.refresh_device_indicator()

        attackSpinBox = QtWidgets.QDoubleSpinBox(self)
        attackSpinBox.setStatusTip(
            "Brightness fade-in time for the cue, in seconds (0 = instant)."
        )
        attackSpinBox.setRange(0, 60)
        attackSpinBox.setSingleStep(0.1)
        attackSpinBox.setSuffix(" seconds")
        attackSpinBox.valueChanged.connect(self.update_visual_attack)
        attackSpinBox.setValue(0.0)
        self.attackSpinBox = attackSpinBox

        releaseSpinBox = QtWidgets.QDoubleSpinBox(self)
        releaseSpinBox.setStatusTip(
            "Brightness fade-out time when stopping the cue, in seconds (0 = instant)."
        )
        releaseSpinBox.setRange(0, 60)
        releaseSpinBox.setSingleStep(0.1)
        releaseSpinBox.setSuffix(" seconds")
        releaseSpinBox.valueChanged.connect(self.update_visual_release)
        releaseSpinBox.setValue(0.0)
        self.releaseSpinBox = releaseSpinBox

        header = QtWidgets.QFormLayout()
        header.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        header.addRow("Device:", self.deviceLabel)
        header.addRow("Fade in:", attackSpinBox)
        header.addRow("Fade out:", releaseSpinBox)

        # "Now lit" indicator on top of the slot table (mixing-board style).
        self.nowLitLabel = QtWidgets.QLabel(self)
        self.nowLitLabel.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._set_now_off()

        # Light table: a persistent header row, then one rebuildable row per slot,
        # then an "add" row — the audio board's reparent-don't-delete grid.
        self._grid = QtWidgets.QGridLayout()
        self._header_labels = [
            self._make_header_label(title)
            for title in (
                "Name",
                "Color",
                "Bright",
                "Pattern",
                "Rate",
                "Length",
                "Loop",
                "",
                "",
                "",
            )
        ]
        self._addButton = QtWidgets.QPushButton("+ Add cue", self)
        self._addButton.setStatusTip(
            f"Add another light cue (up to {MAX_LIGHT_SLOTS})."
        )
        self._addButton.setToolTip("Add another light cue")
        self._addButton.clicked.connect(self.add_slot)

        # Shown whenever any slot's pattern runs faster than RATE_WARN_HZ.
        self.rateWarningLabel = QtWidgets.QLabel(
            f"⚠ Rates above {RATE_WARN_HZ:.0f} Hz carry a photosensitivity "
            "(epilepsy) risk, and USB timing gets unreliable — see the docs.",
            self,
        )
        self.rateWarningLabel.setWordWrap(True)
        self.rateWarningLabel.setVisible(False)

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(make_section_title("Visual cue"))
        layout.addLayout(header)
        layout.addWidget(self.nowLitLabel)
        layout.addLayout(self._grid)
        layout.addWidget(self.rateWarningLabel)
        layout.addSpacing(8)
        layout.addLayout(self._build_monitoring())
        layout.addStretch(1)
        central = QtWidgets.QWidget()
        central.setLayout(layout)
        return central

    def _make_header_label(self, text: str) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel(text, self)
        label.setStyleSheet("font-weight: bold;")
        return label

    def _build_monitoring(self) -> QtWidgets.QLayout:
        """The sending swatch: the exact frame on the device right now.

        Like the audio board's "Sending" meter (#37), it confirms emission — that
        SMACC is driving the light, and with what color — not that the bedroom
        light itself lit (a BlinkStick has no return channel to check that).
        """
        heading = QtWidgets.QLabel("Monitoring", self)
        heading.setStyleSheet("font-weight: bold;")
        self.sendingSwatch = QtWidgets.QLabel(self)
        self.sendingSwatch.setStatusTip(
            "The exact color SMACC is sending to the light right now — confirms "
            "emission, not that the bedroom light actually lit."
        )
        self._set_swatch((0, 0, 0))
        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        form.addRow("Sending:", self.sendingSwatch)
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(heading)
        layout.addLayout(form)
        return layout

    def _rebuild_grid(self) -> None:
        """Re-lay the light table: header row, one row per slot, then the add row.

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
            self._grid.addWidget(slot.colorButton, row, 1)
            self._grid.addWidget(slot.brightnessSpinBox, row, 2)
            self._grid.addWidget(slot.patternCombo, row, 3)
            self._grid.addWidget(slot.rateSpinBox, row, 4)
            self._grid.addWidget(slot.lengthSpinBox, row, 5)
            self._grid.addWidget(slot.loopCheckBox, row, 6)
            self._grid.addWidget(slot.playButton, row, 7)
            self._grid.addWidget(slot.stopButton, row, 8)
            self._grid.addWidget(slot.removeButton, row, 9)
            # The lone required slot can't be removed: keep the button in place (so
            # the column doesn't jump) but disabled.
            slot.removeButton.setEnabled(len(self.slots) > MIN_LIGHT_SLOTS)
        self._grid.addWidget(self._addButton, len(self.slots) + 1, 0, 1, 2)
        self._addButton.setEnabled(len(self.slots) < MAX_LIGHT_SLOTS)
        self._grid.setColumnStretch(0, 1)

    # ----- add / remove slots ------------------------------------------------

    def add_slot(self) -> None:
        """Append a new light slot, up to the cap."""
        if len(self.slots) >= MAX_LIGHT_SLOTS:
            return
        slot = self._make_slot(f"Light {len(self.slots) + 1}")
        self._rebuild_grid()
        self.adjustSize()
        self.session.log_interaction(f"Added light cue '{slot.nameEdit.text()}'")

    def remove_slot(self, slot: LightSlot) -> None:
        """Remove a light slot (never the last one), stopping it first."""
        if len(self.slots) <= MIN_LIGHT_SLOTS or slot not in self.slots:
            return
        name = slot.nameEdit.text()
        self.slots.remove(slot)
        self._destroy_slot_widgets(slot)
        self._rebuild_grid()
        self._refresh_rate_warning()
        self.adjustSize()
        self.session.log_interaction(f"Removed light cue '{name}'")

    def _destroy_slot_widgets(self, slot: LightSlot) -> None:
        """Tear down a removed slot: darken it if lit, then free its widgets."""
        if self._active_slot is slot:
            self._finish(mark=False)  # off without a spurious marker
        for widget in (
            slot.nameEdit,
            slot.colorButton,
            slot.brightnessSpinBox,
            slot.patternCombo,
            slot.rateSpinBox,
            slot.lengthSpinBox,
            slot.loopCheckBox,
            slot.playButton,
            slot.stopButton,
            slot.removeButton,
        ):
            widget.hide()  # leave no orphan visible before deferred deletion
            widget.deleteLater()

    def _resize_slots(self, count: int) -> None:
        """Grow/shrink the slot list to ``count`` (clamped to ``1..MAX``)."""
        count = max(MIN_LIGHT_SLOTS, min(count, MAX_LIGHT_SLOTS))
        while len(self.slots) < count:
            self._make_slot(f"Light {len(self.slots) + 1}")
        while len(self.slots) > count:
            self._destroy_slot_widgets(self.slots.pop())
        self._rebuild_grid()

    # ----- shared device + fade ---------------------------------------------

    def refresh_device_indicator(self) -> None:
        """Resolve the light backend from the routed role (BlinkStick or Hue).

        A cue already lit keeps the backend it started with; the fresh resolution
        applies from the next Play.
        """
        role = self.session.devices.role_for("visual_out")
        binding = self.session.devices.device_for("visual_out")
        if role == "hue":
            self._backend = hue.resolve_backend(self.session.hue_config, binding)
        else:
            self._backend = lights.resolve_blinkstick(binding)
        self.deviceLabel.setText(describe_target(self.session, "visual_out"))

    def update_visual_attack(self, value: float) -> None:
        """Set the shared brightness fade-in (attack) time in seconds."""
        self.visual_attack_s = value
        self.session.log_interaction(f"Visual fade-in set to {value:.1f}s")

    def update_visual_release(self, value: float) -> None:
        """Set the shared brightness fade-out (release) time in seconds."""
        self.visual_release_s = value
        self.session.log_interaction(f"Visual fade-out set to {value:.1f}s")

    # ----- per-slot controls -------------------------------------------------

    def pick_slot_color(self, slot: LightSlot) -> None:
        # No device needed to choose a color (the settings editor has none).
        current = QtGui.QColor(*slot.rgb)
        color = QtWidgets.QColorDialog.getColor(current, self)
        if color.isValid():
            self._set_slot_color(slot, color.red(), color.green(), color.blue())

    def _set_slot_color(self, slot: LightSlot, r: int, g: int, b: int) -> None:
        """Set a slot's cue color and its button swatch (applies from next Play)."""
        slot.rgb = (r, g, b)
        slot.colorButton.setIcon(QtGui.QIcon(_swatch_pixmap(slot.rgb)))
        self.session.log_interaction(
            f"Light cue '{slot.nameEdit.text()}' color set to {_hexcode(slot.rgb)}"
        )

    def update_slot_brightness(
        self, slot: LightSlot, value: float | None = None
    ) -> None:
        """Set a slot's brightness (0-1) from its spinbox (live if it's lit)."""
        brightness = slot.brightnessSpinBox.value()
        if self._active_slot is slot:
            self._engine.brightness = brightness
        self.session.log_interaction(
            f"Light cue '{slot.nameEdit.text()}' brightness set to {brightness:.2f}",
            debug=True,
        )

    def update_slot_pattern(self, slot: LightSlot, index: int | None = None) -> None:
        """A slot's pattern changed: gate its rate control (applies next Play)."""
        pattern = slot.patternCombo.currentData()
        slot.rateSpinBox.setEnabled(pattern != lights.STEADY)
        self._refresh_rate_warning()
        self.session.log_interaction(
            f"Light cue '{slot.nameEdit.text()}' pattern set to {pattern}"
        )

    def update_slot_rate(self, slot: LightSlot, value: float | None = None) -> None:
        """A slot's pattern rate changed (applies next Play)."""
        self._refresh_rate_warning()
        self.session.log_interaction(
            f"Light cue '{slot.nameEdit.text()}' rate set to "
            f"{slot.rateSpinBox.value():.1f} Hz",
            debug=True,
        )

    def update_slot_loop(self, slot: LightSlot, enabled: bool | None = None) -> None:
        """Set a slot's loop flag from its checkbox (live if it's lit)."""
        looping = slot.loopCheckBox.isChecked()
        if self._active_slot is slot:
            self._engine.loop = looping
        self.session.log_interaction(
            f"Light cue '{slot.nameEdit.text()}' loop {'on' if looping else 'off'}"
        )

    def _refresh_rate_warning(self) -> None:
        """Show the photosensitivity note iff any patterned slot runs > the cutoff."""
        risky = any(
            slot.patternCombo.currentData() != lights.STEADY
            and slot.rateSpinBox.value() > RATE_WARN_HZ
            for slot in self.slots
        )
        self.rateWarningLabel.setVisible(risky)

    # ----- playback ------------------------------------------------------------

    def play_slot(self, slot: LightSlot) -> None:
        """Light one slot (stopping any other lit slot first) with fade-in.

        Re-playing the lit slot just restarts it (no stop marker), like the audio
        board re-playing its active slot.
        """
        if self._backend is None:
            self.session.show_error_popup(
                "Visual cue unavailable.",
                "No light is set. In the Devices window, bind a BlinkStick "
                "(or pair a Philips Hue) and route the visual cue to it.",
                parent=self,
            )
            return
        backend = self._backend
        # Refuse flash on a backend that can't honor it (the Hue bridge's rate
        # limits) rather than degrade the stimulus silently — and refuse before
        # touching whatever cue is currently lit.
        if slot.patternCombo.currentData() == lights.FLASH and not getattr(
            backend, "supports_flash", True
        ):
            self.session.show_error_popup(
                "Flash isn't available on the Philips Hue.",
                "The bridge rate-limits commands, far below a square wave. Use "
                "pulse or steady, or route the visual cue to a BlinkStick.",
                parent=self,
            )
            return
        if self._active_slot is not None:
            self._finish(mark=self._active_slot is not slot)
        now = self._clock()
        self._engine.start(
            now,
            slot.rgb,
            brightness=slot.brightnessSpinBox.value(),
            duration_s=slot.lengthSpinBox.value(),
            loop=slot.loopCheckBox.isChecked(),
            pattern=slot.patternCombo.currentData(),
            rate_hz=slot.rateSpinBox.value(),
            attack_s=self.visual_attack_s,
            release_s=self.visual_release_s,
        )
        first = self._engine.frame(now)
        try:
            backend.apply(first)
        except Exception as err:
            self._engine.stop(now)
            self.session.show_error_popup(
                "Could not light the visual cue.", str(err), parent=self
            )
            return
        self._active_backend = backend
        self._active_slot = slot
        # Later frames go through the writer thread; it skips duplicates (the
        # first frame seeds that filter) and always jumps to the newest frame, so
        # a slow backend lags a little but never queues stale light.
        self._writer = self._make_writer(backend, first)
        self._timer.start()
        self._set_now_lit(slot)
        self._set_swatch(first)
        # Marked after the first frame is on the device, so the marker trails the
        # photons by microseconds instead of leading them by up to a tick.
        self.session.emit_event("VisualStarted", detail=slot.nameEdit.text())

    def _make_writer(self, backend: lights.LightBackend, first: lights.RGB):
        """Build the cue's frame writer (a seam: tests inject a synchronous fake)."""
        return lights.FrameWriter(backend, applied=first)

    def stop_slot(self, slot: LightSlot) -> None:
        """Stop a slot (with fade-out) if it is the one currently lit."""
        if self._active_slot is not slot or not self._timer.isActive():
            return
        self._engine.stop(self._clock())
        if self._engine.ended:  # instant stop (no release fade)
            self._tick()  # finalize immediately: off + marker, not a tick later
        # Otherwise the release fade runs and _tick finalizes it when done.

    def _tick(self) -> None:
        """Timer slot: submit the current frame, finishing once the cue has ended."""
        now = self._clock()
        frame = self._engine.frame(now)
        if self._engine.ended:
            self._finish(mark=True)
            return
        writer = self._writer
        assert writer is not None  # created with the timer in play_slot
        if writer.error is not None:  # a device write failed on the writer thread
            error = writer.error
            self._finish(mark=True)  # the stimulus is over, whatever the light says
            self.session.show_error_popup(
                "Light write failed; visual cue stopped.", error, parent=self
            )
            return
        writer.submit(frame)
        self._set_swatch(frame)

    def _finish(self, mark: bool) -> None:
        """Stop the timer, force the light off (best effort), and mark the stop."""
        slot = self._active_slot
        self._timer.stop()
        if self._writer is not None:
            # Join the writer before the off, so a slow in-flight frame can't land
            # after it and leave the light stuck on.
            self._writer.stop()
            self._writer = None
        if self._active_backend is not None:
            try:
                self._active_backend.off()
            except Exception:
                pass  # unplugged mid-cue; nothing left to turn off
            self._active_backend = None
        self._active_slot = None
        self._set_now_off()
        self._set_swatch((0, 0, 0))
        if mark and slot is not None:
            self.session.emit_event("VisualStopped", detail=slot.nameEdit.text())

    def _set_now_lit(self, slot: LightSlot) -> None:
        name = slot.nameEdit.text()
        looping = slot.loopCheckBox.isChecked()
        self.nowLitLabel.setText(f"● {name} (looping)" if looping else f"● {name}")
        self.nowLitLabel.setStyleSheet("color: red; font-weight: bold;")

    def _set_now_off(self) -> None:
        self.nowLitLabel.setText("■ off")  # ■
        self.nowLitLabel.setStyleSheet("")

    def _set_swatch(self, rgb: lights.RGB) -> None:
        self.sendingSwatch.setPixmap(_swatch_pixmap(rgb))

    # ----- settings state ----------------------------------------------------

    def gather_state(self) -> dict:
        return {
            "visual_cues": [
                {
                    "name": slot.nameEdit.text(),
                    "color": _hexcode(slot.rgb),
                    "brightness": slot.brightnessSpinBox.value(),
                    "pattern": slot.patternCombo.currentData(),
                    "rate": slot.rateSpinBox.value(),
                    "length": slot.lengthSpinBox.value(),
                    "loop": slot.loopCheckBox.isChecked(),
                }
                for slot in self.slots
            ],
            "visual_attack": self.attackSpinBox.value(),
            "visual_release": self.releaseSpinBox.value(),
        }

    def apply_state(self, state: dict) -> None:
        # A v1 file's blink_color/blink_length arrive here already migrated into
        # a one-slot visual_cues list (see smacc.settings).
        cues = state.get("visual_cues")
        if isinstance(cues, list) and cues:
            self._resize_slots(len(cues))
            for slot, cue in zip(self.slots, cues, strict=False):
                if isinstance(cue, dict):
                    self._apply_cue(slot, cue)
        if (v := state.get("visual_attack")) is not None:
            restore_spin_value(self.attackSpinBox, v)
        if (v := state.get("visual_release")) is not None:
            restore_spin_value(self.releaseSpinBox, v)

    def _apply_cue(self, slot: LightSlot, cue: dict) -> None:
        if name := cue.get("name"):
            slot.nameEdit.setText(str(name))
        if (c := cue.get("color")) is not None:
            qcolor = QtGui.QColor(str(c))
            if qcolor.isValid():
                self._set_slot_color(slot, qcolor.red(), qcolor.green(), qcolor.blue())
        if (v := cue.get("brightness")) is not None:
            restore_spin_value(slot.brightnessSpinBox, v)
        pattern = cue.get("pattern")
        if pattern in lights.PATTERNS:
            slot.patternCombo.setCurrentIndex(slot.patternCombo.findData(pattern))
        if (v := cue.get("rate")) is not None:
            restore_spin_value(slot.rateSpinBox, v)
        if (v := cue.get("length")) is not None:
            restore_spin_value(slot.lengthSpinBox, v)
        slot.loopCheckBox.setChecked(bool(cue.get("loop", False)))

    def cleanup(self) -> None:
        """Stop the cue timer and leave the light off (no marker; app is quitting)."""
        self._finish(mark=False)


def _hexcode(rgb: lights.RGB) -> str:
    r, g, b = rgb
    return f"#{r:02x}{g:02x}{b:02x}"
