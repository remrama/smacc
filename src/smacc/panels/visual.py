"""Visual stimulation window driving a BlinkStick LED device."""

from __future__ import annotations

from blinkstick import blinkstick
from PyQt5 import QtCore, QtGui, QtWidgets

from ..session import SmaccSession
from .base import (
    ModalityWindow,
    current_device_key,
    make_section_title,
    select_saved_device,
)


class VisualWindow(ModalityWindow):
    """BlinkStick color/length picker and trigger."""

    TITLE = "Visual stimulation"

    def __init__(self, session: SmaccSession, parent: QtWidgets.QWidget | None = None):
        super().__init__(session, parent)
        self.bstick = None  # selected device; None until one is found/selected
        self.bstick_blink_freq = 1.0
        self.set_blink_color(0, 0, 0)  # default color: black/off
        self.setCentralWidget(self._build())

    def _build(self) -> QtWidgets.QWidget:
        # Visual device picker: QComboBox signal --> update device slot
        available_blinksticks_dropdown = QtWidgets.QComboBox()
        available_blinksticks_dropdown.setStatusTip("Select visual stimulation device")
        available_blinksticks_dropdown.currentTextChanged.connect(
            self.set_new_blinkstick
        )
        self.available_blinksticks_dropdown = available_blinksticks_dropdown
        self.refresh_available_blinksticks()

        # Visual play button: QPushButton signal --> visual_stim slot
        blinkButton = QtWidgets.QPushButton("Play BlinkStick", self)
        blinkButton.setStatusTip("Present visual stimulus.")
        blinkButton.clicked.connect(self.stimulate_visual)

        # Visual color picker: QPushButton signal --> QColorPicker slot
        colorpickerButton = QtWidgets.QPushButton("Select color", self)
        colorpickerButton.setStatusTip("Pick the visual stimulus color.")
        colorpickerButton.clicked.connect(self.pick_color)
        self.colorpickerButton = colorpickerButton
        self._update_color_swatch()  # show the current color from the start

        # Visual frequency selector: QDoubleSpinBox signal --> update params slot
        freqSpinBox = QtWidgets.QDoubleSpinBox(self)
        freqSpinBox.setStatusTip(
            "Pick light stimulation length (how long the light will stay on in seconds)."
        )
        freqSpinBox.setMinimum(0)
        freqSpinBox.setMaximum(60)
        freqSpinBox.setSuffix(" seconds")
        freqSpinBox.setSingleStep(0.1)
        freqSpinBox.valueChanged.connect(self.handle_freq_change)
        freqSpinBox.setValue(self.bstick_blink_freq)
        self.freqSpinBox = freqSpinBox

        layout = QtWidgets.QFormLayout()
        layout.setLabelAlignment(QtCore.Qt.AlignRight)
        layout.addRow(make_section_title("Visual stimulation"))
        layout.addRow("Device:", available_blinksticks_dropdown)
        layout.addRow("Color:", colorpickerButton)
        layout.addRow("Length:", freqSpinBox)
        layout.addRow(blinkButton)
        central = QtWidgets.QWidget()
        central.setLayout(layout)
        return central

    def set_new_blinkstick(self, text):
        """Select a BlinkStick from the dropdown (empty = no device).

        The serial number is carried as the item's data, so selection is robust to
        the display-text format (no string parsing).
        """
        serial_number = self.available_blinksticks_dropdown.currentData()
        if not serial_number:  # dropdown cleared / no device selected
            self.bstick = None
            return
        self.bstick = blinkstick.find_by_serial(serial_number)

    def refresh_available_blinksticks(self):
        """Populate the dropdown with connected BlinkSticks (silent if none).

        The error is raised only when visual stimulation is used (see
        _ensure_blinkstick), so non-BlinkStick users aren't nagged at startup.
        """
        self.available_blinksticks_dropdown.clear()
        devices = blinkstick.find_all()
        for d in devices:
            product_name = d.device.product_name
            serial_number = d.device.serial_number
            version_number = d.device.version_number
            device_str = (
                f"{product_name} v{version_number} (Serial No. {serial_number})"
            )
            self.available_blinksticks_dropdown.addItem(device_str, serial_number)
        if devices:
            self.available_blinksticks_dropdown.setCurrentIndex(0)

    def refresh_devices(self) -> None:
        """Rescan for connected BlinkSticks, keeping the selection if still present.

        BlinkStick enumeration is a live USB scan (no PortAudio caching), so this
        picks up a device plugged in after launch on its own.
        """
        combo = self.available_blinksticks_dropdown
        previous = current_device_key(combo)
        self.refresh_available_blinksticks()
        select_saved_device(combo, previous)

    def set_blink_color(self, r: int, g: int, b: int) -> None:
        """Set the BlinkStick color from 0-255 RGB components.

        Stores the hex code (for settings save/load) and precomputes the LED data.
        blinkstick.set_led_data expects G/R swapped: 3 values per LED, 32 LEDs.
        """
        self.bstick_rgb = (r, g, b, 255)
        self.bstick_hexcode = f"#{r:02x}{g:02x}{b:02x}"
        self.bstick_led_data = [g, r, b] * 32
        # Keep the color picker's swatch in sync (once the button exists).
        if hasattr(self, "colorpickerButton"):
            self._update_color_swatch()
        self.session.log_interaction(f"Blink color set to {self.bstick_hexcode}")

    def _update_color_swatch(self) -> None:
        """Show the currently selected blink color on the color picker button."""
        size = 22
        pixmap = QtGui.QPixmap(size, size)
        pixmap.fill(QtGui.QColor(*self.bstick_rgb))
        painter = QtGui.QPainter(pixmap)
        painter.setPen(QtGui.QColor("#808080"))  # border so black/white read
        painter.drawRect(0, 0, size - 1, size - 1)
        painter.end()
        self.colorpickerButton.setIcon(QtGui.QIcon(pixmap))
        self.colorpickerButton.setIconSize(QtCore.QSize(size, size))

    def _ensure_blinkstick(self) -> bool:
        """Return True if a BlinkStick device is selected, else show one error popup."""
        if self.bstick is not None:
            return True
        self.session.show_error_popup(
            "Visual stimulation unavailable.",
            "No BlinkStick device was found. Connect one and restart SMACC.",
            parent=self,
        )
        return False

    def pick_color(self):
        if not self._ensure_blinkstick():
            return
        color = QtWidgets.QColorDialog.getColor(QtGui.QColor(self.bstick_hexcode), self)
        if color.isValid():
            r, g, b, _ = color.getRgb()
            self.set_blink_color(r, g, b)

    def handle_freq_change(self, freq: float) -> None:
        """Takes the blink length in seconds from the spinbox."""
        self.bstick_blink_freq = freq
        self.session.log_interaction(f"Blink length set to {freq:.1f}s")

    def stimulate_visual(self):
        if not self._ensure_blinkstick():
            return
        from time import sleep

        black = [0, 0, 0] * 32
        freq = self.bstick_blink_freq
        self.session.emit_event("VisualStarted")
        self.bstick.set_led_data(channel=0, data=self.bstick_led_data)
        sleep(freq)
        self.bstick.set_led_data(channel=0, data=black)

    def gather_state(self) -> dict:
        return {
            "blink_device": current_device_key(self.available_blinksticks_dropdown),
            "blink_color": self.bstick_hexcode,
            "blink_length": self.bstick_blink_freq,
        }

    def apply_state(self, state: dict) -> None:
        saved = state.get("blink_device")
        if saved and not select_saved_device(
            self.available_blinksticks_dropdown, saved
        ):
            self.session.note_missing_device("BlinkStick", saved)
        if hexcode := state.get("blink_color"):
            qcolor = QtGui.QColor(hexcode)
            if qcolor.isValid():
                self.set_blink_color(qcolor.red(), qcolor.green(), qcolor.blue())
        if (length := state.get("blink_length")) is not None:
            self.freqSpinBox.setValue(float(length))
