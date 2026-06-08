"""Utility helpers: data-directory resolution and noise/tone generation."""

from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from os import environ
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.io.wavfile import write

_WAV_SUFFIXES = {".wav", ".wave"}
AUDIO_SUFFIXES = {".wav", ".wave", ".mp3", ".flac", ".ogg", ".oga", ".aif", ".aiff"}
DEMO_RATE = 44100


def get_data_directory() -> Path:
    """Return the data directory, creating it if needed.

    Honors the ``SMACC_DATA_DIRECTORY`` environment variable and falls back
    to ``~/SMACC`` when it is not set.
    """
    raw = environ.get("SMACC_DATA_DIRECTORY", "~/SMACC")
    data_directory = Path(raw).expanduser()
    data_directory.mkdir(exist_ok=True)
    return data_directory


def normalize_survey_url(text: str) -> str:
    """Normalize a survey URL for storing and opening in the browser.

    Trims surrounding whitespace, returns ``""`` for blank input, and prepends
    ``https://`` when no scheme is present so a typed ``example.com/survey`` still
    opens correctly.
    """
    text = text.strip()
    if not text:
        return ""
    if "://" not in text:
        text = f"https://{text}"
    return text


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


def normalize_audio(samples: np.ndarray, peak: float = 0.9) -> np.ndarray:
    """Return ``samples`` as float32 scaled so its peak magnitude is ``peak``.

    Keeps generated noise at a predictable level with headroom, so the 0-1
    volume control maps cleanly without clipping at high settings.
    """
    data = samples.astype(np.float32)
    largest = float(np.max(np.abs(data))) if data.size else 0.0
    if largest > 0:
        data *= peak / largest
    return data


def read_loop(buf: np.ndarray, pos: int, frames: int) -> tuple[np.ndarray, int]:
    """Read ``frames`` samples from ``buf`` starting at ``pos``, looping the end.

    ``buf`` is treated as an endless loop; reads spanning the end wrap back to the
    start. Returns the chunk (a view when it doesn't wrap) and the next position.
    """
    n = buf.shape[0]
    pos %= n
    end = pos + frames
    if end <= n:
        return buf[pos:end], end % n
    pieces: list[np.ndarray] = [buf[pos:]]
    remaining = frames - (n - pos)
    if remaining >= n:
        reps = remaining // n
        pieces.append(np.tile(buf, reps))
        remaining -= reps * n
    if remaining:
        pieces.append(buf[:remaining])
    return np.concatenate(pieces), (pos + frames) % n


def resample_to(samples: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Resample mono ``samples`` from ``src_rate`` to ``dst_rate`` as float32.

    Used so a loaded noise file matches the output device's sample rate (WASAPI
    shared mode only opens a stream at the device's own rate).
    """
    data = np.ascontiguousarray(samples, dtype=np.float32)
    if src_rate == dst_rate:
        return data
    from math import gcd

    from scipy.signal import resample_poly

    divisor = gcd(int(src_rate), int(dst_rate))
    resampled = resample_poly(data, dst_rate // divisor, src_rate // divisor)
    return np.ascontiguousarray(resampled, dtype=np.float32)


def _enveloped(
    samples: np.ndarray, rate: int, *, fade: float = 0.01, decay: bool = False
) -> np.ndarray:
    """Apply a short fade in/out (and optional exponential decay) to avoid clicks."""
    n = samples.shape[0]
    env = np.exp(-3.0 * np.linspace(0, 1, n)) if decay else np.ones(n)
    fade_n = min(int(fade * rate), n // 2)
    if fade_n > 0:
        ramp = np.linspace(0.0, 1.0, fade_n)
        env[:fade_n] *= ramp
        env[-fade_n:] *= ramp[::-1]
    return np.clip(samples * env, -32768, 32767).astype(np.int16)


def _demo_chord(rate: int) -> np.ndarray:
    """A C-E-G arpeggio that resolves into a chord (the original test cue)."""
    duration = 1
    amp = 1e4
    silence = note(0, duration, amp, rate)
    c4 = note(261.63, duration, amp, rate)
    e4 = note(329.63, duration, amp, rate)
    g4 = note(392.00, duration, amp, rate)
    seq1 = np.concatenate((c4, silence, silence, silence, c4))
    seq2 = np.concatenate((silence, e4, silence, silence, e4))
    seq3 = np.concatenate((silence, silence, g4, silence, g4))
    song = seq1.astype(np.int32) + seq2.astype(np.int32) + seq3.astype(np.int32)
    return np.clip(song, -32768, 32767).astype(np.int16)


def _demo_chime(rate: int) -> np.ndarray:
    """A bell-like tone with an exponential decay."""
    return _enveloped(note(880.0, 1.5, 1.2e4, rate), rate, fade=0.005, decay=True)


def _demo_alert(rate: int) -> np.ndarray:
    """A two-tone alternating alert."""
    amp = 1e4
    high = note(1000.0, 0.12, amp, rate)
    low = note(800.0, 0.12, amp, rate)
    pattern = np.concatenate([high, low, high, low, high, low])
    return _enveloped(pattern, rate, fade=0.005)


# Built-in demo cues, keyed by their ``demo-`` filename so they stay distinct from
# (and never clobber) a user's own cue files. Used both to pre-render the bundled
# assets and to regenerate on the fly when a demo is missing.
DEMO_CUES: dict[str, Callable[[int], np.ndarray]] = {
    "demo-chord.wav": _demo_chord,
    "demo-chime.wav": _demo_chime,
    "demo-alert.wav": _demo_alert,
}


def generate_demo_cues(dest_dir: Path) -> list[Path]:
    """Synthesize the built-in demo cues into ``dest_dir`` as PCM-16 WAVs."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for name, synth in DEMO_CUES.items():
        path = dest_dir / name
        write(path, DEMO_RATE, synth(DEMO_RATE))
        paths.append(path)
    return paths


def seed_demo_cues(cues_dir: Path, bundled_dir: Path) -> None:
    """Ensure the demo cues exist in ``cues_dir`` (best-effort; never fatal).

    Copies any shipped demo file missing from ``cues_dir`` (restoring a deleted
    demo and adding bundled clips), then synthesizes any built-in demo still
    absent. Existing files are never overwritten, so a user's own cues -- and any
    demos they choose to keep -- are left untouched.
    """
    try:
        cues_dir.mkdir(parents=True, exist_ok=True)
        if bundled_dir.is_dir():
            for src in sorted(bundled_dir.iterdir()):
                dest = cues_dir / src.name
                if src.suffix.lower() in AUDIO_SUFFIXES and not dest.exists():
                    shutil.copy2(src, dest)
        for name, synth in DEMO_CUES.items():
            dest = cues_dir / name
            if not dest.exists():
                write(dest, DEMO_RATE, synth(DEMO_RATE))
    except Exception:
        logging.getLogger("smacc").exception("Could not seed demo cues")
