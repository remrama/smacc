"""Tests for the EEG trace view (#136) — offscreen, no MNE.

The view draws from the :class:`SliceProvider` protocol, so a small fake with
known constant data stands in for a recording; channel scaling and lane
offsets can then be asserted exactly.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pyqtgraph as pg
import pytest
from PyQt6 import QtCore, QtGui

from smacc.eeg import dsp
from smacc.eeg.annotations import Annotation
from smacc.eeg.view import TYPE_GAINS, TimeAxis, TraceView

SFREQ = 100.0
DURATION = 60.0
# 50 µV everywhere: with the default 100 µV lane scale an EEG channel sits at
# +0.5 lane units above its offset.
CONSTANT_VOLTS = 50e-6


class FakeProvider:
    """Constant-valued recording: 2 EEG + EOG + EMG, 100 Hz, 60 s."""

    ch_names = ["C3", "C4", "EOG", "EMG"]
    ch_types = ["eeg", "eeg", "eog", "emg"]
    sfreq = SFREQ
    duration = DURATION

    def __init__(self) -> None:
        self.calls: list[tuple[float, float]] = []

    def get_slice(self, start_s: float, stop_s: float):
        self.calls.append((start_s, stop_s))
        start = max(0, int(round(max(0.0, start_s) * SFREQ)))
        stop = min(int(DURATION * SFREQ), int(round(min(DURATION, stop_s) * SFREQ)))
        n = max(0, stop - start)
        times = (start + np.arange(n)) / SFREQ
        return times, np.full((4, n), CONSTANT_VOLTS)


@pytest.fixture
def view(qtbot):
    view = TraceView()
    qtbot.addWidget(view)
    view.resize(800, 500)
    return view


@pytest.fixture
def loaded(view):
    provider = FakeProvider()
    view.set_provider(provider)
    return view, provider


# ----- construction and data flow ----------------------------------------------


def test_set_provider_builds_one_curve_per_channel(loaded):
    view, _ = loaded
    assert len(view._curves) == 4


def test_traces_are_scaled_to_microvolt_lanes(loaded):
    # 50 µV on a 100 µV lane scale → +0.5 above the channel's lane center,
    # with channel i centered at y = -i and EMG halved by its type gain.
    view, _ = loaded
    _, y0 = view._curves[0].getData()
    assert y0 == pytest.approx(0.0 + 0.5)
    _, y3 = view._curves[3].getData()
    emg = 0.5 * TYPE_GAINS["emg"]
    assert y3 == pytest.approx(-3 + emg)


def test_scale_control_changes_trace_amplitude(loaded):
    view, _ = loaded
    view.set_scale(50.0)  # half the lane height → double the excursion
    _, y0 = view._curves[0].getData()
    assert y0 == pytest.approx(1.0)


def test_filter_margin_is_fetched_but_trimmed(loaded):
    # With a 0.5 Hz high-pass the view fetches pad_seconds of margin on each
    # side, but the drawn data must stay inside the visible window — the
    # margin exists exactly so filter edge transients are never shown.
    view, provider = loaded
    provider.calls.clear()
    view.set_spec(dsp.FilterSpec(highpass=0.5))
    pad = dsp.pad_seconds(dsp.FilterSpec(highpass=0.5))
    (fetch_start, fetch_stop) = provider.calls[-1]
    assert fetch_start == pytest.approx(0.0 - pad)
    assert fetch_stop == pytest.approx(30.0 + pad)
    x0, _ = view._curves[0].getData()
    assert x0.min() >= 0.0
    assert x0.max() <= 30.0


# ----- windowing ------------------------------------------------------------------


def test_window_start_clamps_to_the_recording(loaded):
    view, _ = loaded
    view.set_window_start(-5.0)
    assert view.window_start == 0.0
    view.set_window_start(1e9)
    assert view.window_start == DURATION - view.window_seconds


def test_scroll_by_pages_and_reports(loaded):
    view, _ = loaded
    moves: list[float] = []
    view.windowChanged.connect(moves.append)
    view.scroll_by(0.5)  # half a 30 s window
    assert view.window_start == 15.0
    assert moves == [15.0]


def test_window_length_change_keeps_the_view_in_range(loaded):
    view, _ = loaded
    view.set_window_start(50.0)  # 60 s file, 30 s window → clamps to 30
    view.set_window_seconds(60.0)  # now the whole file: start must fall to 0
    assert view.window_start == 0.0


def test_view_without_provider_is_inert(view):
    view.set_window_start(10.0)
    view.set_annotations([Annotation(1.0, 0.0, "x")])
    view.scroll_by(1.0)
    assert view.window_start == 0.0
    assert view._curves == []


# ----- annotations -----------------------------------------------------------------


def test_annotations_draw_regions_and_lines_in_window_only(loaded):
    view, _ = loaded
    view.set_annotations(
        [
            Annotation(5.0, 2.0, "region"),  # in window: LinearRegionItem
            Annotation(10.0, 0.0, "point"),  # in window: InfiniteLine
            Annotation(55.0, 1.0, "offscreen"),  # outside the 0-30 s window
        ]
    )
    items = view._annotation_items
    assert len(items) == 2
    assert isinstance(items[0], pg.LinearRegionItem)
    assert isinstance(items[1], pg.InfiniteLine)


def test_click_hit_testing_prefers_the_inner_annotation(loaded):
    view, _ = loaded
    view.set_annotations(
        [
            Annotation(5.0, 20.0, "REM period"),
            Annotation(10.0, 1.0, "Arousal"),  # nested inside the REM span
        ]
    )
    assert view._annotation_at(10.5) == 1  # the nested one wins
    assert view._annotation_at(6.0) == 0
    assert view._annotation_at(29.0) == -1


def test_point_annotations_get_click_tolerance(loaded):
    view, _ = loaded
    view.set_annotations([Annotation(10.0, 0.0, "mark")])
    tolerance = view.window_seconds * 0.005
    assert view._annotation_at(10.0 + tolerance / 2) == 0
    assert view._annotation_at(10.0 + tolerance * 3) == -1


def test_click_selects_and_signals(loaded):
    view, _ = loaded
    view.set_annotations([Annotation(5.0, 2.0, "region")])
    selections: list[int] = []
    view.annotationSelected.connect(selections.append)
    view._on_clicked(6.0)
    assert selections == [0]
    assert view.selected == 0
    view._on_clicked(20.0)  # empty space deselects
    assert selections == [0, -1]


def test_drawn_region_is_clamped_and_empty_drags_dropped(loaded):
    view, _ = loaded
    drawn: list[tuple[float, float]] = []
    view.regionDrawn.connect(lambda lo, hi: drawn.append((lo, hi)))
    view._on_drag_finished(-2.0, 4.0)  # started before the data
    assert drawn == [(0.0, 4.0)]
    view._on_drag_finished(70.0, 80.0)  # entirely past the end: nothing
    assert len(drawn) == 1


def test_point_mark_request_is_clamped_to_the_recording(loaded):
    view, _ = loaded
    marks: list[float] = []
    view.pointMarkRequested.connect(marks.append)
    view._on_mark_requested(-3.0)
    view._on_mark_requested(80.0)  # past the 60 s duration
    assert marks == [pytest.approx(0.0), pytest.approx(60.0)]


# ----- non-bioelectric channels ----------------------------------------------------


class StimProvider(FakeProvider):
    """One EEG channel plus a trigger channel carrying integer event codes."""

    ch_names = ["C3", "TRIG"]
    ch_types = ["eeg", "stim"]

    def get_slice(self, start_s: float, stop_s: float):
        times, _data = super().get_slice(start_s, stop_s)
        data = np.vstack(
            [np.full(times.shape, CONSTANT_VOLTS), np.full(times.shape, 255.0)]
        )
        return times, data


def test_stim_channels_are_fit_to_their_own_lane(view):
    # A trigger code of 255 fed through the µV scaling would draw at
    # -i + 255/100 — straight across every EEG lane above it. Auto-fit must
    # keep it within its own lane's excursion instead.
    view.set_provider(StimProvider())
    _, y_eeg = view._curves[0].getData()
    assert y_eeg == pytest.approx(0.5)  # unchanged by the stim handling
    _, y_stim = view._curves[1].getData()
    assert np.all(np.abs(y_stim - (-1)) <= 0.4 + 1e-9)


# ----- the real mouse gesture path --------------------------------------------------


class _FakeMouseEvent:
    """Stands in for pyqtgraph's MouseDragEvent/MouseClickEvent.

    Positions are given in data coordinates and converted to the ViewBox's
    item coordinates with mapFromView — the frame the real events deliver.
    """

    def __init__(
        self,
        viewbox,
        down_x: float,
        x: float,
        *,
        finish=True,
        button=None,
        modifiers=None,
    ):
        self._button = button or QtCore.Qt.MouseButton.LeftButton
        self._down = viewbox.mapFromView(pg.Point(down_x, 0.0))
        self._pos = viewbox.mapFromView(pg.Point(x, 0.0))
        self._finish = finish
        self._modifiers = modifiers or QtCore.Qt.KeyboardModifier.NoModifier
        self.accepted = False
        self.ignored = False

    def button(self):
        return self._button

    def modifiers(self):
        return self._modifiers

    def buttonDownPos(self):
        return self._down

    def pos(self):
        return self._pos

    def isFinish(self):
        return self._finish

    def accept(self):
        self.accepted = True

    def ignore(self):
        self.ignored = True


@pytest.fixture
def exposed(loaded, qtbot):
    """The loaded view, shown and laid out so ViewBox transforms are valid."""
    view, provider = loaded
    view.show()
    qtbot.waitExposed(view)
    return view, provider


def test_left_drag_emits_the_dragged_span(exposed):
    view, _ = exposed
    drawn: list[tuple[float, float]] = []
    view.regionDrawn.connect(lambda lo, hi: drawn.append((lo, hi)))
    viewbox = view._viewbox
    move = _FakeMouseEvent(viewbox, 5.0, 8.0, finish=False)
    viewbox.mouseDragEvent(move)
    assert move.accepted
    assert viewbox._preview is not None  # live rubber-band while dragging
    finish = _FakeMouseEvent(viewbox, 5.0, 8.0, finish=True)
    viewbox.mouseDragEvent(finish)
    assert viewbox._preview is None
    assert len(drawn) == 1
    assert drawn[0][0] == pytest.approx(5.0, abs=0.05)
    assert drawn[0][1] == pytest.approx(8.0, abs=0.05)


def test_backwards_drag_is_normalized(exposed):
    view, _ = exposed
    drawn: list[tuple[float, float]] = []
    view.regionDrawn.connect(lambda lo, hi: drawn.append((lo, hi)))
    view._viewbox.mouseDragEvent(_FakeMouseEvent(view._viewbox, 8.0, 5.0))
    assert drawn[0][0] < drawn[0][1]


def test_non_left_drag_is_ignored(exposed):
    view, _ = exposed
    drawn: list[tuple[float, float]] = []
    view.regionDrawn.connect(lambda lo, hi: drawn.append((lo, hi)))
    ev = _FakeMouseEvent(
        view._viewbox, 5.0, 8.0, button=QtCore.Qt.MouseButton.RightButton
    )
    view._viewbox.mouseDragEvent(ev)
    assert ev.ignored
    assert drawn == []


def test_click_event_maps_to_data_seconds(exposed):
    view, _ = exposed
    view.set_annotations([Annotation(5.0, 2.0, "region")])
    selections: list[int] = []
    view.annotationSelected.connect(selections.append)
    view._viewbox.mouseClickEvent(_FakeMouseEvent(view._viewbox, 6.0, 6.0))
    assert selections == [0]


def test_ctrl_click_requests_a_point_mark_instead_of_selecting(exposed):
    view, _ = exposed
    view.set_annotations([Annotation(5.0, 2.0, "region")])
    marks: list[float] = []
    selections: list[int] = []
    view.pointMarkRequested.connect(marks.append)
    view.annotationSelected.connect(selections.append)
    ev = _FakeMouseEvent(
        view._viewbox,
        6.0,
        6.0,
        modifiers=QtCore.Qt.KeyboardModifier.ControlModifier,
    )
    view._viewbox.mouseClickEvent(ev)
    assert marks == [pytest.approx(6.0, abs=0.05)]
    assert selections == []  # ctrl-click marks; it must never also select


# ----- wheel and keyboard navigation -------------------------------------------------


def _wheel_event(notches: float) -> QtGui.QWheelEvent:
    from PyQt6.QtCore import QPoint, QPointF, Qt

    return QtGui.QWheelEvent(
        QPointF(0, 0),
        QPointF(0, 0),
        QPoint(0, 0),
        QPoint(0, int(notches * 120)),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )


def test_wheel_down_scrolls_forward(loaded):
    # Wheel-down (negative delta) must move forward in time — a sign flip
    # here would silently invert scrolling everywhere.
    view, _ = loaded
    view.wheelEvent(_wheel_event(-1.0))
    assert view.window_start == pytest.approx(3.0)  # +0.1 windows of 30 s
    view.wheelEvent(_wheel_event(1.0))
    assert view.window_start == pytest.approx(0.0)


def test_step_epochs_moves_by_one_epoch_length(loaded):
    # The window's Left/Right arrows drive this (keyboard routing lives in the
    # window now); the view just exposes the epoch-sized step and reports it.
    view, _ = loaded
    view.set_epoch_seconds(10.0)
    moves: list[float] = []
    view.windowChanged.connect(moves.append)
    view.step_epochs(2)
    assert view.window_start == pytest.approx(20.0)
    assert moves == [20.0]


def test_nudge_seconds_scrolls_a_fixed_amount(loaded):
    view, _ = loaded
    moves: list[float] = []
    view.windowChanged.connect(moves.append)
    view.nudge_seconds(3.0)
    assert view.window_start == pytest.approx(3.0)
    assert moves == [3.0]


# ----- epoch model (#173) ---------------------------------------------------------


def _epoch_boundaries(view) -> list[float]:
    return sorted(line.value() for line in view._epoch_items)


def _epoch_numbers(view) -> list[str]:
    # InfiniteLine stores the label text on its InfLineLabel's ``format``.
    return [
        line.label.format for line in sorted(view._epoch_items, key=lambda i: i.value())
    ]


def test_epoch_grid_draws_numbered_boundaries_in_window(loaded):
    # Default: 30 s epochs anchored at 0, 30 s window → boundaries at 0 and 30,
    # starting epochs 1 and 2.
    view, _ = loaded
    assert _epoch_boundaries(view) == pytest.approx([0.0, 30.0])
    assert _epoch_numbers(view) == ["1", "2"]


def test_epoch_length_is_independent_of_window_length(loaded):
    view, _ = loaded
    view.set_epoch_seconds(10.0)  # 10 s epochs in the same 30 s window
    assert _epoch_boundaries(view) == pytest.approx([0.0, 10.0, 20.0, 30.0])
    assert view.window_seconds == 30.0  # window unchanged


def test_epoch_seconds_clamp_to_at_least_one(loaded):
    view, _ = loaded
    view.set_epoch_seconds(0.0)
    assert view.epoch_seconds == 1.0


def test_anchor_back_and_front_fills_the_grid(loaded):
    # Anchoring at 12 s puts a boundary there and fills outward by ±epoch; the
    # boundary at the anchor starts epoch 1, the next one epoch 2.
    view, _ = loaded
    view.set_epoch_anchor(12.0)
    assert view.epoch_anchor == 12.0
    assert _epoch_boundaries(view) == pytest.approx([12.0])  # only 12 lands in 0–30
    view.set_window_start(20.0)  # window 20–50 now spans 12+30=42
    assert _epoch_boundaries(view) == pytest.approx([42.0])
    assert _epoch_numbers(view) == ["2"]


def test_epoch_grid_can_be_hidden(loaded):
    view, _ = loaded
    view.set_epochs_visible(False)
    assert view._epoch_items == []
    view.set_epochs_visible(True)
    assert len(view._epoch_items) == 2


def test_new_recording_resets_the_anchor(loaded):
    view, provider = loaded
    view.set_epoch_anchor(12.0)
    view.set_provider(provider)  # reopening must start epoch 1 at the start
    assert view.epoch_anchor == 0.0


def test_grid_follows_the_scroll(loaded):
    view, _ = loaded
    view.set_window_start(45.0)  # 60 s file, 30 s window → clamps to 30 (30–60)
    assert _epoch_boundaries(view) == pytest.approx([30.0, 60.0])


# ----- time axis ------------------------------------------------------------------


def test_time_axis_formats_clock_strings_from_an_origin(qtbot):
    axis = TimeAxis(orientation="bottom")
    axis.set_origin(datetime(2026, 6, 5, 22, 0, 0))
    axis.set_mode("clock")
    assert axis.tickStrings([0.0, 90.0], 1.0, 1.0) == ["22:00:00", "22:01:30"]


def test_time_axis_falls_back_to_elapsed_without_an_origin(qtbot):
    axis = TimeAxis(orientation="bottom")
    axis.set_mode("clock")  # asked for clock, but no origin is known
    strings = axis.tickStrings([0.0, 30.0], 1.0, 1.0)
    assert all(":" not in s for s in strings)  # plain seconds, not HH:MM:SS
