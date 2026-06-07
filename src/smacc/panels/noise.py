"""Noise machine window: stream continuous colored noise to an output device."""

from __future__ import annotations

from collections.abc import Callable

import sounddevice as sd
from PyQt5 import QtCore, QtGui, QtWidgets

from .. import utils
from ..session import SmaccSession
from .base import ModalityWindow, make_section_title


class NoiseWindow(ModalityWindow):
    """Continuous colored-noise generator with its own output stream."""

    TITLE = "Noise machine"

    def __init__(self, session: SmaccSession, parent: QtWidgets.QWidget | None = None):
        super().__init__(session, parent)
        self.noise_stream: sd.OutputStream | None = None
        self.noise_stream_volume = 0.2
        self.noiseplayer_device = ""
        self.setCentralWidget(self._build())

    def _build(self) -> QtWidgets.QWidget:
        # "Now playing" indicator on top (mixing-board style).
        self.noiseStatusLabel = QtWidgets.QLabel("■ stopped", self)
        self.noiseStatusLabel.setAlignment(QtCore.Qt.AlignCenter)

        # Noise device picker: QComboBox signal --> update device slot
        available_noisespeakers_dropdown = QtWidgets.QComboBox()
        available_noisespeakers_dropdown.setStatusTip("Select speakers for noise")
        available_noisespeakers_dropdown.currentTextChanged.connect(
            self.set_new_noisespeakers
        )
        self.available_noisespeakers_dropdown = available_noisespeakers_dropdown
        self.refresh_available_noisespeakers()

        # Noise color picker: QComboBox signal --> update noise color parameter
        available_noisecolors = ["white", "pink", "brown"]
        available_noisecolors_dropdown = QtWidgets.QComboBox()
        available_noisecolors_dropdown.setStatusTip("Select the noise color/type")
        available_noisecolors_dropdown.currentTextChanged.connect(
            self.set_new_noisecolor
        )
        for color in available_noisecolors:
            pixmap = QtGui.QPixmap(16, 16)
            pixmap.fill(QtGui.QColor(color))
            icon = QtGui.QIcon(pixmap)
            available_noisecolors_dropdown.addItem(icon, color)
        self.available_noisecolors_dropdown = available_noisecolors_dropdown

        # Noise volume selector: QDoubleSpinBox signal --> update volume slot
        noisevolumeSpinBox = QtWidgets.QDoubleSpinBox(self)
        noisevolumeSpinBox.setStatusTip(
            "Select volume of noise (must be in range 0-1)."
        )
        noisevolumeSpinBox.setMinimum(0)
        noisevolumeSpinBox.setMaximum(1)
        noisevolumeSpinBox.setSingleStep(0.01)
        noisevolumeSpinBox.valueChanged.connect(self.update_noise_volume)
        noisevolumeSpinBox.setValue(0.2)
        self.noisevolumeSpinBox = noisevolumeSpinBox

        # Stacked Play/Stop transport (mixing-board style).
        playnoiseButton = QtWidgets.QPushButton("Play noise", self)
        playnoiseButton.setStatusTip("Play the selected noise color.")
        playnoiseButton.clicked.connect(self.play_noise)
        stopnoiseButton = QtWidgets.QPushButton("Stop noise", self)
        stopnoiseButton.setStatusTip("Stop the selected noise color.")
        stopnoiseButton.clicked.connect(self.stop_noise)
        transport = QtWidgets.QVBoxLayout()
        transport.addWidget(playnoiseButton)
        transport.addWidget(stopnoiseButton)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignRight)
        form.addRow("Device:", available_noisespeakers_dropdown)
        form.addRow("Color/Type:", available_noisecolors_dropdown)
        form.addRow("Volume:", noisevolumeSpinBox)

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(make_section_title("Noise machine"))
        layout.addWidget(self.noiseStatusLabel)
        layout.addLayout(form)
        layout.addLayout(transport)
        central = QtWidgets.QWidget()
        central.setLayout(layout)
        return central

    def set_new_noisecolor(self, text: str) -> None:
        """Restart noise playback when the noise color changes (``text``)."""
        if self.noise_stream is not None:  # or isactive
            self.stop_noise()
            self.play_noise()

    def set_new_noisespeakers(self, text: str) -> None:
        """Text is the device name, with host api string appended to the end."""
        self.noiseplayer_device = text

    def refresh_available_noisespeakers(self):
        """Populate the noise device selection menu with available speakers."""
        self.available_noisespeakers_dropdown.clear()
        HOST_API = "Windows WASAPI"
        hostapi = [api["name"] for api in sd.query_hostapis()].index(HOST_API)
        devices = sd.query_devices()
        for device in devices:
            if device["hostapi"] == hostapi and device["max_output_channels"] > 0:
                device_name = device["name"]
                device_str = f"{device_name}, {HOST_API}"
                self.available_noisespeakers_dropdown.addItem(device_str)
        if devices:
            self.available_noisespeakers_dropdown.setCurrentIndex(0)
        else:
            self.session.show_error_popup("No audio devices found.", parent=self)

    @staticmethod
    def noise_color_funcs(color: str) -> Callable:
        """Return the noise-generation function for the given color name."""
        noise_functions = {
            "pink": utils.pink_noise,
            "blue": utils.blue_noise,
            "white": utils.white_noise,
            "brown": utils.brownian_noise,
            "violet": utils.violet_noise,
        }
        return noise_functions[color]

    def play_noise(self) -> None:
        """Start streaming the selected noise color to the selected device."""
        device = self.available_noisespeakers_dropdown.currentText()
        color = self.available_noisecolors_dropdown.currentText()
        rate = 44100

        def callback(outdata, frames, time, status):
            """frames is the number of frames (rate)"""
            if status:
                self.session.logger.warning(f"Audio output status: {status}")
            outdata[:] = (
                self.noise_color_funcs(color)(rate).reshape(-1, 1)
                * self.noise_stream_volume
            )

        if self.noise_stream is None:
            self.noise_stream = sd.OutputStream(
                channels=1, blocksize=rate, callback=callback, device=device
            )
            self.noise_stream.start()
            self.noiseStatusLabel.setText("▶ playing")
            self.noiseStatusLabel.setStyleSheet("color: red; font-weight: bold;")

    def stop_noise(self) -> None:
        """Stop and tear down the active noise stream, if any."""
        if self.noise_stream is not None:
            self.noise_stream.abort()
            self.noise_stream = None
        self.noiseStatusLabel.setText("■ stopped")
        self.noiseStatusLabel.setStyleSheet("")

    def update_noise_volume(self, value: float) -> None:
        """Catch the noise volume spinbox signal (value is a 0-1 float)."""
        self.noise_stream_volume = value

    def gather_state(self) -> dict:
        return {
            "noise_volume": self.noisevolumeSpinBox.value(),
            "noise_color": self.available_noisecolors_dropdown.currentText(),
        }

    def apply_state(self, state: dict) -> None:
        if (v := state.get("noise_volume")) is not None:
            self.noisevolumeSpinBox.setValue(float(v))
        if color := state.get("noise_color"):
            idx = self.available_noisecolors_dropdown.findText(color)
            if idx >= 0:
                self.available_noisecolors_dropdown.setCurrentIndex(idx)

    def cleanup(self) -> None:
        self.stop_noise()
