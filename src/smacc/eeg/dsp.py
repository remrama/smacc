"""Display filtering for the EEG review tool (#136).

The viewer filters only the *visible slice* of the recording, never the whole
file. ``mne.io.Raw.filter`` requires preloading the entire recording — an
overnight high-density file is gigabytes as float64 — while filtering the
fetched slice keeps memory flat regardless of file size (the approach EDF
browsers have used for decades). The trade-off is an edge transient at the
slice boundaries, handled by fetching a margin around the visible window
(:func:`pad_seconds`) that the view trims after filtering.

Zero-phase IIR (Butterworth via ``sosfiltfilt``) rather than MNE's default FIR:
zero phase means a filtered feature stays at its true time — annotations placed
on filtered traces must land where the event is in the raw data — and a 4th-
order IIR over a few seconds of slice is microseconds of work. This is a
*display* filter; it feeds nothing downstream, so publication-grade filter
choice is out of scope.

Pure numpy/scipy (already core dependencies), no MNE, no GUI.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache

import numpy as np
from scipy import signal

# 4th-order Butterworth: the conventional review-display filter — steep enough
# to clean a trace, gentle enough to never ring on K-complexes or slow waves.
_BUTTER_ORDER = 4
# iirnotch quality factor: ~2 Hz wide at 60 Hz, the usual mains-notch shape.
_NOTCH_Q = 30.0
# Filter edges at/above this fraction of Nyquist are dropped rather than
# designed: scipy raises on >= Nyquist, and a 70 Hz lowpass on a 128 Hz file
# should simply mean "no lowpass", not a crash (see effective_spec).
_NYQUIST_FRACTION = 0.99


@dataclass(frozen=True)
class FilterSpec:
    """The viewer's display-filter settings: band edges and mains notch, in Hz.

    ``highpass`` is the low *cut* (drop slow drift below it), ``lowpass`` the
    high cut — named for what they pass, the convention on every EEG review
    screen ("HP 0.3 Hz, LP 35 Hz"). ``None`` disables that stage; all three
    ``None`` (:data:`UNFILTERED`) bypasses filtering entirely.
    """

    highpass: float | None = None
    lowpass: float | None = None
    notch: float | None = None

    def __post_init__(self) -> None:
        for name in ("highpass", "lowpass", "notch"):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be positive (got {value})")
        if (
            self.highpass is not None
            and self.lowpass is not None
            and self.highpass >= self.lowpass
        ):
            raise ValueError(
                f"highpass ({self.highpass} Hz) must be below "
                f"lowpass ({self.lowpass} Hz)"
            )

    @property
    def is_identity(self) -> bool:
        """True when no filtering is requested at all."""
        return self.highpass is None and self.lowpass is None and self.notch is None


UNFILTERED = FilterSpec()


def effective_spec(spec: FilterSpec, sfreq: float) -> FilterSpec:
    """Return ``spec`` with stages the sampling rate can't support dropped.

    A stage whose edge sits at/above (a hair under) Nyquist is undesignable;
    treating it as disabled keeps one filter setting usable across files with
    different rates (the viewer remembers settings, files vary by amp).
    """
    limit = sfreq / 2 * _NYQUIST_FRACTION
    out = spec
    if out.lowpass is not None and out.lowpass >= limit:
        out = replace(out, lowpass=None)
    if out.notch is not None and out.notch >= limit:
        out = replace(out, notch=None)
    if out.highpass is not None and out.highpass >= limit:
        out = replace(out, highpass=None)
    return out


@lru_cache(maxsize=8)
def _design(spec: FilterSpec, sfreq: float) -> np.ndarray:
    """Design the cascaded SOS for ``spec`` at ``sfreq`` (cached per pair).

    The cache means scrolling re-filters with an already-designed filter; only
    changing the settings or opening a differently-rated file designs anew.
    Callers pass a spec already reduced by :func:`effective_spec` and not
    identity (there must be at least one stage to design).
    """
    sections: list[np.ndarray] = []
    if spec.highpass is not None and spec.lowpass is not None:
        sections.append(
            signal.butter(
                _BUTTER_ORDER,
                [spec.highpass, spec.lowpass],
                btype="bandpass",
                fs=sfreq,
                output="sos",
            )
        )
    elif spec.highpass is not None:
        sections.append(
            signal.butter(
                _BUTTER_ORDER, spec.highpass, btype="highpass", fs=sfreq, output="sos"
            )
        )
    elif spec.lowpass is not None:
        sections.append(
            signal.butter(
                _BUTTER_ORDER, spec.lowpass, btype="lowpass", fs=sfreq, output="sos"
            )
        )
    if spec.notch is not None:
        b, a = signal.iirnotch(spec.notch, _NOTCH_Q, fs=sfreq)
        sections.append(signal.tf2sos(b, a))
    return np.vstack(sections)


def apply(data: np.ndarray, sfreq: float, spec: FilterSpec) -> np.ndarray:
    """Zero-phase filter ``data`` (``(n_channels, n_samples)``) per ``spec``.

    Identity specs (including specs reduced to identity by the sampling rate)
    return ``data`` unchanged — same array, no copy. Slices too short to pad
    (a sliver at the end of a file) also pass through unfiltered rather than
    raising; a few unfilterable samples aren't worth crashing the view over.
    """
    spec = effective_spec(spec, sfreq)
    if spec.is_identity or data.size == 0:
        return data
    sos = _design(spec, sfreq)
    # sosfiltfilt's default pad length; inputs shorter than it can't be padded.
    padlen = 3 * (2 * len(sos) + 1)
    if data.shape[-1] <= padlen:
        return data
    return signal.sosfiltfilt(sos, data, axis=-1)


def pad_seconds(spec: FilterSpec) -> float:
    """The margin to fetch around the visible window before filtering.

    Filter transients are longest for the highpass (its time constant scales
    with 1/frequency: a 0.3 Hz cut rings for seconds), so the margin tracks it;
    a flat minimum covers the lowpass/notch. The view fetches this much extra
    on both sides and trims it after :func:`apply`, so edge artifacts never
    reach the screen.
    """
    if spec.highpass is None:
        return 1.0
    return max(1.0, 2.0 / spec.highpass)
