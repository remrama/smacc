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
from smacc.eeg.staging import StageEpoch
from smacc.eeg.view import (
    DEFAULT_TYPE_SCALES,
    HypnogramStrip,
    RaterOverlay,
    TimeAxis,
    TraceView,
)

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
    # EMG (50 µV) sits on its larger default lane (200 µV) → +0.25 above center.
    emg = CONSTANT_VOLTS * 1e6 / DEFAULT_TYPE_SCALES["emg"]
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


# ----- other-rater overlays (#181d) -----------------------------------------


def test_overlays_draw_only_visible_layers_in_window(loaded):
    view, _ = loaded
    view.set_overlays(
        [
            RaterOverlay(
                "alice",
                [Annotation(5.0, 2.0, "a"), Annotation(55.0, 0.0, "offscreen")],
                (230, 159, 0),
                True,
            ),
            RaterOverlay("bob", [Annotation(8.0, 0.0, "b")], (0, 158, 115), False),
        ]
    )
    # Only alice's in-window region: her offscreen mark and hidden bob are skipped.
    assert len(view._overlay_items) == 1
    assert isinstance(view._overlay_items[0], pg.LinearRegionItem)


def test_overlays_are_not_click_selectable(loaded):
    view, _ = loaded
    view.set_annotations([Annotation(20.0, 0.0, "mine")])
    view.set_overlays(
        [RaterOverlay("alice", [Annotation(10.0, 0.0, "theirs")], (230, 159, 0), True)]
    )
    assert view._annotation_at(10.0) == -1  # a peer's mark selects nothing
    assert view._annotation_at(20.0) == 0  # the editable mark still selectable


def test_overlays_redraw_on_scroll(loaded):
    view, _ = loaded
    view.set_overlays(
        [RaterOverlay("alice", [Annotation(40.0, 0.0, "late")], (230, 159, 0), True)]
    )
    assert view._overlay_items == []  # 40 s mark is outside the 0–30 s window
    view.set_window_start(35.0)
    assert len(view._overlay_items) == 1  # now in view


def test_set_provider_clears_overlays(loaded):
    view, _ = loaded
    view.set_overlays(
        [RaterOverlay("alice", [Annotation(5.0, 0.0, "x")], (230, 159, 0), True)]
    )
    assert view._overlay_items
    view.set_provider(FakeProvider())
    assert view._overlays == []
    assert view._overlay_items == []


# ----- session-log overlay (#125) -------------------------------------------


def _log_mark(seconds, level="INFO", tooltip="x"):
    from smacc.eeg.view import LogMark

    return LogMark(seconds, level, tooltip)


def test_log_marks_draw_only_inside_the_window(loaded):
    view, _ = loaded
    view.set_log_marks([_log_mark(5.0), _log_mark(15.0), _log_mark(45.0, "WARNING")])
    # The 0–30 s window holds the first two; the 45 s mark is offscreen.
    assert len(view._log_items) == 2
    assert all(isinstance(item, pg.InfiniteLine) for item in view._log_items)


def test_log_marks_redraw_on_scroll(loaded):
    view, _ = loaded
    view.set_log_marks([_log_mark(45.0)])
    assert view._log_items == []  # outside the 0–30 s window
    view.set_window_start(35.0)
    assert len(view._log_items) == 1


def test_log_marks_are_not_click_selectable(loaded):
    view, _ = loaded
    view.set_annotations([Annotation(20.0, 0.0, "mine")])
    view.set_log_marks([_log_mark(10.0)])
    # A log mark is read-only context: a click near it selects no annotation.
    assert view._annotation_at(10.0) == -1
    assert view._annotation_at(20.0) == 0


def test_set_log_marks_arms_the_lane_slide(loaded):
    view, _ = loaded
    assert view._viewbox._log_lane_active is False
    view.set_log_marks([_log_mark(5.0)])
    assert view._viewbox._log_lane_active is True
    view.set_log_marks([])  # cleared → slide disarmed
    assert view._viewbox._log_lane_active is False


def test_set_provider_clears_log_marks(loaded):
    view, _ = loaded
    view.set_log_marks([_log_mark(5.0)])
    assert view._log_items
    view.set_provider(FakeProvider())
    assert view._log_marks == []
    assert view._log_items == []


def test_pick_mode_emits_time_instead_of_selecting(loaded):
    view, _ = loaded
    view.set_annotations([Annotation(6.0, 0.0, "mine")])
    picked: list[float] = []
    selections: list[int] = []
    view.timePicked.connect(picked.append)
    view.annotationSelected.connect(selections.append)
    view.set_pick_mode(True)
    view._on_clicked(6.0)
    assert picked == [6.0]
    assert selections == []  # no annotation selection while picking
    assert view.selected == -1
    view.set_pick_mode(False)
    view._on_clicked(6.0)
    assert selections == [0]  # normal selection resumes


def test_pick_mode_swallows_drags_and_ctrl_clicks(exposed):
    # A drag or ctrl-click while aiming an alignment must not edit the rater's
    # marks: pick mode swallows both (no region, no point mark).
    view, _ = exposed
    drawn: list[tuple[float, float]] = []
    marks: list[float] = []
    view.regionDrawn.connect(lambda lo, hi: drawn.append((lo, hi)))
    view.pointMarkRequested.connect(marks.append)
    view.set_pick_mode(True)
    viewbox = view._viewbox
    viewbox.mouseDragEvent(
        _FakeMouseEvent(viewbox, 5.0, 8.0, start=True, finish=False, down_y=-1.0)
    )
    viewbox.mouseDragEvent(_FakeMouseEvent(viewbox, 5.0, 8.0, finish=True, down_y=-1.0))
    assert drawn == []  # no stray annotation while pairing
    ctrl = _FakeMouseEvent(
        viewbox, 6.0, 6.0, modifiers=QtCore.Qt.KeyboardModifier.ControlModifier
    )
    picked: list[float] = []
    view.timePicked.connect(picked.append)
    viewbox.mouseClickEvent(ctrl)
    assert marks == []  # ctrl-click drops no mark in pick mode
    assert picked == [pytest.approx(6.0, abs=0.05)]  # it picks the time instead


def test_disarming_the_lane_clears_a_stale_slide_flag(loaded):
    view, _ = loaded
    view.set_log_marks([_log_mark(5.0)])
    view._viewbox._sliding = True  # as if a finish were lost mid-drag
    view.set_log_marks([])  # disarming the lane must reset the flag
    assert view._viewbox._sliding is False


def test_lane_drag_slides_the_log_not_a_region(exposed):
    view, _ = exposed
    view.set_log_marks([_log_mark(5.0)])
    slid: list[float] = []
    drawn: list[tuple[float, float]] = []
    view.logSlideFinished.connect(slid.append)
    view.regionDrawn.connect(lambda lo, hi: drawn.append((lo, hi)))
    viewbox = view._viewbox
    # A drag starting in the top log lane (down_y near the 0.6 top of the range)
    # slides the log by the dragged seconds; no region is drawn.
    viewbox.mouseDragEvent(
        _FakeMouseEvent(viewbox, 5.0, 9.0, start=True, finish=False, down_y=0.55)
    )
    viewbox.mouseDragEvent(_FakeMouseEvent(viewbox, 5.0, 9.0, finish=True, down_y=0.55))
    assert drawn == []
    assert len(slid) == 1
    assert slid[0] == pytest.approx(4.0, abs=0.1)  # dragged +4 s


def test_drag_below_the_lane_still_draws_a_region(exposed):
    view, _ = exposed
    view.set_log_marks([_log_mark(5.0)])  # lane armed, but the drag starts below it
    drawn: list[tuple[float, float]] = []
    view.regionDrawn.connect(lambda lo, hi: drawn.append((lo, hi)))
    viewbox = view._viewbox
    viewbox.mouseDragEvent(
        _FakeMouseEvent(viewbox, 5.0, 8.0, start=True, finish=False, down_y=-1.0)
    )
    viewbox.mouseDragEvent(_FakeMouseEvent(viewbox, 5.0, 8.0, finish=True, down_y=-1.0))
    assert len(drawn) == 1  # ordinary annotation drag, not a slide


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
        start=False,
        down_y: float = 0.0,
        button=None,
        modifiers=None,
    ):
        self._button = button or QtCore.Qt.MouseButton.LeftButton
        self._down = viewbox.mapFromView(pg.Point(down_x, down_y))
        self._pos = viewbox.mapFromView(pg.Point(x, down_y))
        self._finish = finish
        self._start = start
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

    def isStart(self):
        return self._start

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


# ----- channel selection + per-type display (#177) --------------------------------


def test_hiding_channels_draws_only_the_chosen_curves(loaded):
    view, _ = loaded  # FakeProvider: C3, C4, EOG, EMG
    view.set_visible_channels([0, 2])  # C3, EOG
    assert len(view._curves) == 2
    assert view.visible_channels == ["C3", "EOG"]


def test_reordering_channels_sets_the_lane_order(loaded):
    view, _ = loaded
    view.set_visible_channels([3, 0])  # EMG on top lane, then C3
    assert view.visible_channels == ["EMG", "C3"]
    _, y_emg = view._curves[0].getData()  # EMG 50 µV on its 200 µV lane → +0.25
    assert y_emg == pytest.approx(0.25)  # lane 0 centered at y = 0
    _, y_c3 = view._curves[1].getData()  # C3 50 µV on the 100 µV base → +0.5
    assert y_c3 == pytest.approx(-1 + 0.5)  # lane 1 centered at y = -1


def test_empty_or_out_of_range_selection_is_ignored(loaded):
    view, _ = loaded
    view.set_visible_channels([])  # nothing valid → keep the current selection
    assert len(view._curves) == 4
    view.set_visible_channels([99, -1])  # out of range → ignored
    assert len(view._curves) == 4


def test_per_type_scale_overrides_the_base(loaded):
    view, _ = loaded
    view.set_type_scale("eeg", 50.0)  # EEG channels now on a 50 µV lane
    _, y_c3 = view._curves[0].getData()  # C3 (eeg) 50 µV / 50 → 1.0
    assert y_c3 == pytest.approx(1.0)
    _, y_eog = view._curves[2].getData()  # EOG (no override) still on 100 µV base
    assert y_eog == pytest.approx(-2 + 0.5)


def test_per_type_filter_applies_only_to_its_type(loaded):
    view, _ = loaded
    view.set_type_spec("emg", dsp.FilterSpec(highpass=1.0))  # removes EMG's DC
    _, y_c3 = view._curves[0].getData()  # unfiltered EEG unchanged
    assert y_c3 == pytest.approx(0.5)
    _, y_emg = view._curves[3].getData()  # EMG flattened toward its lane center
    assert np.allclose(y_emg, -3, atol=0.05)


def test_effective_spec_and_scale_fall_back_to_the_base(loaded):
    view, _ = loaded
    assert view.effective_scale("eeg") == view.scale_uv  # no override → base 100
    assert view.effective_scale("emg") == 200.0  # default per-type override
    assert view.effective_spec("eeg") == view.spec  # base
    view.set_type_spec("eog", dsp.FilterSpec(notch=50.0))
    assert view.effective_spec("eog") == dsp.FilterSpec(notch=50.0)


# ----- snapshot for figure export (#180) ------------------------------------------


def test_lane_traces_match_exactly_what_the_curves_draw(loaded):
    # The export reuses _lane_traces, so this parity is the guard that the
    # refactor kept the on-screen picture byte-for-byte.
    view, _ = loaded
    times, lanes = view._lane_traces()
    assert len(lanes) == len(view._curves)
    for entry in lanes:
        x, y = view._curves[entry.lane].getData()
        assert np.allclose(x, times)
        assert np.allclose(y, -entry.lane + entry.values)


def test_build_snapshot_traces_match_the_visible_channels(loaded):
    view, _ = loaded
    view.set_visible_channels([0, 3])  # C3 (eeg), EMG (emg)
    snap = view.build_snapshot(marks=[], show_epochs=False)
    assert [t.name for t in snap.traces] == ["C3", "EMG"]
    assert [t.lane for t in snap.traces] == [0, 1]
    assert [t.ch_type for t in snap.traces] == ["eeg", "emg"]
    # C3 50 µV on the 100 µV base → +0.5; EMG 50 µV on its 200 µV lane → +0.25.
    assert np.allclose(snap.traces[0].values, 0.5)
    assert np.allclose(snap.traces[1].values, 0.25)
    assert (snap.traces[0].scale_uv, snap.traces[1].scale_uv) == (100.0, 200.0)


def test_build_snapshot_marks_are_window_relative_and_relabeled(loaded):
    view, _ = loaded
    view.set_window_start(20.0)  # window 20–50
    snap = view.build_snapshot(marks=[(25.0, 2.0, "clean")], show_epochs=False)
    assert len(snap.marks) == 1
    assert snap.marks[0].onset == pytest.approx(5.0)  # 25 − 20
    assert snap.marks[0].duration == 2.0
    assert snap.marks[0].label == "clean"
    assert snap.times[0] == pytest.approx(0.0)  # times window-relative too


def test_build_snapshot_epochs_follow_the_toggle(loaded):
    view, _ = loaded  # 30 s epochs, anchor 0, window 0–30
    assert view.build_snapshot(marks=[], show_epochs=False).epochs == ()
    on = view.build_snapshot(marks=[], show_epochs=True)
    assert [(e.x, e.number) for e in on.epochs] == [(0.0, "1"), (30.0, "2")]


def test_build_snapshot_time_axis_label_follows_mode(loaded):
    view, _ = loaded
    snap = view.build_snapshot(marks=[], show_epochs=False)
    assert snap.time_axis_label == "time (s)"  # no origin → elapsed
    assert len(snap.time_ticks) == 7
    view.set_time_origin(datetime(2026, 6, 5, 22, 0, 0))
    view.set_time_axis_mode("clock")
    assert (
        view.build_snapshot(marks=[], show_epochs=False).time_axis_label == "clock time"
    )


# ----- sleep-staging overlay (#182) ------------------------------------------


def test_set_hypnogram_draws_a_band_per_visible_scored_epoch(loaded):
    view, _ = loaded
    view.set_window_seconds(60.0)  # whole 60 s file in view
    view.set_hypnogram(
        [StageEpoch(0.0, 30.0, "W"), StageEpoch(30.0, 30.0, "N2")],
        {"W": (242, 201, 76), "N2": (74, 144, 200)},
    )
    assert len(view._stage_band_items) == 2


def test_stage_bands_only_draw_the_epochs_in_view(loaded):
    view, _ = loaded
    view.set_window_seconds(30.0)
    view.set_window_start(0.0)  # only [0, 30) is visible
    view.set_hypnogram(
        [StageEpoch(0.0, 30.0, "W"), StageEpoch(30.0, 30.0, "N2")],
        {"W": (242, 201, 76), "N2": (74, 144, 200)},
    )
    assert len(view._stage_band_items) == 1


def test_a_stage_with_no_colour_tints_nothing(loaded):
    view, _ = loaded
    view.set_hypnogram([StageEpoch(0.0, 30.0, "N2")], {})  # no colour for N2
    assert view._stage_band_items == []


def test_stage_focus_brackets_the_left_edge_epoch(loaded):
    view, _ = loaded
    view.set_stage_focus(True)
    assert view._focused_epoch_item is not None
    view.set_stage_focus(False)
    assert view._focused_epoch_item is None


def test_new_provider_drops_the_previous_hypnogram(loaded):
    view, _ = loaded
    view.set_hypnogram([StageEpoch(0.0, 30.0, "N2")], {"N2": (74, 144, 200)})
    view.set_provider(FakeProvider())  # a different recording
    assert view._stage_epochs == []
    assert view._stage_band_items == []


# ----- hypnogram overview strip (#182c) --------------------------------------


def _press(x, width=600.0):
    return QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseButtonPress,
        QtCore.QPointF(x, 15.0),
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )


def test_strip_click_emits_a_seek_at_the_clicked_time(qtbot):
    strip = HypnogramStrip()
    qtbot.addWidget(strip)
    strip.resize(600, 30)
    strip.set_data(600.0, [], {})
    captured: list[float] = []
    strip.seekRequested.connect(captured.append)
    strip.mousePressEvent(_press(300.0))  # half width → half the recording
    assert captured == [pytest.approx(300.0)]


def test_strip_ignores_clicks_with_no_recording(qtbot):
    strip = HypnogramStrip()
    qtbot.addWidget(strip)
    strip.resize(600, 30)
    captured: list[float] = []
    strip.seekRequested.connect(captured.append)
    strip.mousePressEvent(_press(300.0))  # duration is 0 → no seek
    assert captured == []


def test_strip_paints_without_crashing(qtbot):
    strip = HypnogramStrip()
    qtbot.addWidget(strip)
    strip.resize(600, 30)
    strip.set_data(600.0, [StageEpoch(0.0, 30.0, "N2")], {"N2": (74, 144, 200)})
    strip.set_window(30.0, 30.0)
    strip.repaint()  # exercise paintEvent (cells + window marker)
