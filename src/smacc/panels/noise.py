"""Noise machine window: stream built-in colored noise or a looped file."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf
from PyQt6 import QtCore, QtGui, QtWidgets

from .. import utils
from ..session import SmaccSession
from .base import ModalityWindow, describe_target, make_section_title

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
        # Mono float32 loop buffer for the active stream, plus its read position.
        self._noise_buffer: np.ndarray | None = None
        self._noise_pos = 0
        self.setCentralWidget(self._build())

    def _build(self) -> QtWidgets.QWidget:
        # "Now playing" indicator on top (mixing-board style).
        self.noiseStatusLabel = QtWidgets.QLabel("■ stopped", self)
        self.noiseStatusLabel.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

        # Device is chosen in the Devices window; show where noise resolves to.
        self.deviceLabel = QtWidgets.QLabel(self)
        self.deviceLabel.setStatusTip("Set in the Devices window (Noise → role).")
        self.refresh_device_indicator()

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
        playnoiseButton.clicked.connect(self.on_play_noise_clicked)
        stopnoiseButton = QtWidgets.QPushButton("Stop noise", self)
        stopnoiseButton.setStatusTip("Stop the noise.")
        stopnoiseButton.clicked.connect(self.on_stop_noise_clicked)
        transport = QtWidgets.QVBoxLayout()
        transport.addWidget(playnoiseButton)
        transport.addWidget(stopnoiseButton)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        form.addRow("Device:", self.deviceLabel)
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
        source = "file" if self._use_file_source() else "built-in"
        self.session.log_interaction(f"Noise source set to {source}")
        self._restart_if_playing()

    def on_noise_file_changed(self) -> None:
        """A new file path was chosen: restart playback if in file mode."""
        if self._use_file_source():
            self._restart_if_playing()

    def open_noise_selector(self) -> None:
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select a noise file", str(self.session.cues_dir), AUDIO_FILTER
        )
        if filename:
            self.noiseFileEdit.setText(str(Path(filename)))
            self.on_noise_file_changed()

    def set_new_noisecolor(self, text: str) -> None:
        """Restart noise playback when the noise color changes (``text``)."""
        if not self._use_file_source():
            self.session.log_interaction(f"Noise color set to {text}")
            self._restart_if_playing()

    def refresh_device_indicator(self) -> None:
        """Show where noise output resolves (device chosen in the Devices window)."""
        self.deviceLabel.setText(describe_target(self.session, "noise_out"))

    def is_streaming(self) -> bool:
        """True while noise is playing (an open output stream)."""
        return self.noise_stream is not None

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

    def _device_samplerate(self, device: str | None) -> int:
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
        # The master safety cap is the single final gain stage (read live).
        gain = self.noise_stream_volume * self.session.volume_cap
        np.multiply(chunk, gain, out=outdata[:, 0])

    def on_play_noise_clicked(self, _checked: bool = False) -> None:
        """User pressed Play: start the noise and mark it (NoiseStarted).

        The marker fires only on a real user start, not on the silent stop+start
        restart used when the color/device/source changes mid-playback.
        """
        already_playing = self.noise_stream is not None
        self.play_noise()
        if not already_playing and self.noise_stream is not None:
            self.session.emit_event("NoiseStarted")

    def on_stop_noise_clicked(self, _checked: bool = False) -> None:
        """User pressed Stop: stop the noise and mark it (NoiseStopped)."""
        was_playing = self.noise_stream is not None
        self.stop_noise()
        if was_playing:
            self.session.emit_event("NoiseStopped")

    def play_noise(self) -> None:
        """Start streaming the selected noise (built-in color or file) on loop."""
        if self.noise_stream is not None:
            return  # already playing
        device = self.session.devices.device_for("noise_out") or None
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
        self.session.log_interaction(f"Noise volume set to {value:.2f}", debug=True)

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
