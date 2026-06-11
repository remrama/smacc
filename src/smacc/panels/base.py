"""Shared base class and helpers for SMACC's per-modality windows."""

from __future__ import annotations

import sounddevice as sd
from PyQt6 import QtCore, QtGui, QtWidgets

from .. import devices, utils
from ..paths import LOGO_PATH
from ..session import SmaccSession


def resolve_device(device: str | None, kind: str) -> int | str | None:
    """Resolve a stored device name to its WASAPI device index for sounddevice.

    Role bindings persist the bare device name. Passing that name straight to
    sounddevice matches it against *every* host API, and on Windows the same
    hardware appears once per host API (MME, DirectSound, WASAPI, …). A name
    short enough to escape MME's 31-char truncation is then identical across
    host APIs and sounddevice raises "Multiple input/output devices found".
    Resolving here pins the stream to the one host API SMACC enumerates (see
    :func:`smacc.panels.devices.wasapi_devices`).

    ``kind`` is :data:`smacc.devices.OUTPUT` or :data:`smacc.devices.INPUT`.
    ``None``/"" (system default) stays ``None``; a name with no current WASAPI
    match is returned unchanged, so opening it fails with sounddevice's usual
    "no device matching" error rather than silently using another device.
    """
    if not device:
        return None
    chan_key = f"max_{kind}_channels"
    try:
        host_api_names = [api["name"] for api in sd.query_hostapis()]
        hostapi = host_api_names.index(devices.WASAPI_HOST_API)
        for index, info in enumerate(sd.query_devices()):
            if (
                info["hostapi"] == hostapi
                and info[chan_key] > 0
                and info["name"] == device
            ):
                return index
    except Exception:
        pass  # no WASAPI host API (or query failed): fall through to the name
    return device


def describe_target(session: SmaccSession, target_key: str) -> str:
    """A short 'Role → device' description of where a modality target resolves.

    Shown read-only on each modality panel; the actual device is chosen once in the
    Devices window. An unbound audio role reads as the system default; an unbound
    BlinkStick reads as not set; an off (optional) route reads as off.
    """
    cfg = session.devices
    role_key = cfg.role_for(target_key)
    if not role_key:
        return "off"
    role = devices.ROLES_BY_KEY.get(role_key)
    role_label = role.label if role else role_key
    device = cfg.device_for(target_key)
    if device:
        return f"{role_label} → {device}"
    if role is not None and role.kind == devices.VISUAL:
        return f"{role_label} (not set)"
    return f"{role_label} (system default)"


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
    label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
    font = QtGui.QFont()
    font.setPointSize(18)
    label.setFont(font)
    return label


def restore_spin_value(spin: QtWidgets.QDoubleSpinBox, value: object) -> bool:
    """Best-effort restore of a persisted numeric spinbox value.

    Hand-edited studies should not crash a load because one optional scalar is
    malformed. Returning False lets callers keep the widget's current/default value.
    """
    try:
        spin.setValue(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return True


class ModalityWindow(QtWidgets.QMainWindow):
    """Base class for a single modality's window.

    Each panel holds a reference to the shared :class:`SmaccSession` and emits
    markers/log lines through it. Closing the window just hides it (so it can be
    reopened with its state intact); real teardown happens when the launcher
    quits, which sets ``_quitting`` and calls :meth:`cleanup` on every panel.

    Every tool window carries its own *always-on-top* toggle (a checkable View-menu
    action) so an operator can pin just the tools they need above other apps. The
    per-window state travels with the study (collected/applied by the main window in
    a ``tool_always_on_top`` map); the launcher deliberately has no such toggle.
    """

    TITLE = "SMACC"

    def __init__(self, session: SmaccSession, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self._quitting = False
        self.setWindowTitle(self.TITLE)
        if LOGO_PATH.is_file():
            self.setWindowIcon(QtGui.QIcon(str(LOGO_PATH)))
        self._build_file_menu()
        self._build_view_menu()

    def _build_file_menu(self) -> None:
        """Add a minimal File menu carrying this window's close action.

        Closing a tool window only hides it (see :meth:`closeEvent`) — the
        session keeps running — so Ctrl+W is safe to reach for, unlike the
        session window's Ctrl+Q, which ends the whole session.
        """
        menu_bar = self.menuBar()
        assert menu_bar is not None
        fileMenu = menu_bar.addMenu("&File")
        assert fileMenu is not None
        closeAction = QtGui.QAction("&Close window", self)
        closeAction.setShortcut("Ctrl+W")
        closeAction.setStatusTip(
            f"Close the {self.TITLE} window (the session keeps running; "
            "reopen it from the session window)."
        )
        closeAction.triggered.connect(self.close)
        fileMenu.addAction(closeAction)

    def _build_view_menu(self) -> None:
        """Add a minimal View menu carrying this window's always-on-top toggle."""
        menu_bar = self.menuBar()
        assert menu_bar is not None
        viewMenu = menu_bar.addMenu("&View")
        assert viewMenu is not None
        action = QtGui.QAction("Always on &top", self)
        # Every window carries the same shortcut; the default WindowShortcut
        # context scopes each to its own window, so Ctrl+T pins whichever
        # window is active.
        action.setShortcut("Ctrl+T")
        action.setStatusTip(f"Keep the {self.TITLE} window above other applications.")
        action.setCheckable(True)
        action.toggled.connect(self.toggle_always_on_top)
        viewMenu.addAction(action)
        self._always_on_top_action = action

    def is_always_on_top(self) -> bool:
        """Return whether this window's always-on-top toggle is currently on."""
        return self._always_on_top_action.isChecked()

    def set_always_on_top(self, enabled: bool) -> None:
        """Set always-on-top without logging (used when applying saved settings).

        Sets the menu action's checked state (with signals blocked so the toggled
        handler doesn't fire) and applies the window flag directly.
        """
        self._always_on_top_action.blockSignals(True)
        self._always_on_top_action.setChecked(enabled)
        self._always_on_top_action.blockSignals(False)
        self._apply_always_on_top(enabled)

    def toggle_always_on_top(self, enabled: bool) -> None:
        """Handle a user toggle of this window's always-on-top action (logs the change)."""
        self._apply_always_on_top(enabled)
        self.session.log_interaction(
            f"{self.TITLE} always-on-top {'enabled' if enabled else 'disabled'}"
        )

    def _apply_always_on_top(self, enabled: bool) -> None:
        """Apply the always-on-top window flag, re-showing if the window was visible.

        Re-applying ``WindowStaysOnTopHint`` hides the window, so visibility must be
        read *before* the flag is set (afterwards it is always False — the window
        would silently vanish on every toggle). Only a previously-visible window is
        re-shown, so toggling the flag on a hidden tool window (e.g. while applying
        loaded settings) doesn't pop it open.
        """
        was_visible = self.isVisible()
        self.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint, enabled)
        if was_visible:
            self.show()

    def gather_state(self) -> dict:
        """Return this panel's contribution to the saved settings state."""
        return {}

    def apply_state(self, state: dict) -> None:
        """Apply the relevant keys of a loaded settings ``state`` to this panel."""

    def cleanup(self) -> None:
        """Stop any streams/timers this panel owns (called on app quit)."""

    def refresh_device_indicator(self) -> None:
        """Update this panel's read-only device indicator from ``session.devices``.

        Called when the Devices window changes a binding/route (or a study loads);
        panels that consume a device override this to re-render their indicator.
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
