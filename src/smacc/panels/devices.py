"""Devices window: bind devices to the rig's equipment, then route actions to it.

This is the one place device selection lives (#39): an *Equipment* section binds
each named piece of the rig (bedroom speaker, control-room mic, …) to a device,
and an *Actions* section points each thing SMACC does at a piece of equipment.
The tool windows show only a read-only indicator of what they resolve to. The
edited config lives on ``session.devices``; :attr:`changed` fires whenever it is
edited so the window can refresh the indicators everywhere.
"""

from __future__ import annotations

from functools import partial

import sounddevice as sd
from blinkstick import blinkstick
from PyQt6 import QtCore, QtWidgets

from .. import devices, hue
from ..dialogs import HueBridgeDialog
from ..session import SmaccSession
from .base import (
    PanelWindow,
    make_section_title,
    select_saved_device,
)

_NONE_LABEL = "(none)"
# Sole-row placeholders when enumeration finds nothing (#139): say so, instead of
# an ambiguous "(none)" (or the old "(system default)", which implied an output
# exists when none does). The Hue entry distinguishes "no bridge paired yet" (the
# Set up… button is the path forward) from a paired bridge with nothing to list.
_EMPTY_LABELS = {
    devices.OUTPUT: "No output device found",
    devices.INPUT: "No input device found",
    devices.VISUAL: "No BlinkStick found",
}
_NO_BRIDGE_LABEL = "No bridge paired"
_NO_LIGHTS_LABEL = "No lights found"
# Item-data marker (a Qt item-data role, unrelated to the old "role" naming) for
# a "(not connected)" row — a bound device with no live row — so a reload can
# tell it apart from a real match and flag the miss.
_MISSING_ROLE = QtCore.Qt.ItemDataRole.UserRole + 1


def wasapi_devices(kind: str) -> list[str]:
    """Return the WASAPI ``"output"`` or ``"input"`` device names (best effort).

    Only WASAPI devices are listed, so the bare device name is returned (no
    ", Windows WASAPI" suffix — it added nothing and is what gets persisted as
    an equipment binding). A bare name is ambiguous to sounddevice when the same hardware
    appears under several host APIs, so stream-opening code resolves it back to
    the WASAPI device via :func:`smacc.panels.base.resolve_device`.
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


def default_wasapi_device(kind: str) -> str:
    """The name of the device that is currently the WASAPI default ("" when none).

    PortAudio reports each host API's default device as of its last
    initialization, so this is fresh exactly when SMACC reads it (right after
    launch or a rescan). Used only to *auto-bind* an unbound equipment to a concrete
    device name (#139) — never consulted at stream-open time, so a later change
    of the Windows default cannot re-route a study.
    """
    key = "default_output_device" if kind == devices.OUTPUT else "default_input_device"
    try:
        for api in sd.query_hostapis():
            if api["name"] == devices.WASAPI_HOST_API:
                index = api[key]
                return sd.query_devices(index)["name"] if index >= 0 else ""
    except Exception:
        pass
    return ""


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


def hue_devices(cfg: hue.HueConfig) -> list[tuple[str, str]]:
    """Return ``(label, key)`` for each Hue light/group (best effort).

    Empty when the bridge isn't set up or can't be reached — the combo then says
    so ("No bridge paired" / "No lights found"), and the Set up button is the
    path forward.
    """
    try:
        return hue.targets(cfg)
    except hue.HueError:
        return []


class DevicesWindow(PanelWindow):
    """Bind devices to equipment and route actions to equipment (edits session.devices)."""

    TITLE = "Devices"

    # Fired whenever a binding/route changes, so the window can refresh indicators.
    changed = QtCore.pyqtSignal()
    # Fired only by an operator's equipment-binding edit — not routing, not autobind,
    # not the programmatic reload — so the session can persist that binding to the
    # machine's rig profile without the autobound defaults clobbering it (#300).
    binding_edited = QtCore.pyqtSignal()
    # Fired by the Refresh button (and its F5 shortcut); the session window runs the
    # rescan (PortAudio re-init + a live BlinkStick scan).
    refresh_requested = QtCore.pyqtSignal()

    def __init__(self, session: SmaccSession, parent: QtWidgets.QWidget | None = None):
        super().__init__(session, parent)
        self._equipment_combos: dict[str, QtWidgets.QComboBox] = {}
        self._action_combos: dict[str, QtWidgets.QComboBox] = {}
        self._action_indicators: dict[str, QtWidgets.QLabel] = {}
        self.setCentralWidget(self._build())
        self.reload_from_config()

    # ----- construction ------------------------------------------------------

    def _build(self) -> QtWidgets.QWidget:
        equipment_form = QtWidgets.QFormLayout()
        equipment_form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        for equipment in devices.EQUIPMENT:
            combo = QtWidgets.QComboBox(self)
            combo.setStatusTip(f"The device serving as {equipment.label}.")
            combo.setToolTip(equipment.description)
            combo.currentIndexChanged.connect(partial(self._set_binding, equipment.key))
            self._equipment_combos[equipment.key] = combo
            equipment_form.addRow(f"{equipment.label} is:", combo)
            self._set_row_label_tooltip(equipment_form, combo, equipment.description)
        self._populate_equipment_combos()

        routing_form = QtWidgets.QFormLayout()
        routing_form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        for action in devices.ACTIONS:
            combo = QtWidgets.QComboBox(self)
            combo.setStatusTip(f"The equipment '{action.label}' uses.")
            combo.setToolTip(action.description)
            if action.optional:
                combo.addItem(_NONE_LABEL, "")
            for equipment in devices.EQUIPMENT:
                if equipment.kind == action.kind:
                    combo.addItem(equipment.label, equipment.key)
            combo.currentIndexChanged.connect(partial(self._set_routing, action.key))
            self._action_combos[action.key] = combo
            # Beside each route, show the device it currently resolves to — the
            # live composition of the two sections, so a route on an unbound
            # equipment reads "→ no device" instead of looking configured.
            indicator = QtWidgets.QLabel(self)
            self._action_indicators[action.key] = indicator
            row = QtWidgets.QHBoxLayout()
            row.addWidget(combo)
            row.addWidget(indicator, 1)
            routing_form.addRow(f"{action.label} using:", row)
            self._set_row_label_tooltip(routing_form, row, action.description)

        refresh_button = QtWidgets.QPushButton("Refresh devices (F5)", self)
        refresh_button.setStatusTip(
            "Rescan for audio devices, BlinkSticks, and Hue lights (e.g. after "
            "plugging one in)."
        )
        refresh_button.setToolTip("Rescan for devices plugged in after launch")
        # F5 lives here now (the old File ▸ Refresh devices menu entry was removed):
        # rescan when this window is focused.
        refresh_button.setShortcut("F5")
        refresh_button.clicked.connect(self.refresh_requested)

        hue_button = QtWidgets.QPushButton("Set up Philips Hue…", self)
        hue_button.setStatusTip(
            "Pair with a Hue bridge so its lights can serve as the visual cue (#53)."
        )
        hue_button.setToolTip("Find and pair with a Philips Hue bridge")
        hue_button.clicked.connect(self.setup_hue_bridge)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(refresh_button)
        buttons.addWidget(hue_button)

        hint = QtWidgets.QLabel(
            "Tell SMACC what equipment the rig has, then which equipment each "
            "action uses. Hover any row for what it does."
        )
        hint.setWordWrap(True)

        # Hint and action buttons sit above the dropdowns so they're visible
        # without scrolling/resizing (the forms below can grow long).
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(make_section_title("Devices"))
        layout.addWidget(hint)
        layout.addLayout(buttons)
        layout.addSpacing(8)
        layout.addWidget(
            self._subheading(
                "Equipment → devices (what the rig has)",
                "Each row names a physical endpoint of the rig — a speaker, mic, "
                "or light. Bind it to one of this machine's devices, once.",
            )
        )
        layout.addLayout(equipment_form)
        layout.addSpacing(8)
        layout.addWidget(
            self._subheading(
                "Actions → equipment (what SMACC does with it)",
                "Everything SMACC plays or records routes to a piece of "
                "equipment. Several actions can share one — the cue, the noise, "
                "and your voice can all use the bedroom speaker.",
            )
        )
        layout.addLayout(routing_form)
        layout.addStretch(1)
        central = QtWidgets.QWidget()
        central.setLayout(layout)
        return central

    def _subheading(self, text: str, tooltip: str = "") -> QtWidgets.QLabel:
        label = QtWidgets.QLabel(text, self)
        label.setStyleSheet("font-weight: bold;")
        if tooltip:
            label.setToolTip(tooltip)
        return label

    @staticmethod
    def _set_row_label_tooltip(
        form: QtWidgets.QFormLayout,
        field: QtWidgets.QWidget | QtWidgets.QLayout,
        tooltip: str,
    ) -> None:
        """Put ``tooltip`` on a form row's text label (hovering the words works too)."""
        label = form.labelForField(field)  # type: ignore[call-overload]
        if label is not None and tooltip:
            label.setToolTip(tooltip)

    # ----- enumeration -------------------------------------------------------

    def _populate_equipment_combos(self) -> None:
        """(Re)fill each equipment dropdown from a fresh enumeration.

        The selection is re-derived from ``session.devices`` (every user edit
        writes through to it, so the combo can never hold anything newer): the
        bound device's row, or the index-0 placeholder when nothing is bound.
        Index 0 reads "(none)" when there are devices to choose from and a
        kind-specific "No … found" when there are none (#139).
        """
        for equipment in devices.EQUIPMENT:
            combo = self._equipment_combos[equipment.key]
            combo.blockSignals(True)
            combo.clear()
            if equipment.key == "philips_hue_light":
                entries = hue_devices(self.session.hue_config)
                empty = (
                    _NO_LIGHTS_LABEL
                    if self.session.hue_config.configured
                    else _NO_BRIDGE_LABEL
                )
            elif equipment.kind == devices.VISUAL:
                entries = blinkstick_devices()
                empty = _EMPTY_LABELS[devices.VISUAL]
            else:
                entries = [(name, name) for name in wasapi_devices(equipment.kind)]
                empty = _EMPTY_LABELS[equipment.kind]
            combo.addItem(_NONE_LABEL if entries else empty, "")
            for label, key in entries:
                combo.addItem(label, key)
            bound = self.session.devices.device_for_equipment(equipment.key)
            self._select_device_row(combo, bound)
            combo.blockSignals(False)

    def _select_device_row(self, combo: QtWidgets.QComboBox, key: str) -> bool:
        """Select the row for device ``key``; index 0 (the placeholder) when blank.

        A bound device with no row (not currently connected) is added as an
        explicit "(not connected)" row carrying ``key`` as its data and selected,
        so the combo shows the truth instead of displaying the placeholder while
        the binding — which is kept (flag, don't swap) — still points at the
        missing device. Returns False in exactly that case so
        :meth:`reload_from_config` can flag it. A rescan rebuilds the list, so
        the row disappears once the device is back (or another is picked).
        """
        if not key:
            combo.setCurrentIndex(0)
            return True
        if select_saved_device(combo, key):
            return not combo.itemData(combo.currentIndex(), _MISSING_ROLE)
        combo.addItem(f"{key} (not connected)", key)
        index = combo.count() - 1
        combo.setItemData(index, True, _MISSING_ROLE)
        combo.setCurrentIndex(index)
        return False

    # ----- editing -> session.devices ----------------------------------------

    def _set_binding(self, equipment_key: str) -> None:
        """An equipment dropdown changed: write just that binding."""
        key = self._equipment_combos[equipment_key].currentData()
        if key:
            self.session.devices.bindings[equipment_key] = key
        else:  # the "(none)" / "No … found" placeholder rows carry no device key
            self.session.devices.bindings.pop(equipment_key, None)
        self.session.log_interaction(
            f"{devices.EQUIPMENT_BY_KEY[equipment_key].label} device set"
        )
        self.refresh_device_indicator()
        self.changed.emit()
        self.binding_edited.emit()  # operator edit → persist to the rig profile (#300)

    def _set_routing(self, action_key: str) -> None:
        """An action's equipment dropdown changed: write just that route."""
        self.session.devices.routing[action_key] = (
            self._action_combos[action_key].currentData() or ""
        )
        self.session.log_interaction(
            f"{devices.ACTIONS_BY_KEY[action_key].label} routing set"
        )
        self.refresh_device_indicator()
        self.changed.emit()

    # ----- config <-> widgets ------------------------------------------------

    def reload_from_config(self) -> None:
        """Sync every dropdown to ``session.devices`` (after a study load).

        Flags any bound device that isn't currently connected so the operator is
        told (the same consolidated notice the other panels use); the binding is
        kept and shown as a "(not connected)" row, never silently swapped.
        """
        cfg = self.session.devices
        for equipment_key, combo in self._equipment_combos.items():
            combo.blockSignals(True)
            bound = cfg.device_for_equipment(equipment_key)
            if not self._select_device_row(combo, bound):
                equipment = devices.EQUIPMENT_BY_KEY[equipment_key]
                self.session.note_missing_device(equipment.label, bound)
            combo.blockSignals(False)
        for action_key, combo in self._action_combos.items():
            combo.blockSignals(True)
            index = combo.findData(cfg.equipment_for(action_key))
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)
        self.refresh_device_indicator()

    def refresh_device_lists(self) -> None:
        """Re-enumerate the equipment device dropdowns (the Refresh devices hook)."""
        self._populate_equipment_combos()

    def refresh_device_indicator(self) -> None:
        """Render each route's resolved device beside its dropdown.

        The routing combo names equipment; this shows what the route *actually*
        uses right now, so a route pointed at an unbound equipment reads "→ no
        device" instead of looking configured. Refreshed through the same hook
        the other panels use (the session window calls it on every
        binding/routing change, study load, and rescan) and directly from this
        window's own setters, so a standalone window stays honest too.
        """
        cfg = self.session.devices
        for action_key, indicator in self._action_indicators.items():
            equipment_key = cfg.equipment_for(action_key)
            if not equipment_key:
                indicator.setText("")  # the route is off
                indicator.setStyleSheet("")
                continue
            device = cfg.device_for(action_key)
            if device:
                indicator.setText(f"→ {device}")
                indicator.setStyleSheet("color: gray;")
            else:
                indicator.setText("→ no device")
                indicator.setStyleSheet("color: red;")

    def autobind_defaults(self) -> None:
        """Bind unbound required equipment to the current Windows default, by name (#139).

        Live sessions only: the editor usually runs on a different machine than
        the rig, so baking *its* devices into a study would be wrong — the rig
        pins its own defaults the first time the study loads there. Called at
        session construction and after a study load, deliberately not on rescans,
        so an explicit "(none)" never snaps back on a hot-plug. Once bound, the
        device is pinned: a later change of the Windows default re-routes
        nothing. Each fill is logged ungated — which physical device a night
        actually used is provenance, not chatter.
        """
        if self.session.design:
            return
        defaults = {
            kind: default_wasapi_device(kind)
            for kind in (devices.OUTPUT, devices.INPUT)
        }
        filled = devices.autobind(self.session.devices, defaults)
        for equipment, device in filled:
            combo = self._equipment_combos[equipment.key]
            combo.blockSignals(True)
            self._select_device_row(combo, device)
            combo.blockSignals(False)
            self.session.log_info_msg(
                f"{equipment.label} auto-selected: {device} (the current Windows default)"
            )
        if filled:
            self.refresh_device_indicator()
            self.changed.emit()

    def setup_hue_bridge(self) -> None:
        """Open the Hue pairing dialog; on accept, store the config and re-list."""
        dialog = HueBridgeDialog(self.session.hue_config, parent=self)
        if not dialog.exec():
            return
        self.session.hue_config = dialog.get_config()
        self.session.log_interaction("Philips Hue bridge configured")
        self._populate_equipment_combos()  # the Hue equipment now lists the bridge's lights
        self.changed.emit()
