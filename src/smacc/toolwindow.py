"""Shared base for launcher-managed tool windows (session, designer, analyze).

The launcher opens these top-level windows, hides itself, and reappears when the
tool emits :attr:`ToolWindow.closed` from its ``closeEvent``. Keeping the signal on
one base lets the launcher manage every tool through the same small contract.
"""

from __future__ import annotations

from PyQt6 import QtCore, QtWidgets


class ToolWindow(QtWidgets.QMainWindow):
    """A launcher-managed window that signals when it has closed."""

    # Emitted from closeEvent once the window has accepted the close, so the
    # launcher (the persistent root window) can bring itself back.
    closed = QtCore.pyqtSignal()
