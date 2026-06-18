"""Bundled GUI typeface (B612) registration and helpers (#279).

SMACC ships the **B612** family — the typeface Airbus commissioned for aircraft
cockpit instrument displays, optimised for glanceable, low-fatigue reading in
low light — and registers it at startup so the app renders with a consistent
typeface on every machine instead of depending on a system-installed font. That
matches SMACC's context: a control surface read at a glance, in a dark room,
late at night (see the dream-engineering skill).

The proportional **B612** is the base application font; the fixed-pitch
**B612 Mono** is used for the numeric/fixed-width readouts an operator scans at a
glance — the live log preview, marker port codes, level meters, and countdown
timers — where alignment and stable digit widths matter most.

The font is the *app's* identity; the manual uses IBM Plex (see #268). The brand
thread across both is the indigo + crescent, not a shared typeface.
"""

from __future__ import annotations

import logging

from PyQt6 import QtGui, QtWidgets

from .paths import FONTS_DIR

logger = logging.getLogger("smacc")

# The internal family names the bundled faces declare in their name tables. QFont
# matches on these exact strings, so they must equal what the files report — a
# mismatch silently falls back to a system font (the lesson learned bundling the
# manual's fonts, #268). Verified against the TTFs: "B612" and "B612 Mono".
UI_FAMILY = "B612"
MONO_FAMILY = "B612 Mono"

# The bundled faces, registered at startup. The proportional UI face ships its
# italics (a few labels are italic); the mono readouts are never italic, so
# B612 Mono ships Regular + Bold only — kept lean on purpose.
_FONT_FILES = (
    "B612-Regular.ttf",
    "B612-Bold.ttf",
    "B612-Italic.ttf",
    "B612-BoldItalic.ttf",
    "B612Mono-Regular.ttf",
    "B612Mono-Bold.ttf",
)


def register_fonts() -> list[str]:
    """Load the bundled B612 faces into Qt's application font database.

    Returns the family names Qt actually registered (sorted), for logging and
    tests. Requires a live ``QGuiApplication``. A missing or unreadable file is
    logged and skipped rather than raising: the app still runs on Qt's default
    font, and Qt's per-glyph fallback covers anything B612 lacks (e.g. emoji).
    """
    families: set[str] = set()
    for name in _FONT_FILES:
        path = FONTS_DIR / name
        font_id = QtGui.QFontDatabase.addApplicationFont(str(path))
        if font_id == -1:
            logger.warning("Could not load bundled font %s", path)
            continue
        families.update(QtGui.QFontDatabase.applicationFontFamilies(font_id))
    return sorted(families)


def apply_app_font(app: QtWidgets.QApplication) -> None:
    """Register the bundled fonts and set B612 as the base application font.

    Swaps only the *family* of the platform's default font, preserving its point
    size, so the whole UI flips to B612 without resizing. Called once per process
    from each entry point (the session app and the EEG Annotator). If
    registration fails it leaves the default font in place (the warning is
    already logged), so a broken bundle degrades to the system font, not tofu.
    """
    registered = register_fonts()
    if UI_FAMILY not in registered:
        return
    base = app.font()
    base.setFamilies([UI_FAMILY])
    app.setFont(base)
    logger.debug("Registered bundled fonts: %s", ", ".join(registered))


def mono_font(point_size: int | None = None, *, bold: bool = False) -> QtGui.QFont:
    """A B612 Mono ``QFont`` for numeric / fixed-width readouts.

    Lists a generic monospace after B612 Mono and sets the Monospace style hint,
    so a readout still lands on *some* fixed-pitch font if the bundled face
    didn't register — never on the proportional default. With no ``point_size``
    it inherits the application font's current size.
    """
    font = QtGui.QFont()
    font.setFamilies([MONO_FAMILY, "monospace"])
    font.setStyleHint(QtGui.QFont.StyleHint.Monospace)
    if point_size is not None:
        font.setPointSize(point_size)
    font.setBold(bold)
    return font
