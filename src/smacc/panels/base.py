"""Shared base class and helpers for SMACC's per-modality windows."""

from __future__ import annotations

from PyQt5 import QtCore, QtGui, QtWidgets

from ..paths import LOGO_PATH
from ..session import SmaccSession


def make_section_title(text: str) -> QtWidgets.QLabel:
    """Build a centered 18pt section header.

    Uses a QFont (not a stylesheet) so the text color follows the palette and
    stays legible when the dark theme toggles.
    """
    label = QtWidgets.QLabel(text)
    label.setAlignment(QtCore.Qt.AlignCenter)
    font = QtGui.QFont()
    font.setPointSize(18)
    label.setFont(font)
    return label


class ModalityWindow(QtWidgets.QMainWindow):
    """Base class for a single modality's window.

    Each panel holds a reference to the shared :class:`SmaccSession` and emits
    markers/log lines through it. Closing the window just hides it (so it can be
    reopened with its state intact); real teardown happens when the launcher
    quits, which sets ``_quitting`` and calls :meth:`cleanup` on every panel.
    """

    TITLE = "SMACC"

    def __init__(self, session: SmaccSession, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self._quitting = False
        self.setWindowTitle(self.TITLE)
        if LOGO_PATH.is_file():
            self.setWindowIcon(QtGui.QIcon(str(LOGO_PATH)))

    def gather_state(self) -> dict:
        """Return this panel's contribution to the saved settings state."""
        return {}

    def apply_state(self, state: dict) -> None:
        """Apply the relevant keys of a loaded settings ``state`` to this panel."""

    def cleanup(self) -> None:
        """Stop any streams/timers this panel owns (called on app quit)."""

    def closeEvent(self, event):
        """Hide the window instead of destroying it, unless the app is quitting."""
        if self._quitting:
            event.accept()
        else:
            event.ignore()
            self.hide()
