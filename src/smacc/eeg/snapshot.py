"""Plain-data snapshot of the trace view for publication export (#180).

A frozen, numpy-only description of exactly what the view is drawing for one
window — already filtered, trimmed, and scaled into lane units — plus the
scaffolding (epoch boundaries, marks, time ticks) the exporter may keep or
strip. The view builds it (:meth:`smacc.eeg.view.TraceView.build_snapshot`); the
exporter (:mod:`smacc.eeg.export`) consumes it. No Qt, no pyqtgraph, no MNE and
no matplotlib here, so it is trivially constructable in a headless test —
mirroring the pure-module pattern of :mod:`smacc.eeg.dsp`/``annotations``/``profiles``.

Everything is **window-relative**: ``times`` and ``mark.onset`` have the window
start subtracted, so the exporter never needs to know where in the recording the
window sits, and clock time is carried as pre-rendered ``time_ticks`` strings so
the exporter never touches ``datetime``. ``trace.values`` is the lane-unit array
*centered on zero* (the exporter draws ``-lane + values``), i.e. exactly the
``scaled`` array the live view hands each curve — so the export is provably the
same picture the operator saw.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# eq=False on every dataclass: a numpy array field makes the generated __eq__
# ambiguous ("truth value of an array"), so tests compare fields explicitly.


@dataclass(frozen=True, eq=False)
class SnapshotTrace:
    """One channel's drawn trace, in display (lane) order."""

    name: str  # channel display name (left-axis label), e.g. "C3"
    ch_type: str  # MNE type ("eeg"/"eog"/"emg"/"stim"/…); for styling + #180b
    lane: int  # display row; baseline drawn at y = -lane
    values: (
        np.ndarray
    )  # 1-D float, lane units, centered on 0 (export draws -lane + values)
    scale_uv: float | None  # effective µV/lane for bioelectric channels; None for
    # auto-fit (stim/misc — arbitrary units, no µV calibration)


@dataclass(frozen=True, eq=False)
class SnapshotMark:
    """An annotation to draw on the figure (window-relative, already relabeled)."""

    onset: float  # seconds, window-relative (window_start already subtracted)
    duration: float  # seconds; 0 == an instantaneous point mark
    label: str  # clean, user-overridable text (defaults to the description)


@dataclass(frozen=True, eq=False)
class SnapshotEpoch:
    """One epoch boundary line."""

    x: float  # window-relative seconds of the boundary
    number: str  # epoch label as the grid shows it (k+1, stringified)


@dataclass(frozen=True, eq=False)
class Snapshot:
    """Everything the exporter needs for one window — pure data, no behavior."""

    times: np.ndarray  # 1-D window-relative seconds, shared x; starts at ~0
    window_seconds: float  # the x-axis spans [0, window_seconds]
    traces: tuple[SnapshotTrace, ...]  # display order, top lane (lane 0) first
    marks: tuple[SnapshotMark, ...] = ()  # window-filtered + relabeled; () => none
    epochs: tuple[SnapshotEpoch, ...] = ()  # () => no grid (caller passes () when off)
    time_ticks: tuple[tuple[float, str], ...] = ()  # (window-rel x, label); () => auto
    time_axis_label: str = "time (s)"  # "time (s)" or "clock time"
    sfreq: float = 0.0  # informational (titles / provenance)
    title: str = ""  # optional caption; "" => none
