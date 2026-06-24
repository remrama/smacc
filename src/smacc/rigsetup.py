"""Rig setup: bind this machine's equipment to devices, stored in the rig profile.

A launcher tool (#300) for the *physical* half of a device setup, the part that stays
on this machine: which actual device each piece of equipment (the bedroom speaker, the
mics, the lights) resolves to, plus the Hue bridge credential. It writes the ``rig``
block of ``preferences.yaml`` — the same store a session populates as you bind during a
night — so a fresh rig can be set up once, with no study open, and every study on this
machine then reuses it.

Action→equipment *routing* is a study concern (it travels in the ``.smacc``), so it is
deliberately not here — only the equipment→device bindings are.
"""

from __future__ import annotations

from functools import partial

import sounddevice as sd
from PyQt6 import QtCore, QtGui, QtWidgets

from . import devices, hue, preferences
from .dialogs import HueBridgeDialog
from .panels.base import make_section_title
from .panels.devices import populate_equipment_combo
from .paths import LOGO_PATH, preferences_path
from .toolwindow import ToolWindow


class RigSetupWindow(ToolWindow):
    """Bind this machine's equipment to devices, persisted to the rig profile."""

    def __init__(self) -> None:
        super().__init__()
        prefs = preferences.load_preferences(preferences_path)
        self._bindings: dict[str, str] = dict(preferences.rig_bindings(prefs))
        self._hue = hue.from_dict(preferences.rig_hue(prefs))
        self._combos: dict[str, QtWidgets.QComboBox] = {}
        self.setWindowTitle("SMACC — Rig setup")
        if LOGO_PATH.is_file():
            self.setWindowIcon(QtGui.QIcon(str(LOGO_PATH)))
        self._build_menu()
        self.setCentralWidget(self._build())
        self._repopulate()
        self.statusBar()
        self.show()

    def _build_menu(self) -> None:
        menu = self.menuBar()
        assert menu is not None
        file_menu = menu.addMenu("&File")
        assert file_menu is not None
        close_action = QtGui.QAction("&Close", self)
        close_action.setShortcut("Ctrl+W")
        close_action.setStatusTip("Close Rig setup and return to the Launcher.")
        close_action.triggered.connect(self.close)
        file_menu.addAction(close_action)

    def _build(self) -> QtWidgets.QWidget:
        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        for equipment in devices.EQUIPMENT:
            combo = QtWidgets.QComboBox(self)
            combo.setToolTip(equipment.description)
            combo.setStatusTip(f"The device serving as {equipment.label}.")
            combo.currentIndexChanged.connect(partial(self._set_binding, equipment.key))
            self._combos[equipment.key] = combo
            form.addRow(f"{equipment.label} is:", combo)

        refresh_button = QtWidgets.QPushButton("Refresh devices (F5)", self)
        refresh_button.setShortcut("F5")
        refresh_button.setStatusTip(
            "Rescan for audio devices, BlinkSticks, and Hue lights."
        )
        refresh_button.clicked.connect(self._refresh)
        hue_button = QtWidgets.QPushButton("Set up Philips Hue…", self)
        hue_button.setStatusTip(
            "Pair with a Hue bridge so its lights can serve as the visual cue."
        )
        hue_button.clicked.connect(self._setup_hue)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(refresh_button)
        buttons.addWidget(hue_button)

        hint = QtWidgets.QLabel(
            "Bind each piece of the rig to one of this machine's devices. This is the "
            "machine's setup — reused by every study and saved as you go. Which "
            "equipment each action uses (routing) lives in the Editor."
        )
        hint.setWordWrap(True)

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(make_section_title("Rig setup"))
        layout.addWidget(hint)
        layout.addLayout(buttons)
        layout.addSpacing(8)
        layout.addLayout(form)
        layout.addStretch(1)
        central = QtWidgets.QWidget()
        central.setContentsMargins(8, 8, 8, 8)
        central.setLayout(layout)
        return central

    def _repopulate(self) -> None:
        """Refresh every dropdown from a live enumeration, selecting the saved binding."""
        for equipment in devices.EQUIPMENT:
            populate_equipment_combo(
                self._combos[equipment.key],
                equipment,
                self._hue,
                self._bindings.get(equipment.key, ""),
            )

    def _set_binding(self, equipment_key: str) -> None:
        """An equipment dropdown changed: write that one binding to the rig profile."""
        key = self._combos[equipment_key].currentData()
        if key:
            self._bindings[equipment_key] = key
        else:  # the "(none)" / "No … found" placeholder rows carry no device key
            self._bindings.pop(equipment_key, None)
        preferences.update_rig(preferences_path, {"bindings": self._bindings})

    def _refresh(self) -> None:
        """Rescan for devices plugged in after launch, then re-list (nothing streams here)."""
        try:
            sd._terminate()
            sd._initialize()  # rebuild PortAudio's cached device list
        except Exception:
            pass
        self._repopulate()

    def _setup_hue(self) -> None:
        """Pair a Hue bridge; on accept, store the credential in the rig profile."""
        dialog = HueBridgeDialog(self._hue, parent=self)
        if not dialog.exec():
            return
        self._hue = dialog.get_config()
        preferences.update_rig(preferences_path, {"hue": self._hue.to_dict()})
        self._repopulate()

    def closeEvent(self, event: QtGui.QCloseEvent | None) -> None:
        """Close and return to the launcher (it reappears via ``closed``)."""
        if event is not None:
            event.accept()
        self.closed.emit()
