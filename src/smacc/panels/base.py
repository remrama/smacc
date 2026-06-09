"""Shared base class and helpers for SMACC's per-modality windows."""

from __future__ import annotations

from PyQt5 import QtCore, QtGui, QtWidgets

from .. import utils
from ..paths import LOGO_PATH
from ..session import SmaccSession


def current_device_key(combo: QtWidgets.QComboBox) -> str:
    """Return the persisted key for a device combo's current row ("" when empty).

    Pickers that carry a separate stable id (the recorder's raw input name, a
    BlinkStick serial) keep it as item *data*; the noise/intercom pickers use the
    visible *text*. Either way this returns the value to persist for the selection,
    so save/restore is uniform across panels.
    """
    index = combo.currentIndex()
    if index < 0:
        return ""
    data = combo.itemData(index)
    return str(data) if data not in (None, "") else combo.itemText(index)


def select_saved_device(combo: QtWidgets.QComboBox, saved: str | None) -> bool:
    """Select the row whose key equals ``saved``; return True iff one matched.

    A blank/missing ``saved`` or an unplugged device (no match) leaves the current
    selection untouched and returns False, so the caller can flag the miss and keep
    the default.
    """
    keys = [
        str(d) if (d := combo.itemData(i)) not in (None, "") else combo.itemText(i)
        for i in range(combo.count())
    ]
    index = utils.index_of_device(keys, saved)
    if index is None:
        return False
    combo.setCurrentIndex(index)
    return True


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

    def refresh_devices(self) -> None:
        """Re-enumerate this panel's device picker (override where it has one).

        Called by the window's "Refresh devices" action so a device plugged in
        after launch becomes selectable; device-bearing panels override this to
        re-scan while preserving the current selection.
        """

    def is_streaming(self) -> bool:
        """True if this panel currently holds an open audio stream.

        The refresh coordinator checks this before re-initializing PortAudio (which
        would invalidate any live stream); panels that own streams override it.
        """
        return False

    def closeEvent(self, event):
        """Hide the window instead of destroying it, unless the app is quitting."""
        if self._quitting:
            event.accept()
        else:
            event.ignore()
            self.hide()
