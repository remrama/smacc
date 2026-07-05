"""The app-wide light/dark color theme — a machine preference, not the lights state.

Qt's color scheme is a single global :class:`QStyleHints` for the whole app, so this
is a thin wrapper: it maps SMACC's saved theme token — ``"system"``, ``"light"``, or
``"dark"`` — onto that one setting, and builds the shared Theme menu the launcher and
session window both offer.

Kept deliberately separate from the lightswitch (#315): which palette the operator
prefers is machine/operator state, independent of the *room's* light state (the
``LightsOn``/``LightsOff`` marker) and of the portable study. ``"system"`` follows the
OS scheme live (Qt 6.8+ :meth:`unsetColorScheme`); the other two pin it.
"""

from __future__ import annotations

from collections.abc import Callable

from PyQt6 import QtCore, QtGui, QtWidgets

from . import preferences

# Human labels for each theme token (see preferences.THEMES), in menu order.
_THEME_LABELS: dict[str, str] = {
    "system": "Match system",
    "light": "Light",
    "dark": "Dark",
}


def apply(token: str) -> None:
    """Set the app-wide Qt color scheme from a theme token.

    ``"light"``/``"dark"`` pin the scheme; ``"system"`` clears the override so Qt
    follows the OS scheme (and tracks a live OS change). Any unknown token is treated
    as ``"system"``, so a hand-edited preference can never wedge the app in an
    undefined palette.
    """
    hints = QtGui.QGuiApplication.styleHints()
    assert hints is not None
    if token == "dark":
        hints.setColorScheme(QtCore.Qt.ColorScheme.Dark)
    elif token == "light":
        hints.setColorScheme(QtCore.Qt.ColorScheme.Light)
    else:
        hints.unsetColorScheme()


def build_menu(
    parent: QtWidgets.QWidget,
    menu: QtWidgets.QMenu,
    current: str,
    on_select: Callable[[str], None],
) -> QtGui.QActionGroup:
    """Fill ``menu`` with exclusive Match-system / Light / Dark actions.

    The action matching ``current`` starts checked; choosing another calls
    ``on_select(token)`` (which the caller uses to apply + persist the choice). The
    returned :class:`QActionGroup` owns the actions' mutual exclusivity — the caller
    must keep a reference to it so it isn't garbage-collected while the menu lives.
    """
    group = QtGui.QActionGroup(parent)
    group.setExclusive(True)
    for token in preferences.THEMES:
        label = _THEME_LABELS.get(token, token.title())
        action = QtGui.QAction(label, parent)
        action.setCheckable(True)
        action.setChecked(token == current)
        action.setStatusTip(f"Use the {label.lower()} color theme.")
        # Fires once per real change: the exclusive group unchecks the old action
        # (checked=False, skipped) and checks the new one (checked=True, applied).
        action.toggled.connect(
            lambda checked, chosen=token: on_select(chosen) if checked else None
        )
        group.addAction(action)
        menu.addAction(action)
    return group
