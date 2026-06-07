"""Utility helpers: data-directory resolution and noise/tone generation."""

from __future__ import annotations

from collections.abc import Callable
from os import environ
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.io.wavfile import write

_WAV_SUFFIXES = {".wav", ".wave"}


def get_data_directory() -> Path:
    """Return the data directory, creating it if needed.

    Honors the ``SMACC_DATA_DIRECTORY`` environment variable and falls back
    to ``~/SMACC`` when it is not set.
    """
    raw = environ.get("SMACC_DATA_DIRECTORY", "~/SMACC")
    data_directory = Path(raw).expanduser()
    data_directory.mkdir(exist_ok=True)
    return data_directory


def ensure_wav(src: Path, cache_dir: Path) -> Path:
    """Return a QSoundEffect-playable PCM WAV for ``src``.

    WAV inputs are returned unchanged. Other formats (mp3/flac/ogg/aiff) are
    decoded to a 16-bit PCM WAV under ``cache_dir`` and that path is returned.
    The cache key includes the source mtime, so edits re-decode but repeats reuse.
    """
    if src.suffix.lower() in _WAV_SUFFIXES:
        return src
    dest = cache_dir / f"{src.stem}-{src.stat().st_mtime_ns}.wav"
    if not dest.exists():
        data, rate = sf.read(str(src), dtype="int16")  # mono or (frames, channels)
        sf.write(str(dest), data, rate, subtype="PCM_16")
    return dest


def note(freq: float, duration: float, amp: float, rate: int) -> np.ndarray:
    """Return a sine-wave tone as 16-bit integer samples.

    https://stackoverflow.com/q/11570942
    """
    t = np.linspace(0, duration, int(duration * rate))
    data = np.sin(2 * np.pi * freq * t) * amp
    return data.astype(np.int16)  # two byte integers


def noise_psd(N: int, psd: Callable = lambda f: 1) -> np.ndarray:
    """Generate noise shaped by a power-spectral-density function.

    https://stackoverflow.com/a/67127726
    """
    X_white = np.fft.rfft(np.random.randn(N))
    S = psd(np.fft.rfftfreq(N))
    # Normalize S
    S = S / np.sqrt(np.mean(S**2))
    X_shaped = X_white * S
    return np.fft.irfft(X_shaped)


def PSDGenerator(f: Callable) -> Callable[[int], np.ndarray]:
    """Turn a PSD-shape function into a noise generator taking a sample count."""
    return lambda N: noise_psd(N, f)


@PSDGenerator
def white_noise(f):
    """Flat power spectrum."""
    return 1


@PSDGenerator
def blue_noise(f):
    """Power spectrum proportional to sqrt(f)."""
    return np.sqrt(f)


@PSDGenerator
def violet_noise(f):
    """Power spectrum proportional to f."""
    return f


@PSDGenerator
def brownian_noise(f):
    """Power spectrum proportional to 1/f."""
    return 1 / np.where(f == 0, float("inf"), f)


@PSDGenerator
def pink_noise(f):
    """Power spectrum proportional to 1/sqrt(f)."""
    return 1 / np.where(f == 0, float("inf"), np.sqrt(f))


def generate_test_cue_file() -> None:
    """Generate a short multi-tone test cue and save it to the cues directory."""
    data_directory = get_data_directory()
    cues_directory = data_directory / "cues"
    cues_directory.mkdir(exist_ok=True)
    duration = 1
    amp = 1e4
    rate = 44100
    tone0 = note(0, duration, amp, rate)  # silence
    tone1 = note(261.63, duration, amp, rate)  # C4
    tone2 = note(329.63, duration, amp, rate)  # E4
    tone3 = note(392.00, duration, amp, rate)  # G4
    seq1 = np.concatenate((tone1, tone0, tone0, tone0, tone1), axis=0)
    seq2 = np.concatenate((tone0, tone2, tone0, tone0, tone2), axis=0)
    seq3 = np.concatenate((tone0, tone0, tone3, tone0, tone3), axis=0)
    song = seq1 + seq2 + seq3
    export_path = cues_directory / "song.wav"
    write(export_path, 44100, song)
