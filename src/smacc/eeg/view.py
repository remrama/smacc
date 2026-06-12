"""The multichannel trace view for the EEG review tool (#136).

One pyqtgraph ``PlotWidget``, all channels stacked in a single ViewBox by
vertical offset (channel *i* centered at ``y = -i``), channel names as y-axis
ticks — not one ViewBox per channel, which is slow to sync and slow to draw.
Performance comes from rendering only the visible window (fetched per scroll,
filtered by :mod:`smacc.eeg.dsp`, never the whole file) and from pyqtgraph's
min/max *peak* downsampling on each curve, which keeps extremes — a spindle or
artifact stays visible no matter how far the trace is decimated. Deliberately
no OpenGL: pyqtgraph's raster path plus downsampling is the proven approach
(it is what mne-qt-browser ships with; the GL option is off by default there
for Windows driver reasons).

Interaction is built for annotation, not navigation: a left-drag *draws* a
region (it never pans), a click selects the annotation under the cursor, and
the wheel scrolls time. Paging/zoom shortcuts and every other control live in
:mod:`smacc.eeg.window`, which owns this widget.

The view draws from any :class:`SliceProvider` — :class:`smacc.eeg.io.Recording`
in the app, a synthetic fake in tests and benchmarks — so this module imports
no MNE and nothing from the wider app.
"""

from __future__ import annotations

import bisect
import math
from datetime import datetime, timedelta
from typing import Any, NamedTuple, Protocol

import numpy as np
import pyqtgraph as pg
from PyQt6 import QtCore, QtGui

from . import dsp
from .annotations import Annotation
from .snapshot import Snapshot, SnapshotEpoch, SnapshotMark, SnapshotTrace

# Bioelectric channels are recorded in volts and displayed in microvolts.
# Other kinds (stim/misc/…) carry arbitrary units — a trigger channel holds
# integer event codes like 255, which on a 100 µV lane scale would paint
# straight across every EEG lane — so they are auto-fit into their own lane
# per visible slice instead (see _refresh_data).
_MICROVOLT_TYPES = {"eeg", "eog", "emg", "ecg", "seeg", "ecog", "dbs", "bio"}
_VOLTS_TO_MICROVOLTS = 1e6
# Lane-units excursion an auto-fit (non-bioelectric) channel is normalized to.
_AUTOFIT_EXCURSION = 0.4

# Default amplitude (µV per channel lane) and the per-type overrides applied on
# top of it. EMG rides hotter than EEG on most montages, so it defaults to a
# larger µV/lane (a smaller on-screen trace); every type is now overridable per
# montage (#177) — these are only the starting points. (200 µV reproduces the
# old EMG ×0.5 gain against the 100 µV base.)
DEFAULT_BASE_SCALE_UV = 100.0
DEFAULT_TYPE_SCALES = {"emg": 200.0}

# Clicking selects the annotation under the cursor; a zero-duration mark gets
# this much slack on each side, as a fraction of the visible window.
_CLICK_TOLERANCE_FRACTION = 0.005

# Annotation paint: translucent fills so traces stay readable through them.
_REGION_BRUSH = (70, 130, 180, 50)  # steel blue wash
_REGION_BRUSH_SELECTED = (70, 130, 180, 110)
_REGION_PEN = (70, 130, 180, 160)
_LINE_PEN = (178, 34, 34, 160)  # firebrick for instantaneous marks
_LINE_PEN_SELECTED = (178, 34, 34, 255)

# Other raters' marks (#181d) are drawn read-only *behind* the editable layer,
# one distinct colour per rater (Okabe–Ito, chosen to avoid the steel-blue/
# firebrick of the operator's own marks and to stay colourblind-distinguishable).
OVERLAY_COLORS: tuple[tuple[int, int, int], ...] = (
    (230, 159, 0),  # orange
    (0, 158, 115),  # bluish green
    (204, 121, 167),  # reddish purple
    (213, 94, 0),  # vermillion
    (86, 180, 233),  # sky blue
    (240, 228, 66),  # yellow
)
# Read-only overlay marks sit above the curves/epochs but below the editable
# layer (z 10), so a rater's own marks always render on top of their peers'.
_OVERLAY_Z = 5

# Epoch gridlines: a faint dashed grey so the boundaries read as background
# scaffolding behind the traces, never competing with the firebrick marks.
_EPOCH_PEN = pg.mkPen((128, 128, 128, 110), width=1, style=QtCore.Qt.PenStyle.DashLine)
_EPOCH_LABEL_COLOR = (128, 128, 128, 200)
# The standard polysomnography scoring epoch; the sleep default everywhere.
DEFAULT_EPOCH_SECONDS = 30.0

# Session-log overlay (#125): the parsed log is drawn as a read-only reference
# track in a thin lane across the top of the plot, kept clear of the traces and
# the editable/peer marks below it. A log mark is an instantaneous tick spanning
# only this lane (the top _LOG_LANE_FRAC..1.0 of the viewbox height), so a
# left-drag that starts up here slides the whole log instead of drawing a span.
_LOG_LANE_FRAC = 0.92
# Per-level tick colour, keyed by logging level name. Markers (INFO) are the
# common case and read in a calm slate; warnings/errors escalate to amber/red so
# a mid-session fault stands out even as reference context. z below the peer
# overlays (5) and editable marks (10), above the epoch grid (2).
_LOG_LEVEL_COLORS: dict[str, tuple[int, int, int]] = {
    "DEBUG": (150, 150, 150),
    "INFO": (70, 90, 130),
    "WARNING": (200, 150, 0),
    "ERROR": (200, 60, 60),
    "CRITICAL": (200, 60, 60),
}
_LOG_DEFAULT_COLOR = (70, 90, 130)
_LOG_Z = 4


class LogMark(NamedTuple):
    """One session-log entry placed on the EEG timeline for the overlay (#125).

    ``seconds`` is the data-second the entry aligns to (the window computes it
    from the log time, the recording origin, and the clock-skew offset);
    ``level`` selects the tick colour; ``tooltip`` is the hover text (clock time,
    level, and the log message). Read-only — the view never selects or edits it.
    """

    seconds: float
    level: str
    tooltip: str


class RaterOverlay(NamedTuple):
    """One other rater's marks drawn read-only behind the editable layer (#181d).

    ``color`` is the rater's legend colour (RGB); ``visible`` lets the window
    show/hide a rater without rebuilding the data.
    """

    rater_id: str
    annotations: list[Annotation]
    color: tuple[int, int, int]
    visible: bool = True


class TimeAxis(pg.AxisItem):
    """Bottom axis that labels x (data seconds) as elapsed time or wall clock.

    The tick *positions* stay in data seconds (pyqtgraph picks them); only the
    strings change. Clock mode needs an ``origin`` datetime — the recording's
    localized start, computed format-aware in :func:`smacc.eeg.window.wall_time`
    and handed down here, so this axis stays free of MNE and format quirks.
    Falls back to elapsed seconds whenever no origin is known (anonymized files).
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._mode = "elapsed"
        self._origin: datetime | None = None
        self.setLabel("time (s)")

    def set_mode(self, mode: str) -> None:
        """Switch between ``"clock"`` and ``"elapsed"`` tick labels."""
        self._mode = mode
        self.setLabel("clock time" if mode == "clock" else "time (s)")
        self.picture = None  # drop the cached render so tickStrings re-runs
        self.update()

    def set_origin(self, origin: datetime | None) -> None:
        """Set the wall-clock instant of data-second 0 (``None`` disables clock)."""
        self._origin = origin
        self.picture = None
        self.update()

    @property
    def mode(self) -> str:
        """``"clock"`` or ``"elapsed"`` — which kind of tick label is shown."""
        return self._mode

    def tick_label(self, value: float) -> str:
        """Format one x value the way the axis labels it (clock or elapsed seconds).

        Shared with the figure export (#180) so a snapshot's time ticks read
        exactly like the screen's, without re-deriving the clock formatting.
        """
        if self._mode == "clock" and self._origin is not None:
            return (self._origin + timedelta(seconds=float(value))).strftime("%H:%M:%S")
        return f"{value:g}"

    def tickStrings(
        self, values: list[float], scale: float, spacing: float
    ) -> list[str]:
        if self._mode == "clock" and self._origin is not None:
            return [self.tick_label(float(v)) for v in values]
        return super().tickStrings(values, scale, spacing)


class SliceProvider(Protocol):
    """What the view needs from a recording (satisfied by ``io.Recording``)."""

    @property
    def ch_names(self) -> list[str]: ...

    @property
    def ch_types(self) -> list[str]: ...

    @property
    def sfreq(self) -> float: ...

    @property
    def duration(self) -> float: ...

    def get_slice(self, start_s: float, stop_s: float) -> tuple[Any, Any]: ...


class _AnnotateViewBox(pg.ViewBox):
    """A ViewBox where the left mouse annotates instead of panning.

    Pan/zoom-by-mouse is disabled outright: a misdrag that silently shifts the
    time axis would make the operator distrust where their annotations landed.
    Dragging rubber-bands a span (live region preview, then ``dragFinished``);
    a plain click reports its time so the view can select/deselect.
    """

    dragFinished = QtCore.pyqtSignal(float, float)  # span in data seconds
    clicked = QtCore.pyqtSignal(float)  # click time in data seconds
    markRequested = QtCore.pyqtSignal(float)  # ctrl-click: drop a point mark here
    logSlideStarted = QtCore.pyqtSignal()  # a log-lane drag began (#125)
    logSlideMoved = QtCore.pyqtSignal(float)  # live log-lane drag delta (seconds)
    logSlideFinished = QtCore.pyqtSignal(float)  # log-lane drag released (seconds)

    def __init__(self) -> None:
        super().__init__(enableMouse=False, enableMenu=False)
        self._preview: pg.LinearRegionItem | None = None
        # When a session log is overlaid (#125), a drag that *starts* in its top
        # lane slides the log instead of drawing a span. Off by default, so with
        # no log loaded the whole plot draws annotations as before.
        self._log_lane_active = False
        self._sliding = False
        # Pick mode (#125 manual alignment): every gesture only reports a time
        # to pair with a log entry — no span is drawn, no mark dropped — so an
        # accidental drag while aiming can't edit the rater's own annotations.
        self._pick_active = False

    def set_log_lane_active(self, active: bool) -> None:
        """Enable the top-lane log slide (only while a log overlay is loaded)."""
        self._log_lane_active = active
        if not active:
            self._sliding = False  # never strand a slide when the lane is dropped

    def set_pick_active(self, active: bool) -> None:
        """Enter/leave pick mode: gestures only pick a time, never edit marks."""
        self._pick_active = active

    def _in_log_lane(self, local_pos: Any) -> bool:
        """True if ``local_pos`` (item coords) is in the top log lane."""
        rect = self.boundingRect()
        return (local_pos.y() - rect.top()) <= rect.height() * (1.0 - _LOG_LANE_FRAC)

    def mouseDragEvent(self, ev: Any, axis: int | None = None) -> None:
        if ev.button() != QtCore.Qt.MouseButton.LeftButton:
            ev.ignore()
            return
        ev.accept()
        # In pick mode a drag must not draw a span or slide — the whole gesture
        # is reserved for picking a time (the click path reports it). Swallow it.
        if self._pick_active:
            return
        start = float(self.mapToView(ev.buttonDownPos()).x())
        current = float(self.mapToView(ev.pos()).x())
        # Decide the gesture once, at the drag's start, and hold it: a drag that
        # began in the log lane slides the log for its whole duration even as the
        # cursor leaves the lane.
        if ev.isStart():
            self._sliding = self._log_lane_active and self._in_log_lane(
                ev.buttonDownPos()
            )
            if self._sliding:
                self.logSlideStarted.emit()  # the window re-bases its offset here
        if self._sliding:
            delta = current - start
            if ev.isFinish():
                self._sliding = False
                self.logSlideFinished.emit(delta)
            else:
                self.logSlideMoved.emit(delta)
            return
        lo, hi = sorted((start, current))
        if self._preview is None:
            self._preview = pg.LinearRegionItem(
                values=(lo, hi), movable=False, brush=_REGION_BRUSH
            )
            self._preview.setZValue(20)
            self.addItem(self._preview)
        self._preview.setRegion((lo, hi))
        if ev.isFinish():
            self.removeItem(self._preview)
            self._preview = None
            self.dragFinished.emit(lo, hi)

    def mouseClickEvent(self, ev: Any) -> None:
        if ev.button() != QtCore.Qt.MouseButton.LeftButton:
            ev.ignore()
            return
        ev.accept()
        seconds = float(self.mapToView(ev.pos()).x())
        # In pick mode every click (modifier or not) just reports its time; the
        # ctrl-modifier never drops a mark while the rater is aiming an alignment.
        if self._pick_active:
            self.clicked.emit(seconds)
            return
        # Ctrl+click drops a point mark; a plain click selects. The modifier
        # keeps the frequent selection-click from ever creating stray markers.
        if ev.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier:
            self.markRequested.emit(seconds)
        else:
            self.clicked.emit(seconds)


class _LaneTrace(NamedTuple):
    """One drawn channel as :meth:`TraceView._lane_traces` returns it.

    ``values`` is the lane-unit array centered on 0 (the curve draws
    ``-lane + values``); ``scale_uv`` is the µV/lane used for a bioelectric
    channel, ``None`` for the auto-fit (stim/misc) branch.
    """

    lane: int
    channel: int
    ch_type: str
    values: np.ndarray
    scale_uv: float | None


class TraceView(pg.PlotWidget):
    """Stacked-channel trace display with drag-to-annotate.

    Owns the display state (window position/length, filter spec, amplitude
    scale, the annotation list and selection) and emits user intent upward:

    * ``regionDrawn(start, stop)`` — a drag finished; the window asks for a label.
    * ``annotationSelected(index)`` — click selected an annotation (-1: none).
    * ``windowChanged(start)`` — the view scrolled itself (mouse wheel), so the
      window can sync its scrollbar.
    * ``cursorMoved(seconds)`` — mouse position, for the status-bar clock.
    * ``pointMarkRequested(seconds)`` — ctrl-click asked for a point mark here.
    * ``logSlideMoved/Finished(delta)`` — a drag in the log lane is sliding/has
      slid the overlay by ``delta`` seconds (#125 manual alignment).
    * ``timePicked(seconds)`` — a click while in pick mode chose this time (used
      to pair a log entry with the EEG feature it produced).
    """

    regionDrawn = QtCore.pyqtSignal(float, float)
    annotationSelected = QtCore.pyqtSignal(int)
    windowChanged = QtCore.pyqtSignal(float)
    cursorMoved = QtCore.pyqtSignal(float)
    pointMarkRequested = QtCore.pyqtSignal(float)
    logSlideStarted = QtCore.pyqtSignal()
    logSlideMoved = QtCore.pyqtSignal(float)
    logSlideFinished = QtCore.pyqtSignal(float)
    timePicked = QtCore.pyqtSignal(float)

    def __init__(self) -> None:
        self._viewbox = _AnnotateViewBox()
        self._time_axis = TimeAxis(orientation="bottom")
        super().__init__(
            viewBox=self._viewbox,
            background=None,
            axisItems={"bottom": self._time_axis},
        )
        self._provider: SliceProvider | None = None
        self._spec = dsp.UNFILTERED  # the base filter; per-type overrides below
        self._type_specs: dict[str, dsp.FilterSpec] = {}
        self._window_start = 0.0
        self._window_seconds = 30.0  # the standard sleep-scoring epoch
        self._scale_uv = DEFAULT_BASE_SCALE_UV  # base µV per lane; overrides below
        self._type_scales: dict[str, float] = dict(DEFAULT_TYPE_SCALES)
        # Channel indices to draw, in display order; all channels until set_provider
        # (or a view profile) narrows or reorders them (#177).
        self._visible: list[int] = []
        # Epoch model (#173): the scoring epoch is separate from the on-screen
        # window. Boundaries fall at anchor + k·epoch for integer k, so anchoring
        # on a feature back/front-fills the whole grid from that point.
        self._epoch_seconds = DEFAULT_EPOCH_SECONDS
        self._epoch_anchor = 0.0
        self._show_epochs = True
        self._epoch_items: list[pg.InfiniteLine] = []
        self._annotations: list[Annotation] = []
        self._selected = -1
        self._annotation_items: list[pg.LinearRegionItem | pg.InfiniteLine] = []
        # Other raters' read-only marks, drawn behind the editable layer (#181d).
        self._overlays: list[RaterOverlay] = []
        self._overlay_items: list[pg.LinearRegionItem | pg.InfiniteLine] = []
        # Session-log overlay (#125): read-only ticks in the top lane, kept sorted
        # by time so only the visible window is drawn on each scroll.
        self._log_marks: list[LogMark] = []
        self._log_items: list[pg.InfiniteLine] = []
        # Pick mode: a click reports its time (to pair a log entry to an EEG
        # feature) instead of selecting an annotation.
        self._pick_mode = False
        # Whether the log lane may be slid to align — off in standalone mode,
        # which has no recording clock to reconcile against (#125d).
        self._log_alignable = True
        self._curves: list[pg.PlotDataItem] = []

        self._viewbox.dragFinished.connect(self._on_drag_finished)
        self._viewbox.clicked.connect(self._on_clicked)
        self._viewbox.markRequested.connect(self._on_mark_requested)
        self._viewbox.logSlideStarted.connect(self.logSlideStarted)
        self._viewbox.logSlideMoved.connect(self.logSlideMoved)
        self._viewbox.logSlideFinished.connect(self.logSlideFinished)
        # Keyboard navigation is owned by the window (a single app-level filter,
        # so it works without first clicking the traces — see window.py); the
        # view only exposes the navigation primitives it drives.
        self.setAntialiasing(False)  # measurably faster, invisible at 1 px pens
        plot_item = self.getPlotItem()
        assert plot_item is not None
        plot_item.hideButtons()  # the autoscale "A" makes no sense here
        plot_item.setMenuEnabled(False)
        left_axis = plot_item.getAxis("left")
        left_axis.setStyle(tickLength=0)
        # The bottom axis is the custom TimeAxis (clock/elapsed); it labels itself.
        # Track the mouse for the status-bar clock readout.
        self.scene().sigMouseMoved.connect(self._on_mouse_moved)

    # ----- display state ----------------------------------------------------

    @property
    def window_start(self) -> float:
        return self._window_start

    @property
    def window_seconds(self) -> float:
        return self._window_seconds

    @property
    def has_provider(self) -> bool:
        """Whether something is loaded to scroll — a recording or a log timeline."""
        return self._provider is not None

    @property
    def duration(self) -> float:
        """The loaded provider's length in seconds (0 when nothing is loaded).

        Lets the window size its scrollbar from whatever is shown — a recording
        or the standalone log timeline (#125) — without reaching into a recording
        it may not have.
        """
        return self._provider.duration if self._provider is not None else 0.0

    @property
    def annotations(self) -> list[Annotation]:
        return list(self._annotations)

    @property
    def selected(self) -> int:
        return self._selected

    @property
    def epoch_seconds(self) -> float:
        return self._epoch_seconds

    @property
    def epoch_anchor(self) -> float:
        return self._epoch_anchor

    def set_provider(self, provider: SliceProvider | None) -> None:
        """Show a (new) recording from its start; ``None`` clears the view."""
        self._provider = provider
        self._window_start = 0.0
        self._epoch_anchor = 0.0  # a new recording starts epoch 1 at its start
        self._overlays = []  # peers belong to the previous recording; window reloads
        self._log_marks = []  # the log belongs to the previous recording too
        self._viewbox.set_log_lane_active(False)
        # Show every channel in file order by default; a profile may narrow this.
        self._visible = list(range(len(provider.ch_names))) if provider else []
        self._build_curves()
        self._refresh_data()
        self._refresh_annotations()
        self._refresh_epochs()
        self._refresh_log_marks()

    def set_spec(self, spec: dsp.FilterSpec) -> None:
        self._spec = spec
        self._refresh_data()

    def set_scale(self, microvolts: float) -> None:
        """Set the base lane height in µV (smaller value → visually bigger traces)."""
        self._scale_uv = max(1e-9, microvolts)
        self._refresh_data()

    # ----- per-type display + channel selection (#177) ----------------------

    @property
    def spec(self) -> dsp.FilterSpec:
        """The base display filter (used by types without an override)."""
        return self._spec

    @property
    def scale_uv(self) -> float:
        """The base lane height in µV (used by types without an override)."""
        return self._scale_uv

    def type_scales(self) -> dict[str, float]:
        return dict(self._type_scales)

    def type_specs(self) -> dict[str, dsp.FilterSpec]:
        return dict(self._type_specs)

    def effective_spec(self, ch_type: str) -> dsp.FilterSpec:
        return self._type_specs.get(ch_type, self._spec)

    def effective_scale(self, ch_type: str) -> float:
        return self._type_scales.get(ch_type, self._scale_uv)

    def set_type_spec(self, ch_type: str, spec: dsp.FilterSpec | None) -> None:
        """Override (or clear, with ``None``) the display filter for one type."""
        if spec is None:
            self._type_specs.pop(ch_type, None)
        else:
            self._type_specs[ch_type] = spec
        self._refresh_data()

    def set_type_scale(self, ch_type: str, microvolts: float | None) -> None:
        """Override (or clear, with ``None``) the lane height for one type."""
        if microvolts is None:
            self._type_scales.pop(ch_type, None)
        else:
            self._type_scales[ch_type] = max(1e-9, microvolts)
        self._refresh_data()

    def set_type_scales(self, scales: dict[str, float]) -> None:
        """Replace every per-type amplitude override (when applying a profile)."""
        self._type_scales = {k: max(1e-9, v) for k, v in scales.items()}
        self._refresh_data()

    def set_type_specs(self, specs: dict[str, dsp.FilterSpec]) -> None:
        """Replace every per-type filter override (when applying a profile)."""
        self._type_specs = dict(specs)
        self._refresh_data()

    @property
    def channel_names(self) -> list[str]:
        return list(self._provider.ch_names) if self._provider else []

    @property
    def channel_types(self) -> list[str]:
        return list(self._provider.ch_types) if self._provider else []

    @property
    def visible_indices(self) -> list[int]:
        """The channel positions currently drawn, in display order."""
        return list(self._visible)

    @property
    def visible_channels(self) -> list[str]:
        """The names of the currently drawn channels, in display order."""
        names = self.channel_names
        return [names[i] for i in self._visible]

    def set_visible_channels(self, indices: list[int]) -> None:
        """Show exactly ``indices`` (channel positions), in the given order.

        Out-of-range and duplicate indices are dropped; an empty result is
        ignored (a montage with no channels is never useful), so the current
        selection stays.
        """
        if self._provider is None:
            return
        count = len(self._provider.ch_names)
        seen: list[int] = []
        for i in indices:
            if 0 <= i < count and i not in seen:
                seen.append(i)
        if not seen:
            return
        self._visible = seen
        self._build_curves()
        self._refresh_data()
        self._refresh_annotations()
        self._refresh_epochs()
        self._refresh_log_marks()

    def build_snapshot(
        self,
        *,
        marks: list[tuple[float, float, str]],
        show_epochs: bool,
        n_time_ticks: int = 7,
        title: str = "",
    ) -> Snapshot:
        """Assemble a pure :class:`Snapshot` of the current window for export (#180).

        ``marks`` is the list of ``(onset, duration, clean_label)`` to draw — the
        window chooses which annotations to include and how to relabel them.
        Times come back window-relative. Reuses :meth:`_lane_traces` and
        :meth:`_epoch_boundaries`, so the figure is the same picture as the
        screen. Safe with no recording loaded (returns empty traces).
        """
        lo = self._window_start
        hi = lo + self._window_seconds
        if self._provider is None:
            return Snapshot(
                times=np.empty(0), window_seconds=self._window_seconds, traces=()
            )
        times, lanes = self._lane_traces()
        names = self.channel_names
        traces = tuple(
            SnapshotTrace(
                name=names[entry.channel],
                ch_type=entry.ch_type,
                lane=entry.lane,
                values=entry.values,
                scale_uv=entry.scale_uv,
            )
            for entry in lanes
        )
        snapshot_marks = tuple(
            SnapshotMark(onset=onset - lo, duration=duration, label=label)
            for onset, duration, label in marks
        )
        epochs = (
            tuple(
                SnapshotEpoch(x=x - lo, number=number)
                for x, number in self._epoch_boundaries(lo, hi)
            )
            if show_epochs
            else ()
        )
        ticks = tuple(
            (float(t - lo), self._time_axis.tick_label(float(t)))
            for t in np.linspace(lo, hi, n_time_ticks)
        )
        return Snapshot(
            times=times - lo,
            window_seconds=self._window_seconds,
            traces=traces,
            marks=snapshot_marks,
            epochs=epochs,
            time_ticks=ticks,
            time_axis_label=(
                "clock time" if self._time_axis.mode == "clock" else "time (s)"
            ),
            sfreq=self._provider.sfreq,
            title=title,
        )

    def set_window_seconds(self, seconds: float) -> None:
        self._window_seconds = max(1.0, seconds)
        self._clamp_window_start()
        self._refresh_data()
        self._refresh_annotations()
        self._refresh_epochs()
        self._refresh_log_marks()

    def set_window_start(self, seconds: float) -> None:
        self._window_start = seconds
        self._clamp_window_start()
        self._refresh_data()
        self._refresh_annotations()
        self._refresh_epochs()
        self._refresh_log_marks()

    def set_epoch_seconds(self, seconds: float) -> None:
        """Set the scoring-epoch length (≥ 1 s); redraws the epoch grid."""
        self._epoch_seconds = max(1.0, float(seconds))
        self._refresh_epochs()

    def set_epoch_anchor(self, seconds: float) -> None:
        """Set the time at which an epoch boundary falls (epoch 1 starts here).

        The grid back/front-fills from the anchor, so passing a feature's time
        (e.g. the start of an LRLR) lets the signal sit cleanly inside one epoch.
        """
        self._epoch_anchor = max(0.0, float(seconds))
        self._refresh_epochs()

    def set_epochs_visible(self, visible: bool) -> None:
        self._show_epochs = bool(visible)
        self._refresh_epochs()

    def set_time_axis_mode(self, mode: str) -> None:
        """Label the time axis with ``"clock"`` wall time or ``"elapsed"`` seconds."""
        self._time_axis.set_mode(mode)

    def set_time_origin(self, origin: datetime | None) -> None:
        """Tell the axis the wall-clock instant of data-second 0 (for clock mode)."""
        self._time_axis.set_origin(origin)

    def scroll_by(self, fraction: float) -> None:
        """Scroll by a fraction of the window (±1.0 is a full page)."""
        self.set_window_start(self._window_start + fraction * self._window_seconds)
        self.windowChanged.emit(self._window_start)

    def step_epochs(self, count: int) -> None:
        """Move the window by ``count`` epoch lengths (the arrow-key page step)."""
        self.set_window_start(self._window_start + count * self._epoch_seconds)
        self.windowChanged.emit(self._window_start)

    def nudge_seconds(self, seconds: float) -> None:
        """Scroll a fixed number of seconds (the Shift+arrow fine step)."""
        self.set_window_start(self._window_start + seconds)
        self.windowChanged.emit(self._window_start)

    def set_annotations(
        self, annotations: list[Annotation], selected: int = -1
    ) -> None:
        """Replace the displayed annotations (and selection) — no refilter."""
        self._annotations = list(annotations)
        self._selected = selected
        self._refresh_annotations()

    def set_overlays(self, overlays: list[RaterOverlay]) -> None:
        """Replace the other-rater overlays drawn behind the editable layer (#181d).

        Read-only and never selectable — clicks only ever hit the editable
        annotations — so a peer rater's marks are visible context, not editable.
        """
        self._overlays = list(overlays)
        self._refresh_overlays()

    def set_log_marks(self, marks: list[LogMark]) -> None:
        """Replace the read-only session-log overlay in the top lane (#125).

        Marks are kept sorted by time so each scroll redraws only the handful in
        view (an overnight log has thousands of entries). A non-empty list arms
        the top-lane slide (so a drag up there aligns the log) *when alignment is
        enabled* — standalone log mode has no second clock to correct, so it
        disables it; an empty list always disarms.
        """
        self._log_marks = sorted(marks, key=lambda m: m.seconds)
        self._viewbox.set_log_lane_active(bool(self._log_marks) and self._log_alignable)
        self._refresh_log_marks()

    def set_log_alignable(self, enabled: bool) -> None:
        """Allow (or forbid) sliding the log lane — off when there is no recording.

        Aligning reconciles the log clock with the recording's; with no recording
        loaded (standalone mode) there is only one clock, so a slide would only
        push the ticks off their own axis labels. The window disables it there.
        """
        self._log_alignable = enabled
        self._viewbox.set_log_lane_active(bool(self._log_marks) and enabled)

    def set_pick_mode(self, enabled: bool) -> None:
        """In pick mode a click reports its time via ``timePicked`` (for pairing).

        While enabled a plain click does not select an annotation — it answers
        the "click the EEG feature this log entry caused" prompt — and a drag or
        ctrl-click can't slip through to edit a mark either (the viewbox swallows
        them), so the manual alignment never disturbs the rater's own work.
        """
        self._pick_mode = bool(enabled)
        self._viewbox.set_pick_active(self._pick_mode)

    # ----- interaction ---------------------------------------------------------

    def _on_drag_finished(self, lo: float, hi: float) -> None:
        if self._provider is None:
            return
        # Clamp to the recording so a drag past an edge yields a valid span.
        lo = max(0.0, lo)
        hi = min(self._provider.duration, hi)
        if hi > lo:
            self.regionDrawn.emit(lo, hi)

    def _on_mark_requested(self, seconds: float) -> None:
        if self._provider is None:
            return
        seconds = min(max(0.0, seconds), self._provider.duration)
        self.pointMarkRequested.emit(seconds)

    def _on_clicked(self, seconds: float) -> None:
        # Pick mode (manual log alignment): the click chooses a time to pair with
        # a log entry, not an annotation to select.
        if self._pick_mode:
            if self._provider is not None:
                clamped = min(max(0.0, seconds), self._provider.duration)
                self.timePicked.emit(clamped)
            return
        index = self._annotation_at(seconds)
        self._selected = index
        self._refresh_annotations()
        self.annotationSelected.emit(index)

    def _annotation_at(self, seconds: float) -> int:
        """The index of the annotation under ``seconds``, or -1.

        Prefers the latest-starting (typically narrowest/topmost) hit so a
        point mark inside a long region is still clickable. Zero-duration
        marks get a small symmetric tolerance.
        """
        tolerance = self._window_seconds * _CLICK_TOLERANCE_FRACTION
        hit = -1
        for index, a in enumerate(self._annotations):
            lo, hi = a.onset, a.onset + a.duration
            if a.duration == 0:
                lo, hi = lo - tolerance, hi + tolerance
            if lo <= seconds <= hi:
                hit = index
        return hit

    def _on_mouse_moved(self, scene_pos: Any) -> None:
        plot_item = self.getPlotItem()
        # sceneBoundingRect lives on the PlotItem (a QGraphicsWidget) — the
        # PlotWidget itself is the QGraphicsView and has no scene rect.
        if plot_item is not None and plot_item.sceneBoundingRect().contains(scene_pos):
            self.cursorMoved.emit(float(self._viewbox.mapSceneToView(scene_pos).x()))

    def wheelEvent(self, ev: QtGui.QWheelEvent | None) -> None:
        """Wheel scrolls time (a tenth of a window per notch), never zooms."""
        if ev is None:
            return
        notches = ev.angleDelta().y() / 120.0
        self.scroll_by(-0.1 * notches)
        ev.accept()

    # ----- drawing ---------------------------------------------------------------

    def _clamp_window_start(self) -> None:
        if self._provider is None:
            self._window_start = 0.0
            return
        latest = max(0.0, self._provider.duration - self._window_seconds)
        self._window_start = min(max(0.0, self._window_start), latest)

    def _build_curves(self) -> None:
        """Recreate one curve per *visible* channel (on open/clear), tuned for speed."""
        plot_item = self.getPlotItem()
        assert plot_item is not None
        for curve in self._curves:
            plot_item.removeItem(curve)
        self._curves = []
        if self._provider is None:
            plot_item.getAxis("left").setTicks([[]])
            return
        pen = pg.mkPen(self.palette().color(QtGui.QPalette.ColorRole.Text), width=1)
        names = self._provider.ch_names
        for _ in self._visible:
            curve = pg.PlotDataItem(pen=pen)
            # Peak (min/max) downsampling keeps extremes visible at any zoom;
            # clip-to-view skips offscreen points when a margin is set.
            curve.setDownsampling(auto=True, method="peak")
            curve.setClipToView(True)
            plot_item.addItem(curve)
            self._curves.append(curve)
        # Lanes follow display order: the channel at display position ``lane`` is
        # centered at y = -lane, labelled with its name.
        plot_item.getAxis("left").setTicks(
            [[(-lane, names[i]) for lane, i in enumerate(self._visible)]]
        )
        self.setYRange(-len(self._visible) + 0.4, 0.6, padding=0)

    def _lane_traces(self) -> tuple[np.ndarray, list[_LaneTrace]]:
        """Fetch, filter, trim, and scale the visible window into lane-unit traces.

        The single source of truth for both :meth:`_refresh_data` (which draws
        them) and :meth:`build_snapshot` (which exports them), so the screen and
        the figure are guaranteed to be the same picture. ``times`` is in data
        seconds, trimmed to the window; each :class:`_LaneTrace` carries the
        lane-unit ``values`` (centered on 0; draw ``-lane + values``).
        """
        assert self._provider is not None
        ch_types = self._provider.ch_types
        sfreq = self._provider.sfreq
        # Each visible channel filters by its type's effective spec; fetch a
        # margin wide enough for the longest transient across all active specs.
        specs = {i: self.effective_spec(ch_types[i]) for i in self._visible}
        pad = max((dsp.pad_seconds(s) for s in specs.values()), default=1.0)
        lo = self._window_start
        hi = self._window_start + self._window_seconds
        times, raw = self._provider.get_slice(lo - pad, hi + pad)
        raw = np.asarray(raw)
        times = np.asarray(times)
        data = raw.astype(float, copy=True)
        # Filter each group of like-spec channels together — one designed filter
        # per distinct spec (the dsp cache keys on it), not one per channel.
        groups: dict[dsp.FilterSpec, list[int]] = {}
        for i, spec in specs.items():
            groups.setdefault(spec, []).append(i)
        for spec, idx in groups.items():
            if not spec.is_identity:
                data[idx] = dsp.apply(raw[idx], sfreq, spec)
        # Trim the filter margin so its edge transients never reach the screen.
        keep = (times >= lo) & (times <= hi)
        times = times[keep]
        lanes: list[_LaneTrace] = []
        for lane, i in enumerate(self._visible):
            trace = data[i][keep]
            if ch_types[i] in _MICROVOLT_TYPES:
                scale_uv: float | None = self.effective_scale(ch_types[i])
                scaled = trace * _VOLTS_TO_MICROVOLTS / scale_uv
            else:
                # Unit-less channel (stim/misc/…): fit it to its own lane per
                # visible slice. Absolute amplitude is meaningless for these;
                # the edges (a trigger firing) are what a reviewer looks for.
                scale_uv = None
                peak = float(np.max(np.abs(trace))) if trace.size else 0.0
                scaled = trace * (_AUTOFIT_EXCURSION / peak) if peak else trace
            lanes.append(_LaneTrace(lane, i, ch_types[i], scaled, scale_uv))
        return times, lanes

    def _refresh_data(self) -> None:
        """Draw the visible slice of every shown channel."""
        if self._provider is None:
            return
        times, lanes = self._lane_traces()
        for entry in lanes:
            self._curves[entry.lane].setData(times, -entry.lane + entry.values)
        lo = self._window_start
        self.setXRange(lo, lo + self._window_seconds, padding=0)

    def _refresh_annotations(self) -> None:
        """Redraw the annotation overlay for the visible window (cheap)."""
        plot_item = self.getPlotItem()
        assert plot_item is not None
        for old in self._annotation_items:
            plot_item.removeItem(old)
        self._annotation_items = []
        if self._provider is None:
            return
        lo = self._window_start
        hi = self._window_start + self._window_seconds
        for index, a in enumerate(self._annotations):
            if a.onset + a.duration < lo or a.onset > hi:
                continue
            selected = index == self._selected
            item: pg.LinearRegionItem | pg.InfiniteLine
            if a.duration > 0:
                item = pg.LinearRegionItem(
                    values=(a.onset, a.onset + a.duration),
                    movable=False,
                    brush=_REGION_BRUSH_SELECTED if selected else _REGION_BRUSH,
                    pen=_REGION_PEN,
                )
            else:
                item = pg.InfiniteLine(
                    pos=a.onset,
                    angle=90,
                    movable=False,
                    pen=pg.mkPen(
                        _LINE_PEN_SELECTED if selected else _LINE_PEN,
                        width=2 if selected else 1,
                    ),
                )
            item.setToolTip(a.description)
            item.setZValue(10)
            plot_item.addItem(item)
            self._annotation_items.append(item)
        self._refresh_overlays()  # peers redraw with the editable layer on scroll

    def _refresh_overlays(self) -> None:
        """Redraw the read-only other-rater overlays for the visible window (#181d).

        Each visible rater's marks paint in that rater's colour, below the
        editable layer and with no selection styling — visible context only.
        """
        plot_item = self.getPlotItem()
        assert plot_item is not None
        for old in self._overlay_items:
            plot_item.removeItem(old)
        self._overlay_items = []
        if self._provider is None:
            return
        lo = self._window_start
        hi = self._window_start + self._window_seconds
        for overlay in self._overlays:
            if not overlay.visible:
                continue
            red, green, blue = overlay.color
            brush = (red, green, blue, 45)
            pen = (red, green, blue, 200)
            for a in overlay.annotations:
                if a.onset + a.duration < lo or a.onset > hi:
                    continue
                item: pg.LinearRegionItem | pg.InfiniteLine
                if a.duration > 0:
                    item = pg.LinearRegionItem(
                        values=(a.onset, a.onset + a.duration),
                        movable=False,
                        brush=brush,
                        pen=pen,
                    )
                else:
                    item = pg.InfiniteLine(
                        pos=a.onset, angle=90, movable=False, pen=pg.mkPen(pen, width=1)
                    )
                item.setToolTip(f"{overlay.rater_id}: {a.description}")
                item.setZValue(_OVERLAY_Z)
                plot_item.addItem(item)
                self._overlay_items.append(item)

    def _refresh_log_marks(self) -> None:
        """Redraw the session-log overlay ticks in the top lane (#125).

        Each mark is an instantaneous tick spanning only the top lane, coloured
        by its log level. The marks are time-sorted, so a binary search bounds
        the redraw to the entries inside the visible window — cheap on scroll
        even for an all-night log with thousands of entries.
        """
        plot_item = self.getPlotItem()
        assert plot_item is not None
        for old in self._log_items:
            plot_item.removeItem(old)
        self._log_items = []
        if self._provider is None or not self._log_marks:
            return
        lo = self._window_start
        hi = self._window_start + self._window_seconds
        seconds = [m.seconds for m in self._log_marks]
        start = bisect.bisect_left(seconds, lo)
        stop = bisect.bisect_right(seconds, hi)
        for mark in self._log_marks[start:stop]:
            color = _LOG_LEVEL_COLORS.get(mark.level, _LOG_DEFAULT_COLOR)
            line = pg.InfiniteLine(
                pos=mark.seconds,
                angle=90,
                movable=False,
                pen=pg.mkPen(color, width=2),
                span=(_LOG_LANE_FRAC, 1.0),  # the top lane only
            )
            line.setToolTip(mark.tooltip)
            line.setZValue(_LOG_Z)
            plot_item.addItem(line)
            self._log_items.append(line)

    def _refresh_epochs(self) -> None:
        """Redraw the epoch boundary gridlines for the visible window.

        Lines fall at ``anchor + k·epoch`` and are numbered with the epoch they
        begin (the boundary at the anchor starts epoch 1). Only the handful of
        boundaries inside the window are drawn, so this stays cheap on scroll.
        """
        plot_item = self.getPlotItem()
        assert plot_item is not None
        for old in self._epoch_items:
            plot_item.removeItem(old)
        self._epoch_items = []
        if self._provider is None or not self._show_epochs:
            return
        lo = self._window_start
        hi = self._window_start + self._window_seconds
        for boundary, number in self._epoch_boundaries(lo, hi):
            line = pg.InfiniteLine(
                pos=boundary,
                angle=90,
                movable=False,
                pen=_EPOCH_PEN,
                label=number,  # the epoch this boundary starts
                labelOpts={"position": 0.96, "color": _EPOCH_LABEL_COLOR},
            )
            line.setZValue(2)  # above the curves, below the annotations
            plot_item.addItem(line)
            self._epoch_items.append(line)

    def _epoch_boundaries(self, lo: float, hi: float) -> list[tuple[float, str]]:
        """``(boundary_seconds, "k+1")`` for every epoch line within ``[lo, hi]``.

        Shared by :meth:`_refresh_epochs` (the on-screen grid) and
        :meth:`build_snapshot` (the export), so both number epochs identically.
        """
        first = math.ceil((lo - self._epoch_anchor) / self._epoch_seconds)
        last = math.floor((hi - self._epoch_anchor) / self._epoch_seconds)
        return [
            (self._epoch_anchor + k * self._epoch_seconds, str(k + 1))
            for k in range(first, last + 1)
        ]
