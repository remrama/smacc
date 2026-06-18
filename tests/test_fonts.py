"""Tests for the bundled B612 GUI font (``smacc.fonts``, #279)."""

from __future__ import annotations

from PyQt6 import QtGui

from smacc import fonts
from smacc.paths import FONTS_DIR


def test_bundled_font_files_present():
    """Every face ``smacc.fonts`` registers ships in the assets dir."""
    for name in fonts._FONT_FILES:
        assert (FONTS_DIR / name).is_file(), f"missing bundled font {name}"
    # The OFL license must travel with the fonts (a redistribution requirement).
    assert (FONTS_DIR / "OFL.txt").is_file()


def test_register_fonts_reports_both_families(qapp):
    """Registration loads B612 and B612 Mono under the names the code matches on.

    Guards the #268 lesson: the family strings in the code must equal the names
    the TTFs actually declare, or QFont silently falls back to a system font.
    """
    families = fonts.register_fonts()
    assert fonts.UI_FAMILY in families
    assert fonts.MONO_FAMILY in families


def test_apply_app_font_sets_b612_base(qapp):
    """Applying the font makes B612 the base application font (size preserved)."""
    original = qapp.font()
    try:
        fonts.apply_app_font(qapp)
        assert fonts.UI_FAMILY in qapp.font().families()
        assert qapp.font().pointSize() == original.pointSize()
    finally:
        qapp.setFont(original)  # don't leak the font into later tests' metrics


def test_mono_font_is_b612_mono(qapp):
    """The mono helper points at B612 Mono, with a generic-monospace fallback."""
    font = fonts.mono_font(14, bold=True)
    assert font.families()[0] == fonts.MONO_FAMILY
    assert font.styleHint() == QtGui.QFont.StyleHint.Monospace
    assert font.pointSize() == 14
    assert font.bold()
