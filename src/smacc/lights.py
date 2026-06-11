"""Visual cue engine and light-device backends.

The engine is the lights analog of audio's :class:`smacc.audio.CueMixer`: a pure
state machine (no Qt, no I/O) that renders the RGB frame a cue should show at any
caller-supplied clock instant. The GUI panel ticks it from a QTimer and pushes each
frame to a :class:`LightBackend`; tests drive it with hand-picked timestamps, so
patterns and envelopes are verifiable without hardware.

A cue is a *color* at a *brightness*, shaped by a *pattern* — ``steady``, a smooth
``pulse``, or an on/off ``flash`` at a rate in Hz — inside a linear attack/release
envelope (the visual counterpart of the audio board's fade-in/out). A non-looping
cue holds its pattern for ``duration_s`` and then releases on its own; a looping
cue runs until :meth:`LightEngine.stop`. Time is always passed in (a monotonic
timestamp), never read here, and pattern phase is computed from elapsed time — not
accumulated per tick — so a late or missed GUI tick can't drift the stimulus.
"""

from __future__ import annotations

import logging
import math
import threading
from typing import Protocol

_logger = logging.getLogger("smacc")

RGB = tuple[int, int, int]

# Cue patterns: constant light, a raised-cosine "breathing" pulse (starts dark,
# peaks mid-cycle, so onset is gentle), and a 50%-duty on/off flash.
STEADY = "steady"
PULSE = "pulse"
FLASH = "flash"
PATTERNS = (STEADY, PULSE, FLASH)


def _scale(component: int, gain: float) -> int:
    """One 0-255 color component scaled by ``gain``, rounded and clamped."""
    return max(0, min(255, round(component * gain)))


class LightEngine:
    """One-at-a-time visual cue renderer (the CueMixer of lights).

    :meth:`start` arms a cue; :meth:`frame` returns the RGB to show *now*;
    :meth:`stop` begins the release fade. :attr:`ended` flips once the envelope
    has reached zero (the duration ran out, or a release finished), so the GUI
    thread can turn the device off and mark the stop. Idle/ended frames are black.
    ``brightness`` and ``loop`` may be set live (read at the next frame), like
    ``CueMixer.volume``/``loop``.
    """

    def __init__(self) -> None:
        self._color: RGB = (0, 0, 0)
        self.brightness = 1.0
        self._pattern = STEADY
        self._rate_hz = 1.0
        self.loop = False
        self._duration_s = 0.0
        self._attack_s = 0.0
        self._release_s = 0.0
        self._t0 = 0.0
        # Manual-stop release: the time it began and the gain it started from
        # (a stop mid-attack releases from the part-way gain, like CueMixer).
        self._stop_t: float | None = None
        self._stop_gain = 0.0
        self._ended = True

    def start(
        self,
        now: float,
        color: RGB,
        *,
        brightness: float = 1.0,
        duration_s: float,
        loop: bool = False,
        pattern: str = STEADY,
        rate_hz: float = 1.0,
        attack_s: float = 0.0,
        release_s: float = 0.0,
    ) -> None:
        """Arm a cue starting at ``now`` (restarts any cue already playing)."""
        if pattern not in PATTERNS:
            raise ValueError(f"Unknown light pattern {pattern!r}; one of {PATTERNS}.")
        self._color = color
        self.brightness = brightness
        self._pattern = pattern
        self._rate_hz = rate_hz
        self.loop = loop
        self._duration_s = max(0.0, duration_s)
        self._attack_s = max(0.0, attack_s)
        self._release_s = max(0.0, release_s)
        self._t0 = now
        self._stop_t = None
        self._stop_gain = 0.0
        # A zero-length non-looping cue is over before its first frame.
        self._ended = self._duration_s <= 0.0 and not loop

    def stop(self, now: float) -> None:
        """Begin the release fade (end immediately when the release is 0)."""
        if self._ended or self._stop_t is not None:
            return
        if self._release_s <= 0.0:
            self._ended = True
            return
        self._stop_gain = self._envelope(now)
        self._stop_t = now
        if self._stop_gain <= 0.0:
            self._ended = True

    @property
    def ended(self) -> bool:
        """True once the cue has finished (duration ran out, or a release hit 0)."""
        return self._ended

    def frame(self, now: float) -> RGB:
        """Return the RGB to show at ``now`` (black when idle/ended)."""
        if self._ended:
            return (0, 0, 0)
        if self._stop_t is not None:
            done = now >= self._stop_t + self._release_s
        else:
            done = (
                not self.loop and now >= self._t0 + self._duration_s + self._release_s
            )
        if done:
            self._ended = True
            return (0, 0, 0)
        gain = self._envelope(now) * self.brightness * self._pattern_factor(now)
        r, g, b = self._color
        return (_scale(r, gain), _scale(g, gain), _scale(b, gain))

    def _envelope(self, now: float) -> float:
        """The attack/release gain in [0, 1] at ``now``."""
        if self._stop_t is not None:
            # Manual release: from the captured gain down to 0 over release_s.
            faded = 1.0 - (now - self._stop_t) / self._release_s
            return max(0.0, self._stop_gain * faded)
        t = now - self._t0
        gain = 1.0
        if self._attack_s > 0.0:
            gain = min(1.0, t / self._attack_s)
        if not self.loop and t > self._duration_s:
            # Natural release after the ON period (instant when release is 0).
            if self._release_s <= 0.0:
                return 0.0
            gain = min(gain, max(0.0, 1.0 - (t - self._duration_s) / self._release_s))
        return max(0.0, gain)

    def _pattern_factor(self, now: float) -> float:
        """The pattern's brightness factor in [0, 1] at ``now``."""
        if self._pattern == STEADY or self._rate_hz <= 0.0:
            return 1.0
        phase = ((now - self._t0) * self._rate_hz) % 1.0
        if self._pattern == FLASH:
            return 1.0 if phase < 0.5 else 0.0
        return 0.5 * (1.0 - math.cos(math.tau * phase))  # PULSE: raised cosine


class LightBackend(Protocol):
    """A light device that can show one color (all its LEDs together)."""

    def apply(self, rgb: RGB) -> None:
        """Show ``rgb`` now."""
        ...

    def off(self) -> None:
        """Turn the light fully off."""
        ...


# Every BlinkStick variant SMACC drives exposes up to 32 LEDs on channel 0; the
# whole strip gets one color (#11 documents per-LED color as a non-goal).
BLINKSTICK_LED_COUNT = 32


class BlinkStickBackend:
    """Drives one BlinkStick: the same color on all its LEDs.

    ``set_led_data`` expects G,R,B-ordered triplets, one per LED. USB-HID writes
    are fast enough for square-wave flashing, hence ``supports_flash``.
    """

    supports_flash = True

    def __init__(self, device) -> None:
        self._device = device

    def apply(self, rgb: RGB) -> None:
        r, g, b = rgb
        self._device.set_led_data(channel=0, data=[g, r, b] * BLINKSTICK_LED_COUNT)

    def off(self) -> None:
        self.apply((0, 0, 0))


def resolve_blinkstick(serial: str) -> BlinkStickBackend | None:
    """Wrap the connected BlinkStick with ``serial`` (None when blank/missing).

    The blinkstick import is local: the package is Windows-only and touches USB,
    so the engine half of this module stays importable (and testable) anywhere.
    A USB enumeration hiccup resolves to None rather than raising — the panel
    treats that the same as no device bound — but is logged, so a dead stick is
    distinguishable from an unbound one when debugging a rig.
    """
    if not serial:
        return None
    from blinkstick import blinkstick

    try:
        device = blinkstick.find_by_serial(serial)
    except Exception:
        _logger.warning(f"BlinkStick {serial!r} lookup failed", exc_info=True)
        return None
    return BlinkStickBackend(device) if device is not None else None


class FrameWriter:
    """Applies frames to a backend from its own thread (latest-frame-wins).

    A slow backend (the Hue bridge's ~100 ms HTTP writes) must not run on the GUI
    thread at the cue tick rate. The GUI submits the newest frame; the worker
    applies frames as fast as the backend absorbs them, always skipping to the
    latest (stale frames are dropped, never queued) and skipping duplicates — a
    steady cue costs one write, not thirty a second. The first write error stops
    the worker and is kept in :attr:`error` for the GUI to poll; :meth:`stop`
    joins the thread so the caller can then turn the light off in a known state.

    ``applied`` seeds the duplicate filter with a frame the caller already wrote
    synchronously (the cue's first frame, applied before its start marker).
    """

    def __init__(self, backend: LightBackend, applied: RGB | None = None) -> None:
        self._backend = backend
        self._cond = threading.Condition()
        self._latest: RGB | None = None
        self._applied = applied
        self._stopping = False
        self.error: str | None = None
        self._thread = threading.Thread(
            target=self._run, name="smacc-light-writer", daemon=True
        )
        self._thread.start()

    def submit(self, rgb: RGB) -> None:
        """Deposit the newest frame (the worker writes it when the device is free)."""
        with self._cond:
            self._latest = rgb
            self._cond.notify()

    def stop(self, timeout: float = 2.0) -> None:
        """Stop the worker and wait for any in-flight write to finish."""
        with self._cond:
            self._stopping = True
            self._cond.notify()
        self._thread.join(timeout)

    def _run(self) -> None:
        while True:
            with self._cond:
                while not self._stopping and (
                    self._latest is None or self._latest == self._applied
                ):
                    self._cond.wait()
                if self._stopping:
                    return
                frame = self._latest
            assert frame is not None  # the wait loop only exits with a fresh frame
            try:
                self._backend.apply(frame)  # outside the lock: possibly slow I/O
            except Exception as exc:
                self.error = str(exc) or type(exc).__name__
                return
            with self._cond:
                self._applied = frame
