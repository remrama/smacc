"""Visual stimulation window driving a BlinkStick LED device.

Playback is non-blocking: a ~30 Hz QTimer ticks the pure
:class:`smacc.lights.LightEngine` and pushes each frame to the resolved backend,
so the rest of the GUI (markers, intercom, Stop) stays live during a cue — the
old implementation slept on the GUI thread for the whole blink. Start and stop
are marked with the ``VisualStarted``/``VisualStopped`` registry events, every
stop path turns the light off (including app quit), and the color can be picked
with no device plugged in (the settings editor runs hardware-free).
"""

from __future__ import annotations

import time

from PyQt6 import QtCore, QtGui, QtWidgets

from .. import lights
from ..session import SmaccSession
from .base import ModalityWindow, describe_target, make_section_title


class VisualWindow(ModalityWindow):
    """BlinkStick color/length picker with non-blocking play/stop."""

    TITLE = "Visual stimulation"
    # ~30 Hz frames: ample for the steady cue here and smooth enough for the
    # pulse/flash patterns the cue board adds (#86/#87).
    TICK_MS = 33

    def __init__(self, session: SmaccSession, parent: QtWidgets.QWidget | None = None):
        super().__init__(session, parent)
        # Backend resolved from the visual_out role; the one a playing cue is
        # bound to is held separately, so re-routing applies from the next Play
        # (like an audio cue keeping the stream it opened).
        self._backend: lights.LightBackend | None = None
        self._active_backend: lights.LightBackend | None = None
        self._engine = lights.LightEngine()
        self._clock = time.monotonic  # injectable for deterministic tests
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(self.TICK_MS)
        self._timer.timeout.connect(self._tick)
        self.blink_length_s = 1.0
        # Default to red: visible out of the box (the old black default made Play
        # an invisible no-op) and the gentlest color on a dark-adapted sleeper.
        self.set_blink_color(255, 0, 0)
        self.setCentralWidget(self._build())
        # The panel's contents are narrow, so without a floor the window opens
        # too thin to show its "Visual stimulation" titlebar text in full.
        self.setMinimumWidth(340)

    def _build(self) -> QtWidgets.QWidget:
        # The BlinkStick is chosen in the Devices window; show where it resolves.
        self.deviceLabel = QtWidgets.QLabel(self)
        self.deviceLabel.setStatusTip(
            "Set in the Devices window (Bedroom lights role)."
        )
        self.refresh_device_indicator()

        # Visual color picker: QPushButton signal --> QColorPicker slot
        colorpickerButton = QtWidgets.QPushButton("Select color", self)
        colorpickerButton.setStatusTip("Pick the visual stimulus color.")
        colorpickerButton.clicked.connect(self.pick_color)
        self.colorpickerButton = colorpickerButton
        self._update_color_swatch()  # show the current color from the start

        # Cue length selector: QDoubleSpinBox signal --> update params slot
        lengthSpinBox = QtWidgets.QDoubleSpinBox(self)
        lengthSpinBox.setStatusTip(
            "Pick light stimulation length (how long the light will stay on in seconds)."
        )
        lengthSpinBox.setMinimum(0)
        lengthSpinBox.setMaximum(60)
        lengthSpinBox.setSuffix(" seconds")
        lengthSpinBox.setSingleStep(0.1)
        lengthSpinBox.valueChanged.connect(self.handle_length_change)
        lengthSpinBox.setValue(self.blink_length_s)
        self.lengthSpinBox = lengthSpinBox

        playButton = QtWidgets.QPushButton("Play", self)
        playButton.setStatusTip("Present the visual stimulus.")
        playButton.clicked.connect(self.play_cue)
        stopButton = QtWidgets.QPushButton("Stop", self)
        stopButton.setStatusTip("Turn the light off before its length runs out.")
        stopButton.clicked.connect(self.stop_cue)
        buttonRow = QtWidgets.QHBoxLayout()
        buttonRow.addWidget(playButton)
        buttonRow.addWidget(stopButton)

        # Lit indicator: the operator can't see the bedroom from the control room.
        self.stateLabel = QtWidgets.QLabel(self)
        self.stateLabel.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._set_state_off()

        layout = QtWidgets.QFormLayout()
        layout.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        layout.addRow(make_section_title("Visual stimulation"))
        layout.addRow("Device:", self.deviceLabel)
        layout.addRow("Color:", self.colorpickerButton)
        layout.addRow("Length:", lengthSpinBox)
        layout.addRow(buttonRow)
        layout.addRow(self.stateLabel)
        central = QtWidgets.QWidget()
        central.setLayout(layout)
        return central

    def refresh_device_indicator(self) -> None:
        """Resolve the BlinkStick from its role and show where the cue routes.

        A cue already playing keeps the backend it started with; the fresh
        resolution applies from the next Play.
        """
        serial = self.session.devices.device_for("visual_out")
        self._backend = lights.resolve_blinkstick(serial)
        self.deviceLabel.setText(describe_target(self.session, "visual_out"))

    # ----- color + length ------------------------------------------------------

    def set_blink_color(self, r: int, g: int, b: int) -> None:
        """Set the cue color from 0-255 RGB components (hex kept for save/load)."""
        self.blink_rgb: lights.RGB = (r, g, b)
        self.blink_hexcode = f"#{r:02x}{g:02x}{b:02x}"
        # Keep the color picker's swatch in sync (once the button exists).
        if hasattr(self, "colorpickerButton"):
            self._update_color_swatch()
        self.session.log_interaction(f"Blink color set to {self.blink_hexcode}")

    def _update_color_swatch(self) -> None:
        """Show the currently selected blink color on the color picker button."""
        size = 22
        pixmap = QtGui.QPixmap(size, size)
        pixmap.fill(QtGui.QColor(*self.blink_rgb))
        painter = QtGui.QPainter(pixmap)
        painter.setPen(QtGui.QColor("#808080"))  # border so black/white read
        painter.drawRect(0, 0, size - 1, size - 1)
        painter.end()
        self.colorpickerButton.setIcon(QtGui.QIcon(pixmap))
        self.colorpickerButton.setIconSize(QtCore.QSize(size, size))

    def pick_color(self) -> None:
        # No device needed to choose a color (the settings editor has none).
        color = QtWidgets.QColorDialog.getColor(QtGui.QColor(self.blink_hexcode), self)
        if color.isValid():
            r, g, b, _ = color.getRgb()
            self.set_blink_color(r, g, b)

    def handle_length_change(self, length: float) -> None:
        """Takes the blink length in seconds from the spinbox."""
        self.blink_length_s = length
        self.session.log_interaction(f"Blink length set to {length:.1f}s")

    # ----- playback ------------------------------------------------------------

    def play_cue(self) -> None:
        """Light the cue (non-blocking; re-playing while lit just restarts it)."""
        if self._backend is None:
            self.session.show_error_popup(
                "Visual stimulation unavailable.",
                "No BlinkStick is set. Bind one to the Bedroom lights role "
                "in the Devices window.",
                parent=self,
            )
            return
        backend = self._backend
        now = self._clock()
        self._engine.start(now, self.blink_rgb, duration_s=self.blink_length_s)
        try:
            backend.apply(self._engine.frame(now))
        except Exception as err:
            self._engine.stop(now)
            self.session.show_error_popup(
                "Could not light the BlinkStick.", str(err), parent=self
            )
            return
        self._active_backend = backend
        self._timer.start()
        self._set_state_on()
        # Marked after the first frame is on the device, so the marker trails the
        # photons by microseconds instead of leading them by up to a tick.
        self.session.emit_event("VisualStarted")

    def stop_cue(self) -> None:
        """Turn the cue off now (instant; the release fade arrives with #86)."""
        if not self._timer.isActive():
            return
        self._engine.stop(self._clock())
        self._tick()  # finalize immediately: off + marker, not a tick later

    def _tick(self) -> None:
        """Timer slot: push the current frame, finishing once the cue has ended."""
        now = self._clock()
        frame = self._engine.frame(now)
        if self._engine.ended:
            self._finish(mark=True)
            return
        assert self._active_backend is not None  # set with the timer in play_cue
        try:
            self._active_backend.apply(frame)
        except Exception as err:
            self._finish(mark=True)  # the stimulus is over, whatever the LEDs say
            self.session.show_error_popup(
                "BlinkStick write failed; visual cue stopped.", str(err), parent=self
            )

    def _finish(self, mark: bool) -> None:
        """Stop the timer, force the light off (best effort), and mark the stop."""
        self._timer.stop()
        if self._active_backend is not None:
            try:
                self._active_backend.off()
            except Exception:
                pass  # unplugged mid-cue; nothing left to turn off
            self._active_backend = None
        self._set_state_off()
        if mark:
            self.session.emit_event("VisualStopped")

    def _set_state_on(self) -> None:
        self.stateLabel.setText("● lit")
        self.stateLabel.setStyleSheet("color: red; font-weight: bold;")

    def _set_state_off(self) -> None:
        self.stateLabel.setText("■ off")
        self.stateLabel.setStyleSheet("")

    # ----- settings state --------------------------------------------------------

    def gather_state(self) -> dict:
        return {
            "blink_color": self.blink_hexcode,
            "blink_length": self.blink_length_s,
        }

    def apply_state(self, state: dict) -> None:
        if hexcode := state.get("blink_color"):
            qcolor = QtGui.QColor(hexcode)
            if qcolor.isValid():
                self.set_blink_color(qcolor.red(), qcolor.green(), qcolor.blue())
        if (length := state.get("blink_length")) is not None:
            self.lengthSpinBox.setValue(float(length))

    def cleanup(self) -> None:
        """Stop the cue timer and leave the light off (no marker; app is quitting)."""
        self._finish(mark=False)
