"""Shared base class and helpers for SMACC's per-tool windows."""

from __future__ import annotations

import sounddevice as sd
from PyQt6 import QtCore, QtGui, QtWidgets

from .. import devices, utils
from ..paths import LOGO_PATH
from ..session import SmaccSession


def resolve_device(device: str | None, kind: str) -> int | str | None:
    """Resolve a stored device name to its WASAPI device index for sounddevice.

    Equipment bindings persist the bare device name. Passing that name straight to
    sounddevice matches it against *every* host API, and on Windows the same
    hardware appears once per host API (MME, DirectSound, WASAPI, …). A name
    short enough to escape MME's 31-char truncation is then identical across
    host APIs and sounddevice raises "Multiple input/output devices found".
    Resolving here pins the stream to the one host API SMACC enumerates (see
    :func:`smacc.panels.devices.wasapi_devices`).

    ``kind`` is :data:`smacc.devices.OUTPUT` or :data:`smacc.devices.INPUT`.
    ``None``/"" (nothing bound) stays ``None`` — callers must not open a stream
    on it, or PortAudio would fall back to its default device (#139); use
    :func:`require_device` to refuse with a pointer at the Devices window
    instead. A name with no current WASAPI match is returned unchanged, so
    opening it fails with sounddevice's usual "no device matching" error rather
    than silently using another device.
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


def describe_action(session: SmaccSession, action_key: str) -> str:
    """A short 'Equipment → device' description of where an action resolves.

    Shown read-only on each tool panel; the actual device is chosen once in
    the Devices window. An off (optional) route reads as off; equipment with
    no device bound reads as not set — there is no silent system-default
    fallback (#139).
    """
    cfg = session.devices
    equipment_key = cfg.equipment_for(action_key)
    if not equipment_key:
        return "off"
    equipment = devices.EQUIPMENT_BY_KEY.get(equipment_key)
    label = equipment.label if equipment else equipment_key
    device = cfg.device_for(action_key)
    if device:
        return f"{label} → {device}"
    return f"{label} (not set)"


def describe_equipment(session: SmaccSession, equipment_key: str) -> str:
    """A short 'Equipment → device' description of an equipment binding.

    Like :func:`describe_action`, but for the source mics the intercom reads
    directly (deliberately not routable actions — see
    :data:`smacc.devices.TALK_SOURCE`).
    """
    equipment = devices.EQUIPMENT_BY_KEY.get(equipment_key)
    label = equipment.label if equipment else equipment_key
    device = session.devices.device_for_equipment(equipment_key)
    if device:
        return f"{label} → {device}"
    return f"{label} (not set)"


def require_equipment_device(
    session: SmaccSession,
    equipment_key: str,
    kind: str,
    *,
    failure: str,
    parent: QtWidgets.QWidget | None,
) -> int | str | None:
    """Resolve equipment's bound device, or show ``failure`` and return ``None``.

    The unbound case used to fall through to PortAudio's default device; after
    #139 nothing opens implicitly — the operator is pointed at the Devices
    window instead. A bound-but-disconnected device still resolves (to its
    name), so opening it fails with the usual "no device matching" error rather
    than being silently re-routed.
    """
    equipment = devices.EQUIPMENT_BY_KEY[equipment_key]
    device = session.devices.device_for_equipment(equipment_key)
    if not device:
        session.show_error_popup(
            failure,
            f"No device is bound to {equipment.label}. Bind one in the Devices window.",
            parent=parent,
        )
        return None
    return resolve_device(device, kind)


def require_device(
    session: SmaccSession,
    action_key: str,
    kind: str,
    *,
    failure: str,
    parent: QtWidgets.QWidget | None,
) -> int | str | None:
    """Resolve an action's device via its route, or show ``failure`` and return ``None``.

    Covers both ways an action can have no device: its route is off (no
    equipment), or its equipment has nothing bound. Each error names the
    missing piece and points at the Devices window.
    """
    action = devices.ACTIONS_BY_KEY[action_key]
    equipment_key = session.devices.equipment_for(action_key)
    if not equipment_key:
        session.show_error_popup(
            failure,
            f"'{action.label}' is not routed to any equipment. Route it in the "
            "Devices window.",
            parent=parent,
        )
        return None
    return require_equipment_device(
        session, equipment_key, kind, failure=failure, parent=parent
    )


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


class PanelWindow(QtWidgets.QMainWindow):
    """Base class for a single action's window.

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
