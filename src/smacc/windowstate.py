"""Restore and capture window geometry uniformly across every SMACC window.

The launcher, the main session window, each tool window, and the Analyzer window
all reopen where they were last left. The geometry itself is stored machine-local
in ``preferences.yaml`` as a per-window map (see :mod:`smacc.preferences`); these
small Qt helpers are the bridge between that pure data and a live ``QWidget``.

Kept separate from :mod:`smacc.preferences` (which stays Qt-free and unit-testable
without a display) and from any one window class, since windows of different base
classes (``QMainWindow``, ``ToolWindow``, ``PanelWindow``) all need it.
"""

from __future__ import annotations

from typing import Any

from PyQt6 import QtCore, QtWidgets


def geometry_of(window: QtWidgets.QWidget) -> dict[str, int]:
    """Return ``window``'s current position and size as a ``{x, y, w, h}`` mapping."""
    return {
        "x": window.x(),
        "y": window.y(),
        "w": window.width(),
        "h": window.height(),
    }


def is_on_screen(rect: QtCore.QRect) -> bool:
    """True if ``rect`` overlaps any connected screen's available area.

    The off-screen guard: a saved position is only honored when it still lands on a
    currently-connected display, so unplugging a monitor (or a different multi-head
    layout) can't strand a window where it can't be reached.
    """
    screens = QtWidgets.QApplication.screens()
    return any(screen.availableGeometry().intersects(rect) for screen in screens)


def restore_geometry(
    window: QtWidgets.QWidget,
    geometry: dict[str, Any],
    *,
    default_size: tuple[int, int],
) -> bool:
    """Apply a saved ``{x, y, w, h}`` to ``window``; return True iff a position was set.

    The size is always applied (falling back to ``default_size`` when the saved
    width/height are missing). The position is applied only when both coordinates
    are present *and* the resulting rectangle is still on a connected screen (see
    :func:`is_on_screen`); otherwise the caller is told (``False``) so it can place
    the window at its own first-run default.
    """
    default_w, default_h = default_size
    width = _int_or(geometry.get("w"), default_w)
    height = _int_or(geometry.get("h"), default_h)
    window.resize(width, height)
    x, y = geometry.get("x"), geometry.get("y")
    if x is None or y is None:
        return False
    rect = QtCore.QRect(int(x), int(y), width, height)
    if not is_on_screen(rect):
        return False
    window.move(int(x), int(y))
    return True


def _int_or(value: Any, fallback: int) -> int:
    """Coerce ``value`` to int, falling back to ``fallback`` on None/garbage."""
    try:
        if value is None:
            return fallback
        return int(value)
    except (TypeError, ValueError):
        return fallback
