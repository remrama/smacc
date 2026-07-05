"""Tests for smacc.theme — the app-wide color-theme wrapper and its menu builder.

The offscreen platform never reflects ``QStyleHints.colorScheme()`` back (it always
reads Unknown), so these don't assert the resulting scheme; they assert that every
token is callable (the "system" path exercises the Qt 6.8 ``unsetColorScheme``) and
that the shared menu checks the right action and reports selections.
"""

from __future__ import annotations

from PyQt6 import QtWidgets

from smacc import preferences, theme


def test_apply_accepts_every_token(qtbot):
    # Callable for each token, including an unknown one (treated as "system", so it
    # takes the unsetColorScheme path rather than raising).
    for token in ("system", "light", "dark", "not-a-theme"):
        theme.apply(token)


def test_build_menu_checks_current_and_reports_selection(qtbot):
    menu = QtWidgets.QMenu()
    chosen: list[str] = []
    group = theme.build_menu(menu, menu, current="dark", on_select=chosen.append)

    actions = group.actions()
    assert len(actions) == len(preferences.THEMES)  # one action per token
    checked = [a for a in actions if a.isChecked()]
    assert len(checked) == 1 and checked[0].text() == "Dark"  # current starts checked
    assert chosen == []  # setting the initial check fired no selection

    # Choosing another reports exactly that token once (the exclusive group unchecks
    # the old action, whose toggled(False) is ignored).
    light = next(a for a in actions if a.text() == "Light")
    light.trigger()
    assert chosen == ["light"]
