"""Tests for the pure visual-cue engine and light backends (no Qt, no hardware).

The engine never reads a clock — every call takes a timestamp — so envelopes,
patterns, and end conditions are checked here with hand-picked instants.
"""

from __future__ import annotations

import pytest

from smacc import lights

RED = (200, 100, 50)  # asymmetric components so channel mixups can't hide


def started(now: float = 0.0, **kwargs) -> lights.LightEngine:
    engine = lights.LightEngine()
    kwargs.setdefault("duration_s", 10.0)
    engine.start(now, RED, **kwargs)
    return engine


# ----- envelope + duration -----------------------------------------------------


def test_steady_frame_is_the_full_color_within_duration():
    engine = started(duration_s=2.0)
    assert engine.frame(1.0) == RED
    assert not engine.ended


def test_non_looping_cue_ends_at_duration_without_release():
    engine = started(duration_s=2.0)
    assert engine.frame(2.0) == (0, 0, 0)
    assert engine.ended


def test_zero_duration_cue_is_over_before_its_first_frame():
    engine = started(duration_s=0.0)
    assert engine.ended
    assert engine.frame(0.0) == (0, 0, 0)


def test_idle_engine_renders_black():
    engine = lights.LightEngine()
    assert engine.ended
    assert engine.frame(123.0) == (0, 0, 0)


def test_attack_ramps_the_gain_linearly():
    engine = started(attack_s=1.0)
    assert engine.frame(0.5) == (100, 50, 25)  # half-way up the ramp
    assert engine.frame(1.0) == RED  # ramp done


def test_duration_end_runs_the_release_fade():
    engine = started(duration_s=1.0, release_s=1.0)
    assert engine.frame(1.5) == (100, 50, 25)  # half-way down
    assert not engine.ended
    assert engine.frame(2.0) == (0, 0, 0)
    assert engine.ended


def test_manual_stop_releases_from_the_current_gain():
    # Stopped half-way through the attack: the release starts from gain 0.5 and
    # still spends the full release time getting to zero (CueMixer semantics).
    engine = started(attack_s=1.0, release_s=1.0)
    engine.stop(0.5)
    assert engine.frame(1.0) == (
        50,
        25,
        12,
    )  # 0.5 gain * 0.5 released (12.5 rounds even)
    assert not engine.ended
    assert engine.frame(1.5) == (0, 0, 0)
    assert engine.ended


def test_manual_stop_is_instant_without_a_release():
    engine = started()
    engine.stop(1.0)
    assert engine.ended
    assert engine.frame(1.0) == (0, 0, 0)


def test_loop_ignores_duration_until_stopped():
    engine = started(duration_s=1.0, loop=True)
    assert engine.frame(100.0) == RED
    assert not engine.ended
    engine.stop(100.5)
    assert engine.ended


def test_restart_replaces_a_playing_cue():
    engine = started(duration_s=1.0)
    engine.start(5.0, RED, duration_s=2.0)
    assert engine.frame(6.5) == RED  # timed from the new start
    assert not engine.ended


# ----- patterns ------------------------------------------------------------------


def test_pulse_is_a_raised_cosine_starting_dark():
    engine = started(pattern=lights.PULSE, rate_hz=1.0)
    assert engine.frame(0.0) == (0, 0, 0)  # trough: dark but not ended
    assert not engine.ended
    assert engine.frame(0.25) == (100, 50, 25)  # half brightness
    assert engine.frame(0.5) == RED  # peak
    assert engine.frame(1.0) == (0, 0, 0)  # next trough


def test_flash_is_a_half_duty_square_wave():
    engine = started(pattern=lights.FLASH, rate_hz=2.0)  # 0.5 s cycle
    assert engine.frame(0.1) == RED  # first half-cycle: on
    assert engine.frame(0.3) == (0, 0, 0)  # second half-cycle: off
    assert not engine.ended
    assert engine.frame(0.6) == RED  # next cycle


def test_zero_rate_degrades_to_steady():
    engine = started(pattern=lights.FLASH, rate_hz=0.0)
    assert engine.frame(0.3) == RED


def test_unknown_pattern_is_rejected():
    engine = lights.LightEngine()
    with pytest.raises(ValueError):
        engine.start(0.0, RED, duration_s=1.0, pattern="strobe")


def test_brightness_scales_the_color():
    engine = started(brightness=0.5)
    assert engine.frame(1.0) == (100, 50, 25)


# ----- backends -------------------------------------------------------------------


class _StubStick:
    """Records set_led_data calls like a blinkstick.BlinkStick would take them."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, list[int]]] = []

    def set_led_data(self, channel: int, data: list[int]) -> None:
        self.calls.append((channel, data))


def test_blinkstick_backend_sends_grb_triplets_for_every_led():
    stick = _StubStick()
    backend = lights.BlinkStickBackend(stick)
    backend.apply((1, 2, 3))
    channel, data = stick.calls[-1]
    assert channel == 0
    assert data == [2, 1, 3] * lights.BLINKSTICK_LED_COUNT  # G,R,B order
    backend.off()
    assert stick.calls[-1][1] == [0, 0, 0] * lights.BLINKSTICK_LED_COUNT


def test_resolve_blinkstick_blank_serial_is_none():
    assert lights.resolve_blinkstick("") is None


def test_resolve_blinkstick_wraps_a_found_device(monkeypatch):
    from blinkstick import blinkstick

    stick = _StubStick()
    monkeypatch.setattr(blinkstick, "find_by_serial", lambda serial: stick)
    backend = lights.resolve_blinkstick("BS123")
    assert backend is not None
    backend.apply((9, 8, 7))
    assert stick.calls  # the wrapped device got the frame


def test_resolve_blinkstick_swallows_enumeration_errors(monkeypatch):
    from blinkstick import blinkstick

    def boom(serial):
        raise OSError("usb went away")

    monkeypatch.setattr(blinkstick, "find_by_serial", boom)
    assert lights.resolve_blinkstick("BS123") is None
    monkeypatch.setattr(blinkstick, "find_by_serial", lambda serial: None)
    assert lights.resolve_blinkstick("BS123") is None
