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

from typing import Any, Protocol

import numpy as np
import pyqtgraph as pg
from PyQt6 import QtCore, QtGui

from . import dsp
from .annotations import Annotation

# Bioelectric channels are recorded in volts and displayed in microvolts.
# Other kinds (stim/misc/…) carry arbitrary units — a trigger channel holds
# integer event codes like 255, which on a 100 µV lane scale would paint
# straight across every EEG lane — so they are auto-fit into their own lane
# per visible slice instead (see _refresh_data).
_MICROVOLT_TYPES = {"eeg", "eog", "emg", "ecg", "seeg", "ecog", "dbs", "bio"}
_VOLTS_TO_MICROVOLTS = 1e6
# Lane-units excursion an auto-fit (non-bioelectric) channel is normalized to.
_AUTOFIT_EXCURSION = 0.4

# Per-channel-type display gain applied on top of the global scale. EMG rides
# hotter than EEG on most montages; halving it keeps the trace inside its lane
# without a per-channel scaling UI (cut deliberately — see issue #136).
TYPE_GAINS = {"emg": 0.5}

# Clicking selects the annotation under the cursor; a zero-duration mark gets
# this much slack on each side, as a fraction of the visible window.
_CLICK_TOLERANCE_FRACTION = 0.005

# Annotation paint: translucent fills so traces stay readable through them.
_REGION_BRUSH = (70, 130, 180, 50)  # steel blue wash
_REGION_BRUSH_SELECTED = (70, 130, 180, 110)
_REGION_PEN = (70, 130, 180, 160)
_LINE_PEN = (178, 34, 34, 160)  # firebrick for instantaneous marks
_LINE_PEN_SELECTED = (178, 34, 34, 255)


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

    def __init__(self) -> None:
        super().__init__(enableMouse=False, enableMenu=False)
        self._preview: pg.LinearRegionItem | None = None

    def mouseDragEvent(self, ev: Any, axis: int | None = None) -> None:
        if ev.button() != QtCore.Qt.MouseButton.LeftButton:
            ev.ignore()
            return
        ev.accept()
        start = float(self.mapToView(ev.buttonDownPos()).x())
        current = float(self.mapToView(ev.pos()).x())
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
        # Ctrl+click drops a point mark; a plain click selects. The modifier
        # keeps the frequent selection-click from ever creating stray markers.
        if ev.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier:
            self.markRequested.emit(seconds)
        else:
            self.clicked.emit(seconds)


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
    """

    regionDrawn = QtCore.pyqtSignal(float, float)
    annotationSelected = QtCore.pyqtSignal(int)
    windowChanged = QtCore.pyqtSignal(float)
    cursorMoved = QtCore.pyqtSignal(float)
    pointMarkRequested = QtCore.pyqtSignal(float)

    def __init__(self) -> None:
        self._viewbox = _AnnotateViewBox()
        super().__init__(viewBox=self._viewbox, background=None)
        self._provider: SliceProvider | None = None
        self._spec = dsp.UNFILTERED
        self._window_start = 0.0
        self._window_seconds = 30.0  # the standard sleep-scoring epoch
        self._scale_uv = 100.0  # microvolts per channel lane
        self._annotations: list[Annotation] = []
        self._selected = -1
        self._annotation_items: list[pg.LinearRegionItem | pg.InfiniteLine] = []
        self._curves: list[pg.PlotDataItem] = []

        self._viewbox.dragFinished.connect(self._on_drag_finished)
        self._viewbox.clicked.connect(self._on_clicked)
        self._viewbox.markRequested.connect(self._on_mark_requested)
        # Click-to-focus so the arrow-key navigation in keyPressEvent reaches
        # the traces after the operator clicks them.
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.ClickFocus)
        self.setAntialiasing(False)  # measurably faster, invisible at 1 px pens
        plot_item = self.getPlotItem()
        assert plot_item is not None
        plot_item.hideButtons()  # the autoscale "A" makes no sense here
        plot_item.setMenuEnabled(False)
        left_axis = plot_item.getAxis("left")
        left_axis.setStyle(tickLength=0)
        bottom_axis = plot_item.getAxis("bottom")
        bottom_axis.setLabel("time (s)")
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
    def annotations(self) -> list[Annotation]:
        return list(self._annotations)

    @property
    def selected(self) -> int:
        return self._selected

    def set_provider(self, provider: SliceProvider | None) -> None:
        """Show a (new) recording from its start; ``None`` clears the view."""
        self._provider = provider
        self._window_start = 0.0
        self._build_curves()
        self._refresh_data()
        self._refresh_annotations()

    def set_spec(self, spec: dsp.FilterSpec) -> None:
        self._spec = spec
        self._refresh_data()

    def set_scale(self, microvolts: float) -> None:
        """Set the lane height in µV (smaller value → visually bigger traces)."""
        self._scale_uv = max(1e-9, microvolts)
        self._refresh_data()

    def set_window_seconds(self, seconds: float) -> None:
        self._window_seconds = max(1.0, seconds)
        self._clamp_window_start()
        self._refresh_data()
        self._refresh_annotations()

    def set_window_start(self, seconds: float) -> None:
        self._window_start = seconds
        self._clamp_window_start()
        self._refresh_data()
        self._refresh_annotations()

    def scroll_by(self, fraction: float) -> None:
        """Scroll by a fraction of the window (±1.0 is a full page)."""
        self.set_window_start(self._window_start + fraction * self._window_seconds)
        self.windowChanged.emit(self._window_start)

    def set_annotations(
        self, annotations: list[Annotation], selected: int = -1
    ) -> None:
        """Replace the displayed annotations (and selection) — no refilter."""
        self._annotations = list(annotations)
        self._selected = selected
        self._refresh_annotations()

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

    def keyPressEvent(self, ev: QtGui.QKeyEvent | None) -> None:
        """Arrow/Home/End navigation while the traces have focus.

        These live here (with click-to-focus) rather than as window shortcuts
        because a focused spin box consumes cursor keys via ShortcutOverride —
        a window-level Left/Right would silently die right after the operator
        adjusts a filter. Clicking the traces focuses them, and from there the
        arrows always work. PageUp/PageDown are window shortcuts (no text
        widget steals them), so paging works regardless of focus.
        """
        if ev is None:
            return
        key = ev.key()
        if key == QtCore.Qt.Key.Key_Right:
            self.scroll_by(0.1)
        elif key == QtCore.Qt.Key.Key_Left:
            self.scroll_by(-0.1)
        elif key == QtCore.Qt.Key.Key_Home:
            self.set_window_start(0.0)
            self.windowChanged.emit(self._window_start)
        elif key == QtCore.Qt.Key.Key_End:
            self.set_window_start(float("inf"))
            self.windowChanged.emit(self._window_start)
        else:
            super().keyPressEvent(ev)
            return
        ev.accept()

    # ----- drawing ---------------------------------------------------------------

    def _clamp_window_start(self) -> None:
        if self._provider is None:
            self._window_start = 0.0
            return
        latest = max(0.0, self._provider.duration - self._window_seconds)
        self._window_start = min(max(0.0, self._window_start), latest)

    def _build_curves(self) -> None:
        """Recreate one curve per channel (on open/clear), tuned for speed."""
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
        for _ in names:
            curve = pg.PlotDataItem(pen=pen)
            # Peak (min/max) downsampling keeps extremes visible at any zoom;
            # clip-to-view skips offscreen points when a margin is set.
            curve.setDownsampling(auto=True, method="peak")
            curve.setClipToView(True)
            plot_item.addItem(curve)
            self._curves.append(curve)
        plot_item.getAxis("left").setTicks(
            [[(-i, name) for i, name in enumerate(names)]]
        )
        self.setYRange(-len(names) + 0.4, 0.6, padding=0)

    def _refresh_data(self) -> None:
        """Fetch, filter, scale, and draw the visible slice of every channel."""
        if self._provider is None:
            return
        pad = dsp.pad_seconds(self._spec)
        lo = self._window_start
        hi = self._window_start + self._window_seconds
        times, data = self._provider.get_slice(lo - pad, hi + pad)
        data = dsp.apply(np.asarray(data), self._provider.sfreq, self._spec)
        times = np.asarray(times)
        # Trim the filter margin so its edge transients never reach the screen.
        keep = (times >= lo) & (times <= hi)
        times, data = times[keep], data[:, keep]
        ch_types = self._provider.ch_types
        for i, curve in enumerate(self._curves):
            trace = data[i]
            if ch_types[i] in _MICROVOLT_TYPES:
                gain = TYPE_GAINS.get(ch_types[i], 1.0)
                scaled = trace * _VOLTS_TO_MICROVOLTS * (gain / self._scale_uv)
            else:
                # Unit-less channel (stim/misc/…): fit it to its own lane per
                # visible slice. Absolute amplitude is meaningless for these;
                # the edges (a trigger firing) are what a reviewer looks for.
                peak = float(np.max(np.abs(trace))) if trace.size else 0.0
                scaled = trace * (_AUTOFIT_EXCURSION / peak) if peak else trace
            curve.setData(times, -i + scaled)
        self.setXRange(lo, hi, padding=0)

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
