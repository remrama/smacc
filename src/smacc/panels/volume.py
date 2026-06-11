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
from .base import PanelWindow, make_section_title, restore_spin_value


class VolumeWindow(PanelWindow):
    """Set the master output cap + latency mode, and view the Windows volume stages."""

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

        latencyCombo = QtWidgets.QComboBox(self)
        latencyCombo.addItem("High (robust)", "high")
        latencyCombo.addItem("Low (less delay)", "low")
        # Cap the width so this combo doesn't stretch the whole window (the full
        # explanation lives in the status tip and the docs).
        latencyCombo.setMaximumWidth(150)
        latencyCombo.setStatusTip(
            "Output buffer for cue + noise: High is robust (fewer glitches); Low "
            "trims marker-to-sound delay but risks underruns. Applies to the next "
            "cue/noise played. Rarely critical for lucidity cueing — see the docs."
        )
        index = latencyCombo.findData(self.session.output_latency)
        latencyCombo.setCurrentIndex(index if index >= 0 else 0)
        latencyCombo.currentIndexChanged.connect(self.set_output_latency)
        self.latencyCombo = latencyCombo

        self.endpointLabel = QtWidgets.QLabel(self)
        self.appLabel = QtWidgets.QLabel(self)
        refreshButton = QtWidgets.QPushButton("Refresh levels", self)
        refreshButton.setStatusTip("Re-read the current Windows volume levels.")
        refreshButton.clicked.connect(self.refresh_levels)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        form.addRow("Safety cap:", capSpinBox)
        form.addRow("Latency:", self.latencyCombo)
        form.addRow("System volume:", self.endpointLabel)
        form.addRow("App volume:", self.appLabel)

        note = QtWidgets.QLabel(
            "The Windows volumes above multiply with SMACC's per-cue volume and this "
            "cap, and each is per-device. For reproducible cue levels, set the Windows "
            "volumes to 100% and calibrate with the cap and per-cue volumes here."
        )
        note.setWordWrap(True)
        # Without a width cap the wrapped note dictates a wide window; this keeps the
        # Volume tool slim (it just shows a cap spinner and a couple of readouts), so
        # the note wraps to more lines instead of stretching everything out.
        note.setMaximumWidth(300)

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
        self.session.log_interaction(
            f"Output safety cap set to {value:.2f}", debug=True
        )

    def set_output_latency(self, _index: int = 0) -> None:
        """Apply the output latency mode (used the next time a stimulus stream opens)."""
        mode = self.latencyCombo.currentData()
        self.session.output_latency = mode
        self.session.log_interaction(f"Output latency set to {mode}")

    def refresh_levels(self) -> None:
        """Re-read the Windows endpoint + app volumes (best-effort)."""
        endpoint = winvolume.endpoint_volume()
        app = winvolume.app_volume()
        self.endpointLabel.setText(self._format_level(endpoint))
        self.appLabel.setText(self._format_level(app))
        # Record the OS-side volumes on each actual read (not on slider drags), so a
        # run's cue levels stay reproducible from the log alone (the file records
        # DEBUG; only the live preview hides it).
        self.session.log_debug_msg(
            "Windows output volume: "
            f"endpoint {self._format_level(endpoint)}, "
            f"SMACC mixer {self._format_level(app)}"
        )

    @staticmethod
    def _format_level(scalar: float | None) -> str:
        return f"{round(scalar * 100)}%" if scalar is not None else "unavailable"

    def gather_state(self) -> dict:
        return {
            "volume_cap": self.capSpinBox.value(),
            "output_latency": self.latencyCombo.currentData(),
        }

    def apply_state(self, state: dict) -> None:
        if (v := state.get("volume_cap")) is not None:
            restore_spin_value(self.capSpinBox, v)  # fires set_cap on success
        if (lat := state.get("output_latency")) in ("high", "low"):
            index = self.latencyCombo.findData(lat)
            if index >= 0:
                self.latencyCombo.setCurrentIndex(index)  # fires set_output_latency
