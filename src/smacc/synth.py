"""Tone synthesis for the Cue designer (#77): build a cue from simple segments.

Pure, hardware-free DSP — no Qt, no streams — so it is unit-testable on its own. The
Cue designer (:mod:`smacc.cuedesigner`) assembles a list of **segments** (a pure
tone or a gap of silence), renders them into one mono float32 buffer in ``[-1, 1]``,
and exports a PCM-16 WAV that drops straight into a study's ``cues`` folder.

This is deliberately kept separate from the demo-cue synthesis in
:mod:`smacc.utils` (``note``/``_demo_*``), which is frozen to match the committed
demo WAV assets. The model here is intentionally simple — a monophonic sequence of
tones and silences with a per-tone decay and a master fade — not a full ADSR
synthesizer (see #33, closed in favor of this).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

# A generated cue's default sample rate (CD quality); the designer may override it.
DEFAULT_RATE = 44100
# Shortest fade applied to every tone's edges so a hard sine edge — or the seam
# between two segments — doesn't click. In seconds.
EDGE_FADE_S = 0.005
# Peak magnitude a normalized cue is scaled to (leaves a sliver of headroom).
NORMALIZE_PEAK = 0.97


@dataclass
class ToneSegment:
    """A pure sine tone: ``freq`` Hz for ``duration`` s at ``level`` (0-1).

    ``decay`` applies a bell-like exponential fall across the tone; a short
    anti-click fade is always applied at both edges regardless.
    """

    freq: float
    duration: float
    level: float = 1.0
    decay: bool = False


@dataclass
class SilenceSegment:
    """A gap of silence lasting ``duration`` seconds."""

    duration: float


Segment = ToneSegment | SilenceSegment


def _edge_fade(env: np.ndarray, rate: int) -> None:
    """Multiply a short linear ramp into both ends of ``env`` in place (anti-click)."""
    n = env.shape[0]
    fade_n = min(int(EDGE_FADE_S * rate), n // 2)
    if fade_n > 0:
        ramp = np.linspace(0.0, 1.0, fade_n)
        env[:fade_n] *= ramp
        env[-fade_n:] *= ramp[::-1]


def _render_tone(seg: ToneSegment, rate: int) -> np.ndarray:
    """Render one tone segment to mono float32 (empty for a non-positive duration)."""
    n = max(0, int(round(seg.duration * rate)))
    if n == 0:
        return np.zeros(0, dtype=np.float32)
    t = np.arange(n, dtype=np.float64) / rate
    wave = np.sin(2.0 * np.pi * seg.freq * t) * seg.level
    env = np.ones(n, dtype=np.float64)
    if seg.decay:
        env *= np.exp(-3.0 * np.linspace(0.0, 1.0, n))
    _edge_fade(env, rate)
    return (wave * env).astype(np.float32)


def render_segment(seg: Segment, rate: int) -> np.ndarray:
    """Render a single segment (tone or silence) to a mono float32 buffer."""
    if isinstance(seg, ToneSegment):
        return _render_tone(seg, rate)
    if isinstance(seg, SilenceSegment):
        return np.zeros(max(0, int(round(seg.duration * rate))), dtype=np.float32)
    raise TypeError(f"unknown segment type: {type(seg).__name__}")


def _normalize_peak(samples: np.ndarray, peak: float = NORMALIZE_PEAK) -> np.ndarray:
    """Scale ``samples`` so their largest magnitude is ``peak`` (silence unchanged)."""
    largest = float(np.max(np.abs(samples))) if samples.size else 0.0
    if largest > 0:
        return (samples * (peak / largest)).astype(np.float32)
    return samples


def _master_fades(
    samples: np.ndarray, rate: int, fade_in: float, fade_out: float
) -> None:
    """Apply whole-cue fade-in/out ramps to ``samples`` in place (seconds)."""
    n = samples.shape[0]
    if n == 0:
        return
    fi = min(int(round(fade_in * rate)), n)
    if fi > 0:
        samples[:fi] *= np.linspace(0.0, 1.0, fi, dtype=np.float32)
    fo = min(int(round(fade_out * rate)), n)
    if fo > 0:
        samples[-fo:] *= np.linspace(1.0, 0.0, fo, dtype=np.float32)


def render_sequence(
    segments: list[Segment],
    *,
    rate: int = DEFAULT_RATE,
    fade_in: float = 0.0,
    fade_out: float = 0.0,
    normalize: bool = False,
) -> np.ndarray:
    """Render ``segments`` end-to-end into one mono float32 cue in ``[-1, 1]``.

    Segments are concatenated in order. ``normalize`` scales the whole cue to a
    fixed peak first; the master ``fade_in``/``fade_out`` ramps (seconds) are then
    applied over the start/end of the result. An empty list yields an empty buffer.
    """
    if rate <= 0:
        raise ValueError("sample rate must be positive")
    parts = [render_segment(seg, rate) for seg in segments]
    out = (
        np.concatenate(parts).astype(np.float32)
        if parts
        else np.zeros(0, dtype=np.float32)
    )
    if normalize:
        out = _normalize_peak(out)
    out = np.ascontiguousarray(out, dtype=np.float32)  # writable for the in-place fades
    _master_fades(out, rate, fade_in, fade_out)
    np.clip(out, -1.0, 1.0, out=out)
    return out


def total_duration(segments: list[Segment]) -> float:
    """Total length of ``segments`` in seconds (negative durations count as zero)."""
    return float(sum(max(0.0, seg.duration) for seg in segments))


def export_wav(
    path: str | Path, samples: np.ndarray, rate: int, *, subtype: str = "PCM_16"
) -> None:
    """Write ``samples`` (mono float32 in ``[-1, 1]``) to ``path`` as a WAV."""
    sf.write(str(path), samples, int(rate), subtype=subtype)
