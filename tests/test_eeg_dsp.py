"""Tests for the EEG display-filter math in :mod:`smacc.eeg.dsp` (#136, no GUI)."""

from __future__ import annotations

import numpy as np
import pytest

from smacc.eeg import dsp

SFREQ = 256.0


def _sine(freq: float, seconds: float = 20.0, sfreq: float = SFREQ) -> np.ndarray:
    t = np.arange(int(seconds * sfreq)) / sfreq
    return np.sin(2 * np.pi * freq * t)


def _amplitude_at(x: np.ndarray, freq: float, sfreq: float = SFREQ) -> float:
    """Single-bin amplitude of ``freq`` in ``x`` (test signals sit on exact bins)."""
    spectrum = np.abs(np.fft.rfft(x)) / (len(x) / 2)
    bin_hz = np.fft.rfftfreq(len(x), 1.0 / sfreq)
    return float(spectrum[int(np.argmin(np.abs(bin_hz - freq)))])


# ----- FilterSpec validation ------------------------------------------------


def test_spec_rejects_nonpositive_edges():
    with pytest.raises(ValueError, match="highpass"):
        dsp.FilterSpec(highpass=0)
    with pytest.raises(ValueError, match="lowpass"):
        dsp.FilterSpec(lowpass=-35)
    with pytest.raises(ValueError, match="notch"):
        dsp.FilterSpec(notch=0)


def test_spec_rejects_an_inverted_band():
    with pytest.raises(ValueError, match="below"):
        dsp.FilterSpec(highpass=35, lowpass=0.3)


def test_unfiltered_is_identity():
    assert dsp.UNFILTERED.is_identity
    assert not dsp.FilterSpec(notch=60).is_identity


# ----- effective_spec: rate-dependent reduction ------------------------------


def test_effective_spec_drops_edges_the_rate_cannot_support():
    # A 70 Hz lowpass on a 128 Hz file means "no lowpass", not a crash.
    spec = dsp.FilterSpec(highpass=0.3, lowpass=70.0, notch=60.0)
    eff = dsp.effective_spec(spec, 128.0)
    assert eff.lowpass is None
    assert eff.highpass == 0.3
    assert eff.notch == 60.0  # 60 < 0.99 * 64: still designable


def test_effective_spec_can_reduce_to_identity():
    assert dsp.effective_spec(dsp.FilterSpec(notch=60.0), 100.0).is_identity


def test_effective_spec_drops_an_unsupportable_highpass():
    # Absurd but possible: a 30 Hz highpass on a 50 Hz file. The pair survives
    # FilterSpec validation (30 < 35) yet neither edge is designable at fs=50.
    eff = dsp.effective_spec(dsp.FilterSpec(highpass=30.0, lowpass=35.0), 50.0)
    assert eff.is_identity


# ----- apply: the actual filtering -------------------------------------------


def test_identity_spec_returns_the_same_array():
    data = _sine(10.0)[np.newaxis, :]
    assert dsp.apply(data, SFREQ, dsp.UNFILTERED) is data


def test_bandpass_keeps_the_band_and_removes_drift():
    # 10 Hz signal riding on a big slow drift: the standard sleep display
    # (HP 0.3 / LP 35) must keep the signal and flatten the drift.
    x = _sine(10.0) + 5.0 * _sine(0.05)
    out = dsp.apply(x[np.newaxis, :], SFREQ, dsp.FilterSpec(highpass=0.3, lowpass=35.0))
    assert _amplitude_at(out[0], 10.0) == pytest.approx(1.0, abs=0.05)
    assert _amplitude_at(out[0], 0.05) < 0.25  # was 5.0


def test_highpass_alone_removes_drift_and_keeps_the_signal():
    x = _sine(10.0) + 5.0 * _sine(0.05)
    out = dsp.apply(x[np.newaxis, :], SFREQ, dsp.FilterSpec(highpass=0.5))
    assert _amplitude_at(out[0], 10.0) == pytest.approx(1.0, abs=0.05)
    assert _amplitude_at(out[0], 0.05) < 0.25  # was 5.0


def test_lowpass_removes_high_frequency_noise():
    x = _sine(10.0) + _sine(80.0)
    out = dsp.apply(x[np.newaxis, :], SFREQ, dsp.FilterSpec(lowpass=35.0))
    assert _amplitude_at(out[0], 10.0) == pytest.approx(1.0, abs=0.05)
    assert _amplitude_at(out[0], 80.0) < 0.01


def test_notch_removes_mains_and_little_else():
    x = _sine(10.0) + _sine(60.0)
    out = dsp.apply(x[np.newaxis, :], SFREQ, dsp.FilterSpec(notch=60.0))
    assert _amplitude_at(out[0], 60.0) < 0.05
    assert _amplitude_at(out[0], 10.0) == pytest.approx(1.0, abs=0.05)


def test_filtering_is_zero_phase():
    # Annotations are placed on the filtered trace but must land where the
    # event is in the raw data — a filtered transient may not move in time.
    # (A single Gaussian bump has one unambiguous peak; a sine's many equal
    # peaks would make argmax arbitrary.)
    t = np.arange(int(20.0 * SFREQ)) / SFREQ
    x = np.exp(-((t - 10.0) ** 2) / (2 * 0.5**2))  # bump centered at 10 s
    out = dsp.apply(x[np.newaxis, :], SFREQ, dsp.FilterSpec(lowpass=30.0))[0]
    assert abs(int(np.argmax(out)) - int(np.argmax(x))) <= 1


def test_multichannel_filtering_treats_channels_independently():
    data = np.vstack([_sine(10.0), _sine(60.0)])
    out = dsp.apply(data, SFREQ, dsp.FilterSpec(notch=60.0))
    assert out.shape == data.shape
    assert _amplitude_at(out[0], 10.0) == pytest.approx(1.0, abs=0.05)  # untouched
    assert _amplitude_at(out[1], 60.0) < 0.05  # notched


def test_a_sliver_too_short_to_pad_passes_through():
    data = np.ones((2, 5))
    out = dsp.apply(data, SFREQ, dsp.FilterSpec(lowpass=35.0))
    assert out is data


def test_empty_slice_passes_through():
    data = np.empty((4, 0))
    assert dsp.apply(data, SFREQ, dsp.FilterSpec(lowpass=35.0)) is data


def test_filter_design_is_cached_per_spec_and_rate():
    spec = dsp.FilterSpec(highpass=0.3, lowpass=35.0)
    assert dsp._design(spec, SFREQ) is dsp._design(dsp.FilterSpec(0.3, 35.0), SFREQ)


# ----- pad_seconds ------------------------------------------------------------


def test_pad_scales_with_the_highpass_time_constant():
    assert dsp.pad_seconds(dsp.FilterSpec(highpass=0.3)) == pytest.approx(2.0 / 0.3)
    assert dsp.pad_seconds(dsp.FilterSpec(highpass=10.0)) == 1.0  # floor
    assert dsp.pad_seconds(dsp.UNFILTERED) == 1.0
