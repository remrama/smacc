"""Volume window: a master output safety cap and a read-only view of OS volumes.

The cap (``session.volume_cap``) is the single software-gain ceiling multiplied
into every stimulus (cue + noise) in the audio callback, so a cue at full volume
can't blast a sleeping participant. The read-out surfaces the Windows endpoint and
per-app mixer volumes (via :mod:`smacc.winvolume`) that otherwise silently multiply
with it — turning "volume comes from everywhere" into something you can see.
"""

from __future__ import annotations

from PyQt6 import QtCore, QtWidgets

from .. import winvolume
from ..session import SmaccSession
from .base import ModalityWindow, make_section_title


class VolumeWindow(ModalityWindow):
    """Set the master output cap and view the (read-only) Windows volume stages."""

    TITLE = "Volume"

    def __init__(self, session: SmaccSession, parent: QtWidgets.QWidget | None = None):
        super().__init__(session, parent)
        self.setCentralWidget(self._build())
        self.refresh_levels()

    def _build(self) -> QtWidgets.QWidget:
        capSpinBox = QtWidgets.QDoubleSpinBox(self)
        capSpinBox.setRange(0, 1)
        capSpinBox.setSingleStep(0.01)
        capSpinBox.setDecimals(2)
        capSpinBox.setValue(self.session.volume_cap)
        capSpinBox.setStatusTip(
            "Master ceiling on cue + noise output (1.00 = no cap): a safety limit so "
            "a full-volume cue can't blast the participant."
        )
        capSpinBox.valueChanged.connect(self.set_cap)
        self.capSpinBox = capSpinBox

        self.endpointLabel = QtWidgets.QLabel(self)
        self.appLabel = QtWidgets.QLabel(self)
        refreshButton = QtWidgets.QPushButton("Refresh levels", self)
        refreshButton.setStatusTip("Re-read the current Windows volume levels.")
        refreshButton.clicked.connect(self.refresh_levels)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        form.addRow("Output safety cap:", capSpinBox)
        form.addRow("System output volume:", self.endpointLabel)
        form.addRow("SMACC app volume:", self.appLabel)

        note = QtWidgets.QLabel(
            "The Windows volumes above multiply with SMACC's per-cue volume and this "
            "cap, and each is per-device. For reproducible cue levels, set the Windows "
            "volumes to 100% and calibrate with the cap and per-cue volumes here."
        )
        note.setWordWrap(True)

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(make_section_title("Volume"))
        layout.addLayout(form)
        layout.addWidget(refreshButton)
        layout.addWidget(note)
        layout.addStretch(1)
        central = QtWidgets.QWidget()
        central.setLayout(layout)
        return central

    def set_cap(self, value: float) -> None:
        """Apply the master output cap (read live by the cue/noise audio callbacks)."""
        self.session.volume_cap = float(value)
        self.session.log_interaction(f"Output safety cap set to {value:.2f}")

    def refresh_levels(self) -> None:
        """Re-read the Windows endpoint + app volumes (best-effort)."""
        self.endpointLabel.setText(self._format_level(winvolume.endpoint_volume()))
        self.appLabel.setText(self._format_level(winvolume.app_volume()))

    @staticmethod
    def _format_level(scalar: float | None) -> str:
        return f"{round(scalar * 100)}%" if scalar is not None else "unavailable"

    def gather_state(self) -> dict:
        return {"volume_cap": self.capSpinBox.value()}

    def apply_state(self, state: dict) -> None:
        if (v := state.get("volume_cap")) is not None:
            self.capSpinBox.setValue(float(v))  # fires set_cap -> session.volume_cap
