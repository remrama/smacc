"""Tests for the shared window-geometry helpers (need a QApplication, no hardware).

``restore_geometry`` resizes a real widget and applies an on-screen position; the
off-screen guard is exercised by feeding a far-away rectangle. A throwaway
``QWidget`` (registered with ``qtbot``) stands in for any SMACC window, since the
helpers work on any ``QWidget`` regardless of its base class.
"""

from __future__ import annotations

from PyQt6 import QtCore, QtWidgets

from smacc import windowstate


def test_geometry_of_round_trips_through_restore(qtbot):
    widget = QtWidgets.QWidget()
    qtbot.addWidget(widget)
    widget.setGeometry(120, 90, 400, 300)
    captured = windowstate.geometry_of(widget)
    assert captured == {"x": 120, "y": 90, "w": 400, "h": 300}

    other = QtWidgets.QWidget()
    qtbot.addWidget(other)
    assert windowstate.restore_geometry(other, captured, default_size=(640, 560))
    assert other.width() == 400 and other.height() == 300


def test_restore_geometry_uses_default_size_when_missing(qtbot):
    widget = QtWidgets.QWidget()
    qtbot.addWidget(widget)
    # No saved w/h: the default size is applied, and with no x/y it reports False.
    placed = windowstate.restore_geometry(widget, {}, default_size=(333, 222))
    assert placed is False
    assert widget.width() == 333 and widget.height() == 222


def test_restore_geometry_rejects_offscreen_position(qtbot):
    widget = QtWidgets.QWidget()
    qtbot.addWidget(widget)
    far = {"x": 100_000, "y": 100_000, "w": 400, "h": 300}
    placed = windowstate.restore_geometry(widget, far, default_size=(640, 560))
    assert placed is False  # off every screen → caller falls back to its default
    # Size is still applied even when the position is rejected.
    assert widget.width() == 400 and widget.height() == 300


def test_restore_geometry_accepts_onscreen_position(qtbot):
    screen = QtWidgets.QApplication.primaryScreen()
    avail = screen.availableGeometry()
    widget = QtWidgets.QWidget()
    qtbot.addWidget(widget)
    geom = {"x": avail.left() + 10, "y": avail.top() + 10, "w": 300, "h": 200}
    assert windowstate.restore_geometry(widget, geom, default_size=(640, 560))
    assert windowstate.is_on_screen(
        QtCore.QRect(widget.x(), widget.y(), widget.width(), widget.height())
    )


def test_is_on_screen_true_for_primary_screen():
    avail = QtWidgets.QApplication.primaryScreen().availableGeometry()
    assert windowstate.is_on_screen(avail)
