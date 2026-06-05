"""Tests for the pure helpers in :mod:`smacc.utils`."""

from __future__ import annotations

import numpy as np
import pytest
from scipy.io.wavfile import read, write

from smacc import utils


def test_note_returns_int16_of_expected_length():
    rate = 8000
    duration = 1
    data = utils.note(freq=440, duration=duration, amp=1e4, rate=rate)
    assert data.dtype == np.int16
    assert data.shape == (duration * rate,)
    assert np.all(np.isfinite(data))


@pytest.mark.parametrize(
    "noise_func",
    [
        utils.white_noise,
        utils.pink_noise,
        utils.brownian_noise,
        utils.blue_noise,
        utils.violet_noise,
    ],
)
def test_noise_generators_produce_finite_samples(noise_func):
    n = 4096
    samples = noise_func(n)
    assert isinstance(samples, np.ndarray)
    # irfft of an (n // 2 + 1) spectrum yields n real samples.
    assert samples.shape == (n,)
    assert np.all(np.isfinite(samples))


def test_get_data_directory_uses_env_var(tmp_path, monkeypatch):
    target = tmp_path / "smacc_data"
    monkeypatch.setenv("SMACC_DATA_DIRECTORY", str(target))
    result = utils.get_data_directory()
    assert result == target
    assert result.is_dir()


def test_wav_round_trip(tmp_path):
    rate = 8000
    tone = utils.note(freq=261.63, duration=1, amp=1e4, rate=rate)
    wav_path = tmp_path / "tone.wav"
    write(wav_path, rate, tone)
    read_rate, read_data = read(wav_path)
    assert read_rate == rate
    np.testing.assert_array_equal(read_data, tone)
