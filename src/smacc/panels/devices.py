"""Devices window: bind physical devices to roles, then route modalities to roles.

This is the one place device selection lives (#39): a *Roles* section binds each
role (bedroom output, control-room output, bedroom mic, BlinkStick) to a device,
and a *Routing* section points each modality at a role. The modality windows show
only a read-only indicator of what they resolve to. The edited config lives on
``session.devices``; :attr:`changed` fires whenever it is edited so the window can
refresh the modality indicators.
"""

from __future__ import annotations

from functools import partial

import sounddevice as sd
from blinkstick import blinkstick
from PyQt6 import QtCore, QtWidgets

from .. import devices
from ..session import SmaccSession
from .base import (
    ModalityWindow,
    current_device_key,
    make_section_title,
    select_saved_device,
)

_DEFAULT_LABEL = "(system default)"
_NONE_LABEL = "(none)"


def wasapi_devices(kind: str) -> list[str]:
    """Return the WASAPI ``"output"`` or ``"input"`` device names (best effort).

    Only WASAPI devices are listed, so the bare device name is returned (no
    ", Windows WASAPI" suffix — it added nothing and is what gets persisted as a
    role binding). sounddevice still resolves a bare name to the right device, and
    older settings that stored the suffixed form are normalized on load (see
    :func:`smacc.devices.strip_wasapi_suffix`).
    """
    chan_key = "max_output_channels" if kind == devices.OUTPUT else "max_input_channels"
    try:
        host_api_names = [api["name"] for api in sd.query_hostapis()]
        hostapi = (
            host_api_names.index(devices.WASAPI_HOST_API)
            if devices.WASAPI_HOST_API in host_api_names
            else None
        )
        out = []
        for device in sd.query_devices():
            if device[chan_key] <= 0:
                continue
            if hostapi is not None and device["hostapi"] != hostapi:
                continue
            out.append(device["name"])
        return out
    except Exception:
        return []


def blinkstick_devices() -> list[tuple[str, str]]:
    """Return ``(label, serial)`` for each connected BlinkStick (best effort)."""
    try:
        return [
            (
                f"{d.device.product_name} v{d.device.version_number} "
                f"(Serial No. {d.device.serial_number})",
                d.device.serial_number,
            )
            for d in blinkstick.find_all()
        ]
    except Exception:
        return []


class DevicesWindow(ModalityWindow):
    """Bind devices to roles and route modalities to roles (edits session.devices)."""

    TITLE = "Devices"

    # Fired whenever a binding/route changes, so the window can refresh indicators.
    changed = QtCore.pyqtSignal()
    # Fired by the Refresh button; the session window runs the same rescan as
    # File ▸ Refresh devices (PortAudio re-init + a live BlinkStick scan).
    refresh_requested = QtCore.pyqtSignal()

    def __init__(self, session: SmaccSession, parent: QtWidgets.QWidget | None = None):
        super().__init__(session, parent)
        self._role_combos: dict[str, QtWidgets.QComboBox] = {}
        self._route_combos: dict[str, QtWidgets.QComboBox] = {}
        self.setCentralWidget(self._build())
        self.reload_from_config()

    # ----- construction ------------------------------------------------------

    def _build(self) -> QtWidgets.QWidget:
        roles_form = QtWidgets.QFormLayout()
        roles_form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        for role in devices.ROLES:
            combo = QtWidgets.QComboBox(self)
            combo.setStatusTip(f"Device bound to the {role.label} role.")
            combo.currentIndexChanged.connect(partial(self._set_binding, role.key))
            self._role_combos[role.key] = combo
            roles_form.addRow(f"{role.label} is:", combo)
        self._populate_role_combos()

        routing_form = QtWidgets.QFormLayout()
        routing_form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        for target in devices.TARGETS:
            combo = QtWidgets.QComboBox(self)
            combo.setStatusTip(f"Role the '{target.label}' modality is routed to.")
            if target.optional:
                combo.addItem(_NONE_LABEL, "")
            for role in devices.ROLES:
                if role.kind == target.kind:
                    combo.addItem(role.label, role.key)
            combo.currentIndexChanged.connect(partial(self._set_routing, target.key))
            self._route_combos[target.key] = combo
            routing_form.addRow(f"{target.label} using:", combo)

        refresh_button = QtWidgets.QPushButton("Refresh devices", self)
        refresh_button.setStatusTip(
            "Rescan for audio devices and BlinkSticks (e.g. after plugging one in)."
        )
        refresh_button.setToolTip("Rescan for devices plugged in after launch (F5).")
        refresh_button.clicked.connect(self.refresh_requested)

        hint = QtWidgets.QLabel(
            "Bind each role to a device once, then route each modality to a role. "
            "Plugged a device in after launch? Refresh devices (or press F5)."
        )
        hint.setWordWrap(True)

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(make_section_title("Devices"))
        layout.addWidget(self._subheading("Roles → devices"))
        layout.addLayout(roles_form)
        layout.addSpacing(8)
        layout.addWidget(self._subheading("Modalities → roles"))
        layout.addLayout(routing_form)
        layout.addWidget(hint)
        layout.addWidget(refresh_button)
        layout.addStretch(1)
        central = QtWidgets.QWidget()
        central.setLayout(layout)
        return central

    def _subheading(self, text: str) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel(text, self)
        label.setStyleSheet("font-weight: bold;")
        return label

    # ----- enumeration -------------------------------------------------------

    def _populate_role_combos(self) -> None:
        """(Re)fill each role's device dropdown, preserving the current selection."""
        for role in devices.ROLES:
            combo = self._role_combos[role.key]
            previous = current_device_key(combo)
            combo.blockSignals(True)
            combo.clear()
            if role.kind == devices.VISUAL:
                combo.addItem(_NONE_LABEL, "")
                for label, serial in blinkstick_devices():
                    combo.addItem(label, serial)
            else:
                combo.addItem(_DEFAULT_LABEL, "")
                for device_str in wasapi_devices(role.kind):
                    combo.addItem(device_str, device_str)
            # Restore the prior selection (after a refresh) or the bound device.
            target_key = previous or self.session.devices.device_for_role(role.key)
            if not select_saved_device(combo, target_key):
                combo.setCurrentIndex(0)  # default / none
            combo.blockSignals(False)

    # ----- editing -> session.devices ----------------------------------------

    def _set_binding(self, role_key: str) -> None:
        """A role's device dropdown changed: write just that role's binding."""
        combo = self._role_combos[role_key]
        key = current_device_key(combo)
        if key and combo.currentIndex() > 0:  # index 0 is the default/none entry
            self.session.devices.bindings[role_key] = key
        else:
            self.session.devices.bindings.pop(role_key, None)
        self.session.log_interaction(
            f"{devices.ROLES_BY_KEY[role_key].label} device set"
        )
        self.changed.emit()

    def _set_routing(self, target_key: str) -> None:
        """A modality's role dropdown changed: write just that route."""
        self.session.devices.routing[target_key] = (
            self._route_combos[target_key].currentData() or ""
        )
        self.session.log_interaction(
            f"{devices.TARGETS_BY_KEY[target_key].label} routing set"
        )
        self.changed.emit()

    # ----- config <-> widgets ------------------------------------------------

    def reload_from_config(self) -> None:
        """Sync every dropdown to ``session.devices`` (after a study load).

        Flags any bound device that isn't currently connected so the operator is
        told (the same consolidated notice the other panels use).
        """
        cfg = self.session.devices
        for role_key, combo in self._role_combos.items():
            combo.blockSignals(True)
            bound = cfg.device_for_role(role_key)
            if not select_saved_device(combo, bound):
                combo.setCurrentIndex(0)
                if bound:  # a saved device that isn't plugged in
                    role = devices.ROLES_BY_KEY[role_key]
                    self.session.note_missing_device(role.label, bound)
            combo.blockSignals(False)
        for target_key, combo in self._route_combos.items():
            combo.blockSignals(True)
            index = combo.findData(cfg.role_for(target_key))
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)

    def refresh_device_lists(self) -> None:
        """Re-enumerate the role device dropdowns (the File ▸ Refresh devices hook)."""
        self._populate_role_combos()
