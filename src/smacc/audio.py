"""Audio DSP helpers for SMACC's real-time streams (level meter, intercom).

Pure functions only — separated from the GUI so they are unit-testable without
audio hardware. The sounddevice streams that call these live in ``gui.py``.
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


class LinearResampler:
    """Stateful, continuous linear resampler for a mono float32 stream.

    Bridges two independent audio streams running at different sample rates (the
    intercom mic and the participant output): ``push`` input samples at one rate,
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
