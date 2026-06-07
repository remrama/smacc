"""Audio cue window: play a sound file with fade-in/out and looping."""

from __future__ import annotations

from pathlib import Path

from PyQt5 import QtCore, QtMultimedia, QtWidgets

from ..paths import cues_directory
from ..session import SmaccSession
from .base import ModalityWindow, make_section_title


class AudioCueWindow(ModalityWindow):
    """Cue-sound player with a mixing-board transport (play/stop, loop, status)."""

    TITLE = "Audio cue"

    def __init__(self, session: SmaccSession, parent: QtWidgets.QWidget | None = None):
        super().__init__(session, parent)
        player = QtMultimedia.QSoundEffect()
        player.setLoopCount(1)
        player.playingChanged.connect(self.on_cue_playing_change)
        self.wavplayer = player
        # Fade (attack/release) durations in seconds; 0 == instant on/off.
        self.cue_attack_s = 0.0
        self.cue_release_s = 0.0
        self._cue_fade_anim: QtCore.QPropertyAnimation | None = None
        self.setCentralWidget(self._build())

    def _build(self) -> QtWidgets.QWidget:
        # "Now playing" indicator on top (mixing-board style).
        cueStatusLabel = QtWidgets.QLabel("■ stopped", self)
        cueStatusLabel.setAlignment(QtCore.Qt.AlignCenter)
        self.cueStatusLabel = cueStatusLabel

        # Device picker: QComboBox signal --> update device slot
        available_speakers_dropdown = QtWidgets.QComboBox()
        available_speakers_dropdown.setStatusTip("Select audio stimulation device")
        available_speakers_dropdown.setPlaceholderText("No speaker devices were found.")
        available_speakers_dropdown.currentTextChanged.connect(self.set_new_speakers)
        self.available_speakers_dropdown = available_speakers_dropdown
        self.refresh_available_speakers()

        wavselectorLayout = QtWidgets.QHBoxLayout()
        wavselectorLabel = QtWidgets.QLabel("Sound:", self)
        wavselectorEdit = QtWidgets.QLineEdit(self)
        wavselectorButton = QtWidgets.QPushButton("Browse", self)
        wavselectorButton.clicked.connect(self.open_wav_selector)
        wavselectorLayout.addWidget(wavselectorLabel)
        wavselectorLayout.addWidget(wavselectorEdit)
        wavselectorLayout.addWidget(wavselectorButton)
        wavselectorEdit.textChanged.connect(self.update_audio_source)
        wavselectorEdit.editingFinished.connect(self.update_audio_source)
        self.wavselectorEdit = wavselectorEdit

        # Volume selector
        volumeSpinBox = QtWidgets.QDoubleSpinBox(self)
        volumeSpinBox.setStatusTip(
            "Select volume of audio stimulation (must be in range 0-1)."
        )
        volumeSpinBox.setMinimum(0)
        volumeSpinBox.setMaximum(1)  # QSoundEffect only allows 0-1
        volumeSpinBox.setSingleStep(0.01)
        volumeSpinBox.valueChanged.connect(self.update_audio_volume)
        volumeSpinBox.setValue(0.2)
        self.volumeSpinBox = volumeSpinBox

        # Fade-in (attack) and fade-out (release) ramps, in seconds. Ramping the
        # cue volume avoids an abrupt onset that could wake the participant (#22).
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

        # Loop toggle: when checked, the cue repeats until stopped.
        loopCheckBox = QtWidgets.QCheckBox("Loop until stopped", self)
        loopCheckBox.setStatusTip(
            "Repeat the cue continuously until the Stop button is pressed."
        )
        loopCheckBox.toggled.connect(self.update_audio_loop)
        self.loopCheckBox = loopCheckBox

        # Stacked Play/Stop transport (mixing-board style).
        playButton = QtWidgets.QPushButton("Play soundfile", self)
        playButton.setStatusTip("Play the selected sound file.")
        playButton.clicked.connect(self.stimulate_audio)
        stopcueButton = QtWidgets.QPushButton("Stop", self)
        stopcueButton.setStatusTip("Stop the currently playing cue.")
        stopcueButton.clicked.connect(self.stop_audio)
        transport = QtWidgets.QVBoxLayout()
        transport.addWidget(playButton)
        transport.addWidget(stopcueButton)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignRight)
        form.addRow("Device:", available_speakers_dropdown)
        form.addRow("Volume:", volumeSpinBox)
        form.addRow("Fade in:", attackSpinBox)
        form.addRow("Fade out:", releaseSpinBox)
        form.addRow(wavselectorLayout)
        form.addRow(loopCheckBox)

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(make_section_title("Audio cue"))
        layout.addWidget(cueStatusLabel)
        layout.addLayout(form)
        layout.addLayout(transport)
        central = QtWidgets.QWidget()
        central.setLayout(layout)
        return central

    def open_wav_selector(self):
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select a File", str(cues_directory), "Audio (*.wav)"
        )
        if filename:
            self.wavselectorEdit.setText(str(Path(filename)))

    def set_new_speakers(self, text: str) -> None:
        """Handle a new audio-stimulation speaker selection."""
        self.session.logger.debug(f"New speakers {text} selected!")

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

    def stimulate_audio(self):
        """Play the cue, ramping volume up over the attack time if set."""
        target = self.volumeSpinBox.value()
        if self.cue_attack_s > 0:
            self.wavplayer.setVolume(0.0)
            self.wavplayer.play()
            self._fade_volume(0.0, target, self.cue_attack_s)
        else:
            self.wavplayer.setVolume(target)
            self.wavplayer.play()

    def stop_audio(self):
        """Stop the cue, ramping volume down over the release time if set."""
        if self.cue_release_s > 0 and self.wavplayer.isPlaying():
            anim = self._fade_volume(self.wavplayer.volume(), 0.0, self.cue_release_s)
            anim.finished.connect(self.wavplayer.stop)
        else:
            self.wavplayer.stop()

    def _fade_volume(
        self, start: float, end: float, seconds: float
    ) -> QtCore.QPropertyAnimation:
        """Animate the cue player's volume from ``start`` to ``end``."""
        anim = QtCore.QPropertyAnimation(self.wavplayer, b"volume", self)
        anim.setDuration(int(seconds * 1000))
        anim.setStartValue(float(start))
        anim.setEndValue(float(end))
        anim.start()
        self._cue_fade_anim = anim  # keep a reference so it isn't garbage-collected
        return anim

    def update_cue_attack(self, value: float) -> None:
        """Set the cue fade-in (attack) time in seconds."""
        self.cue_attack_s = value

    def update_cue_release(self, value: float) -> None:
        """Set the cue fade-out (release) time in seconds."""
        self.cue_release_s = value

    def update_audio_loop(self, enabled: bool) -> None:
        """Set the cue loop count from the loop checkbox."""
        loop_count = QtMultimedia.QSoundEffect.Infinite if enabled else 1
        self.wavplayer.setLoopCount(loop_count)

    def update_audio_source(self):
        """Catch the audio-file line edit/browse signal and set the cue source."""
        filepath = self.wavselectorEdit.text()
        content = QtCore.QUrl.fromLocalFile(filepath)
        self.wavplayer.setSource(content)

    def update_audio_volume(self, value: float) -> None:
        """Catch the cue volume spinbox signal (value is a 0-1 float)."""
        self.wavplayer.setVolume(value)

    def on_cue_playing_change(self) -> None:
        """Update the cue status indicator when playback starts/stops."""
        if self.wavplayer.isPlaying():
            looping = self.loopCheckBox.isChecked()
            self.cueStatusLabel.setText(
                "\U0001f501 looping" if looping else "▶ playing"
            )
            self.cueStatusLabel.setStyleSheet("color: red; font-weight: bold;")
        else:
            self.cueStatusLabel.setText("■ stopped")
            self.cueStatusLabel.setStyleSheet("")

    def gather_state(self) -> dict:
        return {
            "cue_file": self.wavselectorEdit.text(),
            "cue_volume": self.volumeSpinBox.value(),
            "cue_loop": self.loopCheckBox.isChecked(),
            "cue_attack": self.attackSpinBox.value(),
            "cue_release": self.releaseSpinBox.value(),
        }

    def apply_state(self, state: dict) -> None:
        if cue := state.get("cue_file"):
            self.wavselectorEdit.setText(cue)
        if (v := state.get("cue_volume")) is not None:
            self.volumeSpinBox.setValue(float(v))
        if (v := state.get("cue_attack")) is not None:
            self.attackSpinBox.setValue(float(v))
        if (v := state.get("cue_release")) is not None:
            self.releaseSpinBox.setValue(float(v))
        self.loopCheckBox.setChecked(bool(state.get("cue_loop", False)))

    def cleanup(self) -> None:
        self.wavplayer.stop()
