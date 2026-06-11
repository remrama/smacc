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

A whole design — the segment pattern, its repeat train, and the master settings —
is captured by :class:`CueDesign`, which (de)serializes to a plain dict so the
designer can save and reopen editable ``.json`` design files (#137).
"""

from __future__ import annotations

from dataclasses import dataclass, field
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


def repeat_segments(
    segments: list[Segment], count: int, gap: float = 0.0
) -> list[Segment]:
    """Expand ``segments`` into ``count`` repeats separated by ``gap`` s of silence.

    The standard cue shape is a *pip train* — one short pattern repeated a few
    times — so the repeat lives here rather than as N hand-copied rows. Repeats
    share the original segment objects (rendering never mutates a segment); a
    non-positive ``gap`` inserts nothing between repeats.
    """
    if count < 1:
        raise ValueError("repeat count must be at least 1")
    out: list[Segment] = []
    for i in range(count):
        if i and gap > 0:
            out.append(SilenceSegment(duration=gap))
        out.extend(segments)
    return out


# Version stamp written into saved cue-design files; bump on schema changes.
DESIGN_VERSION = 1


@dataclass
class CueDesign:
    """A complete, serializable cue design: segment pattern plus master settings.

    This is the unit the Cue designer saves and reopens as a JSON design file
    (#137). The exported WAV stays the lab-facing artifact the cue board plays;
    the design file is what keeps a cue editable. The pattern repeats
    ``repeat_count`` times with ``repeat_gap`` seconds of silence between repeats,
    then the whole train is normalized/faded as one cue.
    """

    segments: list[Segment] = field(default_factory=list)
    name: str = "cue"
    fade_in: float = 0.0
    fade_out: float = 0.0
    normalize: bool = False
    repeat_count: int = 1
    repeat_gap: float = 0.0

    def expanded_segments(self) -> list[Segment]:
        """The pattern expanded into its repeat train (what actually renders)."""
        return repeat_segments(self.segments, self.repeat_count, self.repeat_gap)

    def total_duration(self) -> float:
        """Length of the full rendered cue in seconds, repeats included."""
        return total_duration(self.expanded_segments())

    def render(self, rate: int = DEFAULT_RATE) -> np.ndarray:
        """Render the full design to one mono float32 cue in ``[-1, 1]``."""
        return render_sequence(
            self.expanded_segments(),
            rate=rate,
            fade_in=self.fade_in,
            fade_out=self.fade_out,
            normalize=self.normalize,
        )

    def to_dict(self) -> dict:
        """Serialize to a JSON-ready dict, stamped with the schema version."""
        segments: list[dict] = []
        for seg in self.segments:
            if isinstance(seg, ToneSegment):
                segments.append(
                    {
                        "type": "tone",
                        "freq": seg.freq,
                        "duration": seg.duration,
                        "level": seg.level,
                        "decay": seg.decay,
                    }
                )
            else:
                segments.append({"type": "silence", "duration": seg.duration})
        return {
            "version": DESIGN_VERSION,
            "name": self.name,
            "fade_in": self.fade_in,
            "fade_out": self.fade_out,
            "normalize": self.normalize,
            "repeat_count": self.repeat_count,
            "repeat_gap": self.repeat_gap,
            "segments": segments,
        }

    @classmethod
    def from_dict(cls, data: object) -> CueDesign:
        """Rebuild a design from :meth:`to_dict` output (``ValueError`` if invalid)."""
        if not isinstance(data, dict):
            raise ValueError("a cue design must be a JSON object")
        version = data.get("version")
        if version != DESIGN_VERSION:
            raise ValueError(f"unsupported cue-design version: {version!r}")
        raw_segments = data.get("segments")
        if not isinstance(raw_segments, list) or not raw_segments:
            raise ValueError("a cue design needs at least one segment")
        try:
            segments: list[Segment] = []
            for raw in raw_segments:
                if not isinstance(raw, dict):
                    raise ValueError("segment entries must be objects")
                kind = raw.get("type")
                if kind == "tone":
                    segments.append(
                        ToneSegment(
                            freq=float(raw["freq"]),
                            duration=float(raw["duration"]),
                            level=float(raw.get("level", 1.0)),
                            decay=bool(raw.get("decay", False)),
                        )
                    )
                elif kind == "silence":
                    segments.append(SilenceSegment(duration=float(raw["duration"])))
                else:
                    raise ValueError(f"unknown segment type: {kind!r}")
            design = cls(
                segments=segments,
                name=str(data.get("name", "cue")),
                fade_in=float(data.get("fade_in", 0.0)),
                fade_out=float(data.get("fade_out", 0.0)),
                normalize=bool(data.get("normalize", False)),
                repeat_count=int(data.get("repeat_count", 1)),
                repeat_gap=float(data.get("repeat_gap", 0.0)),
            )
        except (KeyError, TypeError, ValueError) as err:
            raise ValueError(f"invalid cue design: {err}") from err
        if design.repeat_count < 1:
            raise ValueError("repeat count must be at least 1")
        return design
