"""Tests for the audio DSP helpers (no hardware required)."""

import numpy as np
import pytest

from smacc import audio


def test_full_scale_sine_is_about_minus_3_db():
    t = np.linspace(0, 1, 44100, endpoint=False)
    sine = np.sin(2 * np.pi * 440 * t).astype(np.float32)
    # RMS of a full-scale sine is 1/sqrt(2) -> ~ -3.01 dBFS.
    assert audio.rms_dbfs(sine) == pytest.approx(-3.01, abs=0.1)


def test_silence_clamps_to_floor():
    assert audio.rms_dbfs(np.zeros(1024, dtype=np.float32)) == audio.FLOOR_DBFS
    assert audio.rms_dbfs(np.array([], dtype=np.float32)) == audio.FLOOR_DBFS


def test_rms_dbfs_never_below_floor():
    tiny = np.full(256, 1e-9, dtype=np.float32)
    assert audio.rms_dbfs(tiny) == audio.FLOOR_DBFS


def test_resampler_passthrough_when_rates_match():
    r = audio.LinearResampler(48000, 48000)
    block = np.linspace(-1, 1, 1024, dtype=np.float32)
    r.push(block)
    out = r.pull(1024)
    # Equal rates -> interpolation at integer positions reproduces the input.
    assert np.allclose(out, block, atol=1e-5)


def test_resampler_downsample_length_ratio():
    # 48k -> 24k: pulling N outputs should consume ~2N inputs over time.
    r = audio.LinearResampler(48000, 24000)
    r.push(np.ones(4000, dtype=np.float32))
    out = r.pull(2000)
    assert out.shape == (2000,)
    assert np.allclose(out, 1.0, atol=1e-5)  # constant signal stays constant


def test_resampler_underrun_zero_fills():
    r = audio.LinearResampler(48000, 48000)
    r.push(np.ones(100, dtype=np.float32))
    out = r.pull(500)
    assert out[:90].min() == pytest.approx(1.0, abs=1e-5)
    assert out[-1] == 0.0  # tail beyond available input is zero


def test_resampler_rejects_bad_rates():
    with pytest.raises(ValueError):
        audio.LinearResampler(0, 48000)


def test_meter_mapping_endpoints_and_clamp():
    assert audio.dbfs_to_meter(0.0) == 100
    assert audio.dbfs_to_meter(audio.METER_FLOOR_DBFS) == 0
    assert audio.dbfs_to_meter(-1000.0) == 0  # clamped


def test_ambient_baseline_tracks_a_quiet_floor():
    base = audio.AmbientBaseline()
    for _ in range(50):
        base.update(-70.0)  # steady quiet room
    assert base.floor == pytest.approx(-70.0, abs=0.5)


def test_ambient_baseline_reports_rise_for_a_cue_above_the_floor():
    base = audio.AmbientBaseline()
    for _ in range(50):
        base.update(-70.0)  # settle the floor at the room noise
    rise = base.update(-40.0)  # a cue lifts the level 30 dB
    assert rise == pytest.approx(30.0, abs=1.0)


def test_ambient_baseline_drops_instantly_to_a_quieter_level():
    base = audio.AmbientBaseline()
    base.update(-40.0)
    base.update(-80.0)  # quieter than the floor -> snaps down immediately
    assert base.floor == pytest.approx(-80.0, abs=0.01)


def test_ambient_baseline_floor_creeps_up_under_sustained_sound():
    base = audio.AmbientBaseline(creep_db_per_update=0.15)
    base.update(-70.0)  # floor starts low
    for _ in range(100):  # a sustained louder sound
        base.update(-40.0)
    # The floor adapts upward toward the sustained level (so the rise shrinks).
    assert base.floor > -70.0
    assert base.update(-40.0) < 30.0


def test_ambient_baseline_reset_forgets_the_floor():
    base = audio.AmbientBaseline()
    base.update(-30.0)
    base.reset()
    assert base.floor == audio.FLOOR_DBFS
    assert audio.dbfs_to_meter(50.0) == 100  # clamped
    midpoint = audio.METER_FLOOR_DBFS / 2
    assert audio.dbfs_to_meter(midpoint) == 50


# ----- CueMixer -------------------------------------------------------------


def test_cuemixer_idle_renders_silence():
    m = audio.CueMixer()
    assert m.ended  # nothing started
    assert np.array_equal(m.render(64), np.zeros(64, dtype=np.float32))


def test_cuemixer_plays_buffer_scaled_by_volume():
    m = audio.CueMixer()
    m.start(np.ones(100, dtype=np.float32), volume=0.5)
    out = m.render(50)
    assert np.allclose(out, 0.5)
    assert not m.ended


def test_cuemixer_nonloop_ends_after_buffer_then_silence():
    m = audio.CueMixer()
    m.start(np.ones(80, dtype=np.float32))
    m.render(80)  # consume the whole buffer
    assert m.ended
    assert np.array_equal(m.render(16), np.zeros(16, dtype=np.float32))


def test_cuemixer_loop_wraps_and_never_ends():
    m = audio.CueMixer()
    m.start(np.arange(4, dtype=np.float32), loop=True)  # 0,1,2,3
    out = m.render(10)
    assert not m.ended
    assert np.allclose(out, [0, 1, 2, 3, 0, 1, 2, 3, 0, 1])


def test_cuemixer_attack_ramps_in_then_reaches_unity():
    m = audio.CueMixer()
    m.start(np.ones(1000, dtype=np.float32), attack_samples=100)
    out = m.render(100)
    assert out[0] < out[-1]  # rising envelope
    assert out[0] == pytest.approx(0.01, abs=0.02)
    assert m.render(10)[0] == pytest.approx(1.0, abs=1e-6)  # unity after the attack


def test_cuemixer_release_fades_then_ends():
    m = audio.CueMixer()
    m.start(np.ones(10000, dtype=np.float32))
    m.render(10)  # playing at unity
    m.stop(release_samples=100)
    out = m.render(100)
    assert out[0] > out[-1]  # falling envelope
    assert out[-1] == pytest.approx(0.0, abs=1e-6)
    assert m.ended


def test_cuemixer_instant_stop_ends_immediately():
    m = audio.CueMixer()
    m.start(np.ones(1000, dtype=np.float32))
    m.stop(release_samples=0)
    assert m.ended
    assert np.array_equal(m.render(16), np.zeros(16, dtype=np.float32))


def test_cuemixer_empty_buffer_is_ended():
    m = audio.CueMixer()
    m.start(np.zeros(0, dtype=np.float32))
    assert m.ended
