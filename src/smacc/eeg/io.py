"""Recording access for the EEG review tool — the only module that touches MNE (#136).

MNE is strictly a *backend* here: it reads the formats (EDF, BrainVision, FIF —
the formats sleep-lab amps actually produce) and exposes their metadata;
rendering is pyqtgraph and filtering is :mod:`smacc.eeg.dsp`. The review tool
itself only ever *writes* the TSV/JSON sidecar (:mod:`smacc.eeg.annotations`) —
the source recording is never modified. The import is lazy so probing
this package costs nothing, and recordings are opened with ``preload=False`` so
an overnight file is memory-mapped and fetched slice-by-slice — never loaded
whole (see the dsp module docstring for why).

:class:`Recording` is the thin contract the viewer draws from (names, types,
rate, duration, ``get_slice``); tests fake it without MNE.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from .annotations import Annotation

if TYPE_CHECKING:  # only for annotations; mne itself is imported lazily
    import mne

# Suffix → the mne.io reader that opens it; the single source of truth for what
# the tool can open, so adding a format is a one-line change (the dialog filter
# and the unsupported-type error both derive from it). BrainVision recordings
# are a triplet (.vhdr/.eeg/.vmrk) opened via the header file; EEGLAB .set may
# store its data in a sibling .fdt, and only *continuous* .set files are
# supported — an epoched .set raises in MNE, surfaced verbatim by open_recording.
_READERS = {
    ".edf": "read_raw_edf",
    ".vhdr": "read_raw_brainvision",
    ".fif": "read_raw_fif",
    ".cnt": "read_raw_cnt",
    ".set": "read_raw_eeglab",
}

# Qt file-dialog filter, built from the reader table so it never drifts from it.
FILE_FILTER = (
    "EEG recordings (" + " ".join(f"*{ext}" for ext in _READERS) + ");;All files (*)"
)

# Label for embedded events that arrive without one (rare, but EDF+ allows it);
# the Annotation model rejects empty descriptions, and inventing nothing is
# worse than naming the gap.
_UNLABELED = "unlabeled"


class Recording:
    """An open recording: its metadata, and data fetched per visible slice."""

    def __init__(self, raw: mne.io.BaseRaw, path: Path) -> None:
        self._raw = raw
        self.path = path

    @property
    def ch_names(self) -> list[str]:
        return list(self._raw.ch_names)

    @property
    def ch_types(self) -> list[str]:
        """Per-channel kind ("eeg", "eog", "emg", …) as MNE classified them."""
        return list(self._raw.get_channel_types())

    @property
    def sfreq(self) -> float:
        return float(self._raw.info["sfreq"])

    @property
    def duration(self) -> float:
        """Total data span in seconds (the valid range for slices and annotations)."""
        return self._raw.n_times / self.sfreq

    @property
    def meas_date(self) -> datetime | None:
        """The recording's absolute start time, when the file carries one.

        Lets the viewer show clock time — how sleep techs think ("the arousal
        at 03:12"), and how a night's SMACC log is cross-referenced — alongside
        seconds-from-start. ``None`` when the format or anonymization dropped it.
        """
        return self._raw.info["meas_date"]

    def get_slice(self, start_s: float, stop_s: float) -> tuple[Any, Any]:
        """Return ``(times, data)`` for the span, clamped to the recording.

        ``times`` is seconds from data start (the annotation timebase); ``data``
        is ``(n_channels, n_samples)`` float64 in the file's units (SI — volts
        for bioelectric channels; display scaling is the view's job). A span
        entirely outside the recording yields empty arrays rather than raising,
        so a scrolled-past-the-end view simply draws nothing.
        """
        sfreq = self.sfreq
        start = max(0, int(round(max(0.0, start_s) * sfreq)))
        stop = min(self._raw.n_times, int(round(min(self.duration, stop_s) * sfreq)))
        if stop <= start:
            return np.empty(0), np.empty((len(self._raw.ch_names), 0))
        data, times = self._raw.get_data(start=start, stop=stop, return_times=True)
        return times, data


def open_recording(path: str | Path) -> Recording:
    """Open ``path`` (dispatched on suffix) without preloading its data.

    Raises:
        ValueError: for a suffix no reader claims.
        OSError, RuntimeError: from MNE, for a file that exists but won't parse
            (the window shows these verbatim — amp-specific corruption messages
            are more useful than a generic wrapper).
    """
    import mne

    src = Path(path)
    reader_name = _READERS.get(src.suffix.lower())
    if reader_name is None:
        supported = " ".join(sorted(_READERS))
        raise ValueError(
            f"Unsupported recording type {src.suffix!r} (supported: {supported})"
        )
    reader = getattr(mne.io, reader_name)
    raw = reader(src, preload=False, verbose="error")
    return Recording(raw, src)


def embedded_annotations(recording: Recording) -> list[Annotation]:
    """Return events already stored in the file as data-relative annotations.

    Files from amp software routinely carry event markers — including SMACC's
    own portcode triggers — and a reviewer expects to see them alongside their
    new marks. Converted to this package's model so they save into the sidecar
    like any other annotation.

    MNE's onsets are relative to ``orig_time`` when one is set (so the data
    offset ``first_time`` must come off) and data-relative when it is ``None``
    — the documented ``mne.Annotations`` semantics. Events that land outside
    the data span after correction (possible on cropped files) are dropped.
    """
    raw = recording._raw
    duration = recording.duration
    shift = raw.first_time if raw.annotations.orig_time is not None else 0.0
    out: list[Annotation] = []
    for onset, length, description in zip(
        raw.annotations.onset,
        raw.annotations.duration,
        raw.annotations.description,
        strict=True,
    ):
        data_onset = float(onset) - shift
        if data_onset < 0 or data_onset > duration:
            continue
        # Normalize the same way the model will, so a whitespace-only label
        # falls back to _UNLABELED instead of tripping the model's own
        # empty-description check and aborting the whole conversion.
        label = " ".join(str(description).split()) or _UNLABELED
        out.append(Annotation(data_onset, float(length), label))
    return sorted(out)
