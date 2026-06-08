"""Noise machine window: stream built-in colored noise or a looped file."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf
from PyQt5 import QtCore, QtGui, QtWidgets

from .. import utils
from ..paths import cues_directory
from ..session import SmaccSession
from .base import ModalityWindow, make_section_title

NOISE_RATE = 44100
# Seconds of colored noise pre-generated per Play and then looped. A single
# irfft buffer is inherently periodic, so it loops seamlessly; the length only
# sets how long until brown's low-frequency pattern perceptually repeats.
NOISE_LOOP_SECONDS = 30
AUDIO_FILTER = "Audio (*.wav *.mp3 *.flac *.ogg *.oga *.aif *.aiff);;All files (*)"


class NoiseWindow(ModalityWindow):
    """Continuous noise generator: built-in colors or a looped user file."""

    TITLE = "Noise machine"

    def __init__(self, session: SmaccSession, parent: QtWidgets.QWidget | None = None):
        super().__init__(session, parent)
        self.noise_stream: sd.OutputStream | None = None
        self.noise_stream_volume = 0.2
        self.noiseplayer_device = ""
        # Mono float32 loop buffer for the active stream, plus its read position.
        self._noise_buffer: np.ndarray | None = None
        self._noise_pos = 0
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

        # Source toggle: built-in generated color vs. a loaded file.
        self.builtinRadio = QtWidgets.QRadioButton("Built-in", self)
        self.fileRadio = QtWidgets.QRadioButton("From file", self)
        self.builtinRadio.setChecked(True)
        source_group = QtWidgets.QButtonGroup(self)
        source_group.addButton(self.builtinRadio)
        source_group.addButton(self.fileRadio)
        self._noise_source_group = source_group
        self.builtinRadio.toggled.connect(self.on_noise_source_changed)
        sourceRow = QtWidgets.QHBoxLayout()
        sourceRow.addWidget(self.builtinRadio)
        sourceRow.addWidget(self.fileRadio)
        sourceRow.addStretch(1)

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

        # Noise file picker (enabled when "From file" is selected).
        self.noiseFileEdit = QtWidgets.QLineEdit(self)
        self.noiseFileEdit.setMinimumWidth(180)
        self.noiseFileEdit.editingFinished.connect(self.on_noise_file_changed)
        self.noiseBrowseButton = QtWidgets.QPushButton("Browse", self)
        self.noiseBrowseButton.clicked.connect(self.open_noise_selector)
        fileRow = QtWidgets.QHBoxLayout()
        fileRow.addWidget(self.noiseFileEdit)
        fileRow.addWidget(self.noiseBrowseButton)

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
        playnoiseButton.setStatusTip("Play the selected noise.")
        playnoiseButton.clicked.connect(self.play_noise)
        stopnoiseButton = QtWidgets.QPushButton("Stop noise", self)
        stopnoiseButton.setStatusTip("Stop the noise.")
        stopnoiseButton.clicked.connect(self.stop_noise)
        transport = QtWidgets.QVBoxLayout()
        transport.addWidget(playnoiseButton)
        transport.addWidget(stopnoiseButton)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignRight)
        form.addRow("Device:", available_noisespeakers_dropdown)
        form.addRow("Source:", sourceRow)
        form.addRow("Color/Type:", available_noisecolors_dropdown)
        form.addRow("File:", fileRow)
        form.addRow("Volume:", noisevolumeSpinBox)

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(make_section_title("Noise machine"))
        layout.addWidget(self.noiseStatusLabel)
        layout.addLayout(form)
        layout.addLayout(transport)
        central = QtWidgets.QWidget()
        central.setLayout(layout)
        self._sync_source_enabled()
        return central

    # ----- source selection -------------------------------------------------

    def _use_file_source(self) -> bool:
        return self.fileRadio.isChecked()

    def _sync_source_enabled(self) -> None:
        """Enable the color picker xor the file row to match the source toggle."""
        file_mode = self._use_file_source()
        self.available_noisecolors_dropdown.setEnabled(not file_mode)
        self.noiseFileEdit.setEnabled(file_mode)
        self.noiseBrowseButton.setEnabled(file_mode)

    def _restart_if_playing(self) -> None:
        """Re-apply the current selection by restarting an active stream."""
        if self.noise_stream is not None:
            self.stop_noise()
            self.play_noise()

    def on_noise_source_changed(self, checked: bool) -> None:
        """Built-in/file toggled: update enabled controls and restart if playing."""
        self._sync_source_enabled()
        self._restart_if_playing()

    def on_noise_file_changed(self) -> None:
        """A new file path was chosen: restart playback if in file mode."""
        if self._use_file_source():
            self._restart_if_playing()

    def open_noise_selector(self) -> None:
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select a noise file", str(cues_directory), AUDIO_FILTER
        )
        if filename:
            self.noiseFileEdit.setText(str(Path(filename)))
            self.on_noise_file_changed()

    def set_new_noisecolor(self, text: str) -> None:
        """Restart noise playback when the noise color changes (``text``)."""
        if not self._use_file_source():
            self._restart_if_playing()

    def set_new_noisespeakers(self, text: str) -> None:
        """Text is the device name, with host api string appended to the end."""
        self.noiseplayer_device = text
        self._restart_if_playing()  # switch a live stream over to the new device

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

    # ----- playback ---------------------------------------------------------

    def _device_samplerate(self, device: str) -> int:
        """Best output sample rate for ``device`` (WASAPI opens only at its own)."""
        try:
            return int(sd.query_devices(device, "output")["default_samplerate"])
        except Exception:
            return NOISE_RATE

    def _build_noise_buffer(self, rate: int) -> np.ndarray:
        """Return a mono float32 loop buffer for the current source at ``rate`` Hz."""
        if self._use_file_source():
            path = self.noiseFileEdit.text().strip()
            if not path or not Path(path).is_file():
                raise FileNotFoundError("Choose a noise file to play.")
            data, file_rate = sf.read(path, dtype="float32")
            if data.ndim > 1:  # down-mix to mono
                data = data.mean(axis=1)
            return utils.resample_to(data, int(file_rate), rate)
        color = self.available_noisecolors_dropdown.currentText()
        samples = self.noise_color_funcs(color)(int(NOISE_LOOP_SECONDS * rate))
        return utils.normalize_audio(samples)

    def _noise_callback(self, outdata, frames, time, status) -> None:
        """Fill ``outdata`` from the loop buffer, scaled by the live volume."""
        if status:
            self.session.logger.warning(f"Audio output status: {status}")
        buf = self._noise_buffer
        if buf is None or buf.shape[0] == 0:
            outdata.fill(0)
            return
        chunk, self._noise_pos = utils.read_loop(buf, self._noise_pos, frames)
        np.multiply(chunk, self.noise_stream_volume, out=outdata[:, 0])

    def play_noise(self) -> None:
        """Start streaming the selected noise (built-in color or file) on loop."""
        if self.noise_stream is not None:
            return  # already playing
        device = self.available_noisespeakers_dropdown.currentText()
        rate = self._device_samplerate(device)
        try:
            buf = self._build_noise_buffer(rate)
        except Exception as err:
            self.session.show_error_popup(
                "Could not load noise audio", str(err), parent=self
            )
            return
        self._noise_buffer = buf
        self._noise_pos = 0
        try:
            stream = sd.OutputStream(
                channels=1,
                samplerate=rate,
                callback=self._noise_callback,
                device=device,
            )
            stream.start()
        except Exception as err:
            self._noise_buffer = None
            self.session.show_error_popup(
                "Could not start noise output", str(err), parent=self
            )
            return
        self.noise_stream = stream
        self.noiseStatusLabel.setText("▶ playing")
        self.noiseStatusLabel.setStyleSheet("color: red; font-weight: bold;")

    def stop_noise(self) -> None:
        """Stop and tear down the active noise stream, if any."""
        if self.noise_stream is not None:
            self.noise_stream.abort()
            self.noise_stream.close()
            self.noise_stream = None
        self._noise_buffer = None
        self._noise_pos = 0
        self.noiseStatusLabel.setText("■ stopped")
        self.noiseStatusLabel.setStyleSheet("")

    def update_noise_volume(self, value: float) -> None:
        """Catch the noise volume spinbox signal (value is a 0-1 float)."""
        self.noise_stream_volume = value

    def gather_state(self) -> dict:
        return {
            "noise_volume": self.noisevolumeSpinBox.value(),
            "noise_color": self.available_noisecolors_dropdown.currentText(),
            "noise_source": "file" if self._use_file_source() else "builtin",
            "noise_file": self.noiseFileEdit.text(),
        }

    def apply_state(self, state: dict) -> None:
        if (v := state.get("noise_volume")) is not None:
            self.noisevolumeSpinBox.setValue(float(v))
        if color := state.get("noise_color"):
            idx = self.available_noisecolors_dropdown.findText(color)
            if idx >= 0:
                self.available_noisecolors_dropdown.setCurrentIndex(idx)
        if (f := state.get("noise_file")) is not None:
            self.noiseFileEdit.setText(str(f))
        if src := state.get("noise_source"):
            if src == "file":
                self.fileRadio.setChecked(True)
            else:
                self.builtinRadio.setChecked(True)
        self._sync_source_enabled()

    def cleanup(self) -> None:
        self.stop_noise()
