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
    assert audio.dbfs_to_meter(50.0) == 100  # clamped
    midpoint = audio.METER_FLOOR_DBFS / 2
    assert audio.dbfs_to_meter(midpoint) == 50
