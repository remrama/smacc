"""Audio DSP helpers for SMACC's real-time streams (level meter, voice chat, cues).

Pure functions and small state machines only — separated from the GUI so they are
unit-testable without audio hardware. The sounddevice streams that call these live
in the tool panels (``panels/*.py``).
"""

from __future__ import annotations

import numpy as np

# Quietest level we report; avoids log10(0) and bounds the meter.
FLOOR_DBFS = -90.0
# Level mapped to the bottom of the on-screen meter.
METER_FLOOR_DBFS = -60.0


def rms_dbfs(block: np.ndarray, floor_db: float = FLOOR_DBFS) -> float:
    """Return the RMS level of a float audio ``block`` in dBFS.

    ``block`` holds samples in [-1, 1] (any shape). Full scale (RMS 1.0) is 0 dB;
    silence clamps to ``floor_db``.
    """
    if block.size == 0:
        return floor_db
    rms = float(np.sqrt(np.mean(np.square(block, dtype=np.float64))))
    if rms <= 0.0:
        return floor_db
    return max(floor_db, 20.0 * np.log10(rms))


def dbfs_to_meter(db: float, floor_db: float = METER_FLOOR_DBFS) -> int:
    """Map a dBFS level in [``floor_db``, 0] to an int percent [0, 100]."""
    span = 0.0 - floor_db
    percent = (db - floor_db) / span * 100.0
    return int(min(100.0, max(0.0, percent)))


class AmbientBaseline:
    """A slowly-adapting noise-floor estimate, so a *rise* above the room's resting
    level is readable even when the absolute level is low (#37).

    Fed the input level in dBFS each refresh, the floor drops instantly to a quieter
    level but creeps back up only slowly. The headline :meth:`update` return — the
    rise (level minus floor) — then jumps when a cue lifts the mic above the room
    noise, which is the sensitivity a cheap mic on a faint cue otherwise lacks. The
    floor adapts to a *sustained* sound over a few seconds, so this favors short
    cues; a long looping cue still reads on the absolute level meter beside it.
    """

    def __init__(
        self, creep_db_per_update: float = 0.15, floor_db: float = FLOOR_DBFS
    ) -> None:
        self._initial = floor_db
        self._creep = creep_db_per_update
        self._floor = floor_db
        self._seen = False

    @property
    def floor(self) -> float:
        """The current noise-floor estimate, in dBFS."""
        return self._floor

    def update(self, level_db: float) -> float:
        """Fold in a new level (dBFS); return the rise above the floor (``>= 0``)."""
        if not self._seen or level_db < self._floor:
            self._floor = level_db
            self._seen = True
        else:
            self._floor = min(level_db, self._floor + self._creep)
        return max(0.0, level_db - self._floor)

    def reset(self) -> None:
        """Forget the learned floor (e.g. when the meter's device changes)."""
        self._floor = self._initial
        self._seen = False


class CueMixer:
    """One-at-a-time cue playback engine for the audio callback (no Qt, no I/O).

    Holds the active mono buffer, read position, loop flag, per-cue volume, and a
    linear fade envelope: :meth:`start` ramps the gain 0->1 over the attack and
    :meth:`stop` ramps it 1->0 over the release. :meth:`render` produces the next
    block (silence when idle) and flags :attr:`ended` when a non-looping cue runs
    out or a release fade reaches zero, so the GUI thread can tear the stream down
    and mark the stop. All state lives here, so it is unit-testable without a sound
    device. ``volume`` and ``loop`` may be set live (read on the next block).
    """

    def __init__(self) -> None:
        self._buffer: np.ndarray | None = None
        self._pos = 0
        self.loop = False
        self.volume = 1.0
        self._gain = 0.0  # current fade gain in [0, 1]
        self._gain_step = 0.0  # per-sample change toward _target (0 == steady)
        self._target = 0.0  # fade target: 1.0 while playing, 0.0 when stopping
        self._ended = True

    def start(
        self,
        buffer: np.ndarray,
        *,
        volume: float = 1.0,
        loop: bool = False,
        attack_samples: int = 0,
    ) -> None:
        """Begin playing ``buffer`` (mono float32), with an optional fade-in."""
        self._buffer = np.ascontiguousarray(buffer, dtype=np.float32)
        self._pos = 0
        self.loop = bool(loop)
        self.volume = float(volume)
        self._target = 1.0
        if attack_samples > 0:
            self._gain = 0.0
            self._gain_step = 1.0 / attack_samples
        else:
            self._gain = 1.0
            self._gain_step = 0.0
        self._ended = self._buffer.shape[0] == 0

    def stop(self, *, release_samples: int = 0) -> None:
        """Start a fade-out over ``release_samples`` (end immediately when 0)."""
        self._target = 0.0
        if release_samples > 0 and self._gain > 0.0:
            self._gain_step = -self._gain / release_samples
        else:
            self._gain = 0.0
            self._gain_step = 0.0
            self._ended = True

    @property
    def ended(self) -> bool:
        """True once the cue has finished (ran out, or a release fade reached 0)."""
        return self._ended

    def render(self, frames: int) -> np.ndarray:
        """Return the next ``frames`` mono float32 samples (silence when ended)."""
        buf = self._buffer
        if buf is None or self._ended or buf.shape[0] == 0:
            return np.zeros(frames, dtype=np.float32)
        n = buf.shape[0]
        if self.loop:
            chunk = buf[np.arange(self._pos, self._pos + frames) % n]
            self._pos = (self._pos + frames) % n
        else:
            avail = min(frames, n - self._pos)
            chunk = np.zeros(frames, dtype=np.float32)
            chunk[:avail] = buf[self._pos : self._pos + avail]
            self._pos += avail
        # Per-sample fade envelope toward the target gain (attack up / release down).
        if self._gain_step != 0.0:
            gains = self._gain + self._gain_step * np.arange(
                1, frames + 1, dtype=np.float32
            )
            np.clip(gains, 0.0, 1.0, out=gains)
            self._gain = float(gains[-1])
            reached_up = self._gain_step > 0 and self._gain >= self._target
            reached_down = self._gain_step < 0 and self._gain <= self._target
            if reached_up or reached_down:
                self._gain = self._target
                self._gain_step = 0.0
            out = chunk * self.volume * gains
        else:
            out = chunk * (self.volume * self._gain)
        # Finished? A non-looping buffer ran out, or a release fade hit zero.
        if self._target == 0.0 and self._gain <= 0.0:
            self._ended = True
        elif not self.loop and self._pos >= n:
            self._ended = True
        return out.astype(np.float32, copy=False)


class LinearResampler:
    """Stateful, continuous linear resampler for a mono float32 stream.

    Bridges two independent audio streams running at different sample rates (the
    Talk mic and the participant output): ``push`` input samples at one rate,
    ``pull`` output samples at another. Linear interpolation is plenty for speech
    and is cheap enough for an audio callback. When the rates match it is a
    pass-through. On underrun ``pull`` returns zeros for the missing tail.
    """

    def __init__(self, in_rate: float, out_rate: float) -> None:
        if in_rate <= 0 or out_rate <= 0:
            raise ValueError("sample rates must be positive")
        self.step = in_rate / out_rate  # input samples consumed per output sample
        self._buf = np.zeros(0, dtype=np.float32)
        self._pos = 0.0  # fractional read position within ``_buf``

    def push(self, samples: np.ndarray) -> None:
        """Append mono input ``samples`` to the internal buffer."""
        self._buf = np.concatenate((self._buf, np.asarray(samples, dtype=np.float32)))

    def pull(self, n: int) -> np.ndarray:
        """Return ``n`` output samples; missing tail (underrun) is zero-filled."""
        out = np.zeros(n, dtype=np.float32)
        if len(self._buf) >= 2:
            positions = self._pos + np.arange(n) * self.step
            usable = positions <= len(self._buf) - 1
            count = int(np.count_nonzero(usable))
            if count:
                out[:count] = np.interp(
                    positions[:count], np.arange(len(self._buf)), self._buf
                ).astype(np.float32)
            # Advance only past what we actually produced, keeping the remainder.
            last = self._pos + count * self.step
            consumed = int(np.floor(last))
            self._buf = self._buf[consumed:]
            self._pos = last - consumed
        return out
