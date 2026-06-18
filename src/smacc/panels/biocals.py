"""Biocals window: timed biocalibration markers with optional voice instructions.

Each row is one biocal (a standard sleep-study calibration or a lucid-dreaming
signal practice) behind a toggle button: press to run it — optionally announcing
it first with a pre-recorded voice on the cue output — and press again to cancel.
A countdown shows the remaining task window. "Play sequence" runs every
sequence-checked row in order through the same per-biocal path, so the EEG
record carries identical markers either way; pressing the active biocal's button
mid-sequence skips just that item, while the sequence button aborts the rest.

Rows may repeat a biocal (eyes-closed twice, extra LRLRs) and can be reordered
or removed; the stack persists in the study's ``biocals`` settings block. All
marker/timing decisions live in the Qt-free :class:`smacc.biocals.BiocalRun` —
this window renders its state and owns the audio streams (the cue route, with
its control-room monitor fan-out and the master volume cap). See #78.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import timedelta
from functools import partial

import numpy as np
import sounddevice as sd
import soundfile as sf
from PyQt6 import QtCore, QtWidgets

from .. import audio, biocals, devices, utils
from ..fonts import mono_font
from ..paths import resolve_biocal_voice
from ..session import SmaccSession
from ..utils import format_elapsed
from .audio import CueOutput
from .base import (
    PanelWindow,
    describe_action,
    make_section_title,
    require_device,
    resolve_device,
)

# Rows are instances, not definitions, so a stack can repeat biocals freely; the
# cap just keeps the window and a played sequence manageable.
MAX_BIOCAL_ROWS = 40
# Fallback output rate when a device's own rate can't be queried.
_FALLBACK_RATE = 44100


def _device_samplerate(device: int | str | None) -> int:
    """Best output sample rate for ``device`` (WASAPI opens only at its own)."""
    try:
        return int(sd.query_devices(device, "output")["default_samplerate"])
    except Exception:
        return _FALLBACK_RATE


@dataclass
class BiocalRowWidgets:
    """One stack row: its biocal key plus the widgets controlling it.

    Signal handlers bind to the row *object*, never a row index, so adding,
    removing, or reordering rows can't misroute another row's controls (the
    cue-board pattern).
    """

    key: str
    seqCheckBox: QtWidgets.QCheckBox
    voiceCheckBox: QtWidgets.QCheckBox
    button: QtWidgets.QPushButton
    durationSpin: QtWidgets.QSpinBox
    upButton: QtWidgets.QPushButton
    downButton: QtWidgets.QPushButton
    removeButton: QtWidgets.QPushButton


class BiocalsWindow(PanelWindow):
    """A reorderable biocal stack with per-row toggle buttons and a sequence."""

    TITLE = "Biocals"

    def __init__(self, session: SmaccSession, parent: QtWidgets.QWidget | None = None):
        super().__init__(session, parent)
        # The run engine decides what happens; this window executes its actions.
        # time.monotonic so a wall-clock adjustment mid-night can't warp a window.
        self._run = biocals.BiocalRun(time.monotonic)
        # Open voice outputs (cue device + optional control-room monitor), each
        # with its own mixer — present only while an announcement is playing.
        self._outputs: list[CueOutput] = []
        # Decoded voice buffers by biocal key (a session replays the same few
        # files; failures aren't cached so a restored file works immediately).
        self._voice_cache: dict[str, tuple[np.ndarray, int]] = {}
        # GUI-thread poller: renders the countdown, detects the announcement
        # ending and the task window running out. Runs only while a biocal is on.
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._poll)
        self.rows: list[BiocalRowWidgets] = []
        self.setCentralWidget(self._build())
        self._set_rows(biocals.default_rows())

    # ----- construction ------------------------------------------------------

    def _build(self) -> QtWidgets.QWidget:
        # Voice output rides the cue route (set in the Devices window), so the
        # instruction reaches the participant's speakers — and the control-room
        # monitor fan-out — exactly like a cue would.
        self.deviceLabel = QtWidgets.QLabel(self)
        self.deviceLabel.setStatusTip("Set in the Devices window (Play audio cue).")
        self.refresh_device_indicator()

        voiceVolumeSpin = QtWidgets.QDoubleSpinBox(self)
        voiceVolumeSpin.setRange(0, 1)  # software gain at unity-or-below
        voiceVolumeSpin.setSingleStep(0.01)
        voiceVolumeSpin.setMaximumWidth(70)
        voiceVolumeSpin.setStatusTip(
            "Volume of the spoken instructions (shared by every biocal; the "
            "master output cap still applies)."
        )
        voiceVolumeSpin.valueChanged.connect(self._on_voice_volume)
        voiceVolumeSpin.setValue(0.5)
        self.voiceVolumeSpin = voiceVolumeSpin

        header = QtWidgets.QFormLayout()
        header.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        header.addRow("Device:", self.deviceLabel)
        header.addRow("Voice volume:", voiceVolumeSpin)

        # The timekeeper: counts the active task window down (and shows the
        # upcoming window during an announcement). Glanceable, but kept compact so
        # the whole stack fits without a tall window.
        countdownLabel = QtWidgets.QLabel("00:00:00", self)
        countdownLabel.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        # B612 Mono (#279) so the clock holds a steady width as the digits tick.
        countdownLabel.setFont(mono_font(20, bold=True))
        countdownLabel.setStatusTip("Time remaining in the running biocal.")
        self.countdownLabel = countdownLabel

        self.statusLabel = QtWidgets.QLabel("■ idle", self)
        self.statusLabel.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

        # Stack table: a persistent header row plus one rebuildable row per
        # biocal. Header widgets are created once and reused across rebuilds, so
        # a rebuild only reparents widgets — live controls survive untouched.
        # The Seq and Voice headers are master checkboxes: clicking one checks or
        # unchecks that column for every row at once (a quick "uncheck all"), and
        # each reflects its column's state (all / none / mixed = partially checked).
        self._grid = QtWidgets.QGridLayout()
        self._grid.setVerticalSpacing(4)  # keep the multi-row stack short
        self._seqHeader = self._make_header_checkbox(
            "Seq", "Include every biocal in the played sequence (click to toggle all)."
        )
        self._seqHeader.clicked.connect(self._on_seq_header_clicked)
        self._voiceHeader = self._make_header_checkbox(
            "Voice",
            "Announce every biocal with its voice instruction (click to toggle all).",
        )
        self._voiceHeader.clicked.connect(self._on_voice_header_clicked)
        self._header_widgets: list[QtWidgets.QWidget] = [
            self._seqHeader,
            self._voiceHeader,
            *(
                self._make_header_label(title)
                for title in ("Biocal", "Duration", "", "", "")
            ),
        ]

        addCombo = QtWidgets.QComboBox(self)
        for b in biocals.default_biocals():
            addCombo.addItem(b.label, b.key)
        addCombo.setStatusTip(
            "Biocal to add as another row (rows can repeat a biocal, e.g. to "
            "run it twice in the sequence)."
        )
        self._addCombo = addCombo
        addButton = QtWidgets.QPushButton("+ Add", self)
        addButton.setStatusTip(f"Add the chosen biocal (up to {MAX_BIOCAL_ROWS} rows).")
        addButton.setToolTip("Add another biocal row")
        addButton.clicked.connect(self._add_clicked)
        self._addButton = addButton
        addRow = QtWidgets.QHBoxLayout()
        addRow.addWidget(addCombo)
        addRow.addWidget(addButton)
        addRow.addStretch(1)

        sequenceButton = QtWidgets.QPushButton("Play sequence", self)
        sequenceButton.setCheckable(True)
        sequenceButton.setStatusTip(
            "Run every sequence-checked biocal in order (press again to abort)."
        )
        sequenceButton.clicked.connect(self._on_sequence_button)
        self.sequenceButton = sequenceButton

        # The stack lives in a scroll area: the full default stack made the window
        # taller than many screens (burying the sequence button), so the rows
        # scroll instead of growing the window. Top-aligned via a trailing stretch
        # so a short stack doesn't spread its rows over the viewport.
        stackLayout = QtWidgets.QVBoxLayout()
        stackLayout.setContentsMargins(0, 0, 0, 0)
        stackLayout.addLayout(self._grid)
        stackLayout.addStretch(1)
        stackWidget = QtWidgets.QWidget()
        stackWidget.setLayout(stackLayout)
        scroll = QtWidgets.QScrollArea(self)
        scroll.setWidget(stackWidget)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        scroll.setMinimumHeight(240)  # roughly eight rows visible by default
        self._stackScroll = scroll

        # Sequence button above the stack, so it's visible regardless of how long
        # the stack is; the add-row controls stay below it, also outside the scroll.
        layout = QtWidgets.QVBoxLayout()
        layout.setSpacing(6)  # tighter than the default so the stack stays compact
        layout.addWidget(make_section_title("Biocals"))
        layout.addLayout(header)
        layout.addWidget(countdownLabel)
        layout.addWidget(self.statusLabel)
        layout.addWidget(sequenceButton)
        layout.addSpacing(4)
        layout.addWidget(scroll, 1)  # the scroll area absorbs extra height
        layout.addLayout(addRow)
        central = QtWidgets.QWidget()
        central.setLayout(layout)
        return central

    def _make_header_label(self, text: str) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel(text, self)
        label.setStyleSheet("font-weight: bold;")
        return label

    def _make_header_checkbox(self, text: str, status_tip: str) -> QtWidgets.QCheckBox:
        """A bold column-header checkbox that toggles its whole column at once."""
        box = QtWidgets.QCheckBox(text, self)
        box.setStyleSheet("font-weight: bold;")
        box.setStatusTip(status_tip)
        return box

    def _make_row(self, state: biocals.BiocalRow) -> BiocalRowWidgets:
        """Build one fully-wired stack row and append it to ``self.rows``."""
        b = biocals.BIOCALS_BY_KEY[state.key]
        seqCheckBox = QtWidgets.QCheckBox(self)
        seqCheckBox.setChecked(state.sequence)
        seqCheckBox.setToolTip("Include in Play sequence")
        seqCheckBox.setStatusTip("Include this biocal when the sequence is played.")
        voiceCheckBox = QtWidgets.QCheckBox(self)
        voiceCheckBox.setChecked(state.voice)
        voiceCheckBox.setToolTip("Speak the instruction")
        voiceCheckBox.setStatusTip(
            "Play the pre-recorded voice instruction when this biocal starts."
        )
        button = QtWidgets.QPushButton(b.label, self)
        button.setCheckable(True)
        button.setToolTip(f"{b.full_name}. Voice: “{b.phrase}”")
        button.setStatusTip(
            f"Run the {b.full_name} biocal; press again to cancel "
            "(mid-sequence: skip to the next)."
        )
        durationSpin = QtWidgets.QSpinBox(self)
        durationSpin.setRange(biocals.MIN_DURATION_S, biocals.MAX_DURATION_S)
        durationSpin.setSuffix(" s")
        durationSpin.setValue(state.duration_s)
        durationSpin.setStatusTip(
            "Task-window length; the countdown (and completion marker) runs "
            "this long after the instruction ends."
        )
        upButton = QtWidgets.QPushButton("▲", self)
        upButton.setMaximumWidth(28)
        upButton.setToolTip("Move this biocal up")
        downButton = QtWidgets.QPushButton("▼", self)
        downButton.setMaximumWidth(28)
        downButton.setToolTip("Move this biocal down")
        removeButton = QtWidgets.QPushButton("✕", self)
        removeButton.setMaximumWidth(28)
        removeButton.setToolTip("Remove this biocal row")
        row = BiocalRowWidgets(
            state.key,
            seqCheckBox,
            voiceCheckBox,
            button,
            durationSpin,
            upButton,
            downButton,
            removeButton,
        )
        self.rows.append(row)  # append before wiring so handlers can resolve it
        seqCheckBox.toggled.connect(partial(self._on_seq_toggled, row))
        voiceCheckBox.toggled.connect(partial(self._on_voice_toggled, row))
        durationSpin.valueChanged.connect(partial(self._on_duration_changed, row))
        button.clicked.connect(partial(self._on_row_button, row))
        upButton.clicked.connect(partial(self._move_row, row, -1))
        downButton.clicked.connect(partial(self._move_row, row, 1))
        removeButton.clicked.connect(partial(self._remove_row, row))
        return row

    def _rebuild_grid(self) -> None:
        """Re-lay the stack table: header row, then one row per biocal.

        Every widget here is persistent (the header labels and each row's
        controls), so clearing only reparents them out of the grid — nothing is
        deleted — and they're re-added in their new positions.
        """
        while self._grid.count():
            self._grid.takeAt(0)  # drop the layout item only; widgets are reused
        for col, widget in enumerate(self._header_widgets):
            self._grid.addWidget(widget, 0, col)
        for r, row in enumerate(self.rows, start=1):
            self._grid.addWidget(row.seqCheckBox, r, 0)
            self._grid.addWidget(row.voiceCheckBox, r, 1)
            self._grid.addWidget(row.button, r, 2)
            self._grid.addWidget(row.durationSpin, r, 3)
            self._grid.addWidget(row.upButton, r, 4)
            self._grid.addWidget(row.downButton, r, 5)
            self._grid.addWidget(row.removeButton, r, 6)
        self._grid.setColumnStretch(2, 1)
        # Horizontal scrolling is disabled, so the scroll area must be at least as
        # wide as the widest row (plus the vertical scrollbar's track).
        content = self._stackScroll.widget()
        if content is not None:
            style = self.style()
            assert style is not None
            extent = style.pixelMetric(QtWidgets.QStyle.PixelMetric.PM_ScrollBarExtent)
            self._stackScroll.setMinimumWidth(content.sizeHint().width() + extent)
        self._refresh_structure_buttons()
        self._update_sequence_enabled()
        self._refresh_column_headers()

    def _set_rows(self, states: list[biocals.BiocalRow]) -> None:
        """Replace the whole stack (initial build and settings loads)."""
        for row in list(self.rows):
            self._destroy_row_widgets(row)
        self.rows = []
        for state in states:
            self._make_row(state)
        self._rebuild_grid()

    def _destroy_row_widgets(self, row: BiocalRowWidgets) -> None:
        for widget in (
            row.seqCheckBox,
            row.voiceCheckBox,
            row.button,
            row.durationSpin,
            row.upButton,
            row.downButton,
            row.removeButton,
        ):
            widget.hide()  # leave no orphan visible before deferred deletion
            widget.deleteLater()

    # ----- stack editing (locked while a biocal runs) -------------------------

    def _refresh_structure_buttons(self) -> None:
        """Enable/disable add/reorder/remove: the stack is frozen mid-run.

        A run snapshots its plan at start, so structural edits during one would
        only desynchronize the widgets from what's actually running.
        """
        locked = self._run.active
        self._addButton.setEnabled(not locked and len(self.rows) < MAX_BIOCAL_ROWS)
        self._addCombo.setEnabled(not locked)
        last = len(self.rows) - 1
        for i, row in enumerate(self.rows):
            row.upButton.setEnabled(not locked and i > 0)
            row.downButton.setEnabled(not locked and i < last)
            row.removeButton.setEnabled(not locked)

    def _add_clicked(self, _checked: bool = False) -> None:
        """Append a row of the combo's biocal (its defaults), up to the cap."""
        key = self._addCombo.currentData()
        if not key or len(self.rows) >= MAX_BIOCAL_ROWS:
            return
        b = biocals.BIOCALS_BY_KEY[str(key)]
        self._make_row(
            biocals.BiocalRow(
                b.key, sequence=b.standard, voice=True, duration_s=b.duration_s
            )
        )
        self._rebuild_grid()
        self.session.log_interaction(f"Added biocal '{b.label}'")

    def _remove_row(self, row: BiocalRowWidgets, _checked: bool = False) -> None:
        if row not in self.rows:
            return
        name = row.button.text()
        self.rows.remove(row)
        self._destroy_row_widgets(row)
        self._rebuild_grid()
        self.session.log_interaction(f"Removed biocal '{name}'")

    def _move_row(
        self, row: BiocalRowWidgets, delta: int, _checked: bool = False
    ) -> None:
        i = self.rows.index(row)
        j = i + delta
        if not (0 <= j < len(self.rows)):
            return
        self.rows[i], self.rows[j] = self.rows[j], self.rows[i]
        self._rebuild_grid()
        self.session.log_interaction(
            f"Moved biocal '{row.button.text()}' {'up' if delta < 0 else 'down'}"
        )

    def _on_seq_toggled(self, row: BiocalRowWidgets, checked: bool) -> None:
        self.session.log_interaction(
            f"Biocal '{row.button.text()}' sequence {'on' if checked else 'off'}"
        )
        self._update_sequence_enabled()
        self._refresh_column_headers()

    def _on_voice_toggled(self, row: BiocalRowWidgets, checked: bool) -> None:
        self.session.log_interaction(
            f"Biocal '{row.button.text()}' voice {'on' if checked else 'off'}"
        )
        self._refresh_column_headers()

    def _on_seq_header_clicked(self, checked: bool) -> None:
        """Master Seq checkbox: set every row's sequence flag at once."""
        self._set_column("seqCheckBox", checked)
        self.session.log_interaction(
            f"All biocals sequence {'on' if checked else 'off'}"
        )
        self._refresh_column_headers()
        self._update_sequence_enabled()

    def _on_voice_header_clicked(self, checked: bool) -> None:
        """Master Voice checkbox: set every row's voice flag at once."""
        self._set_column("voiceCheckBox", checked)
        self.session.log_interaction(f"All biocals voice {'on' if checked else 'off'}")
        self._refresh_column_headers()

    def _set_column(self, attr: str, checked: bool) -> None:
        """Set a checkbox column across every row without firing per-row handlers.

        Signals are blocked so a bulk toggle logs one summary line (from the header
        handler) instead of one per row; ``gather_state`` reads the boxes directly,
        so the saved state stays correct regardless.
        """
        for row in self.rows:
            box: QtWidgets.QCheckBox = getattr(row, attr)
            box.blockSignals(True)
            box.setChecked(checked)
            box.blockSignals(False)

    def _refresh_column_headers(self) -> None:
        """Reflect each column's state in its master header: all / none / mixed."""
        for header, attr in (
            (self._seqHeader, "seqCheckBox"),
            (self._voiceHeader, "voiceCheckBox"),
        ):
            states = [getattr(row, attr).isChecked() for row in self.rows]
            if states and all(states):
                check_state = QtCore.Qt.CheckState.Checked
            elif any(states):
                check_state = QtCore.Qt.CheckState.PartiallyChecked
            else:
                check_state = QtCore.Qt.CheckState.Unchecked
            header.blockSignals(True)
            header.setCheckState(check_state)
            header.blockSignals(False)

    def _on_duration_changed(self, row: BiocalRowWidgets, value: int) -> None:
        self.session.log_interaction(
            f"Biocal '{row.button.text()}' duration set to {value}s", debug=True
        )

    def _update_sequence_enabled(self) -> None:
        """Play sequence needs a checked row (or an active sequence to abort)."""
        self.sequenceButton.setEnabled(
            self._run.in_sequence
            or any(row.seqCheckBox.isChecked() for row in self.rows)
        )

    # ----- running -------------------------------------------------------------

    def _make_item(self, row: BiocalRowWidgets) -> biocals.RunItem:
        """Snapshot a row into a run item (mid-run edits affect the next run)."""
        b = biocals.BIOCALS_BY_KEY[row.key]
        return biocals.RunItem(
            token=row,
            key=row.key,
            event=b.event,
            label=b.label,
            voice=row.voiceCheckBox.isChecked(),
            duration_s=float(row.durationSpin.value()),
        )

    def _on_row_button(self, row: BiocalRowWidgets, _checked: bool = False) -> None:
        """A row button press: start, cancel, or (mid-sequence) skip its biocal."""
        active = self._run.item
        if active is not None and active.token is row:
            actions = self._run.cancel_item()
        elif self._run.in_sequence:
            actions = []  # other rows are inert while a sequence runs
        else:
            # Starting a different biocal replaces whatever was running (the
            # engine cancels it first, with its marker).
            actions = self._run.start_single(self._make_item(row))
        self._apply_actions(actions)

    def _on_sequence_button(self, _checked: bool = False) -> None:
        """Play every sequence-checked row in order, or abort the running one."""
        if self._run.in_sequence:
            actions = self._run.cancel_all()
        else:
            items = [
                self._make_item(row) for row in self.rows if row.seqCheckBox.isChecked()
            ]
            actions = self._run.start_sequence(items) if items else []
        self._apply_actions(actions)

    def _apply_actions(self, actions: list[biocals.Action]) -> None:
        """Execute the engine's actions (markers, voice), then re-render.

        A voice that can't play reports straight back as finished, so the task
        window opens immediately — a lost WAV must never block a calibration.
        """
        queue = list(actions)
        while queue:
            action = queue.pop(0)
            if isinstance(action, biocals.EmitMarker):
                self.session.emit_event(action.event, detail=action.detail)
            elif isinstance(action, biocals.PlayVoice):
                # The press itself is recorded here; the start marker fires when
                # the announcement ends and the task window opens.
                self.session.log_info_msg(f"Biocal announced: {action.label}")
                if not self._start_voice(action.key):
                    queue.extend(self._run.voice_finished())
            elif isinstance(action, biocals.StopVoice):
                self._stop_voice()
        self._render()

    def _poll(self) -> None:
        """GUI-thread timer: detect the voice ending / window running out."""
        if self._outputs and self._outputs[0].mixer.ended:
            self._stop_voice()
            self._apply_actions(self._run.voice_finished())
            return
        actions = self._run.tick()
        if actions:
            self._apply_actions(actions)
        else:
            self._render_countdown()

    def _render(self) -> None:
        """Sync every control to the engine: depressed buttons, status, timer."""
        active = self._run.item
        token = active.token if active is not None else None
        for row in self.rows:
            row.button.setChecked(row is token)
        in_seq = self._run.in_sequence
        self.sequenceButton.setChecked(in_seq)
        self.sequenceButton.setText("Stop sequence" if in_seq else "Play sequence")
        self._refresh_structure_buttons()
        self._update_sequence_enabled()
        if active is None:
            self.statusLabel.setText("■ idle")
            self.statusLabel.setStyleSheet("")
            self._timer.stop()
        else:
            progress = self._run.sequence_progress()
            suffix = f"  ({progress[0]}/{progress[1]})" if progress else ""
            if self._run.phase == biocals.VOICE:
                text = f"\U0001f50a {active.label} (announcing){suffix}"
            else:
                text = f"▶ {active.label}{suffix}"
            self.statusLabel.setText(text)
            self.statusLabel.setStyleSheet("color: red; font-weight: bold;")
            if not self._timer.isActive():
                self._timer.start()
        self._render_countdown()

    def _render_countdown(self) -> None:
        remaining = self._run.remaining()
        if remaining is not None:
            seconds = math.ceil(remaining)
        elif self._run.item is not None:
            # Announcing: show the task window about to open.
            seconds = int(self._run.item.duration_s)
        else:
            seconds = 0
        self.countdownLabel.setText(format_elapsed(timedelta(seconds=seconds)))

    # ----- voice playback ------------------------------------------------------

    def _load_voice(self, key: str) -> tuple[np.ndarray, int] | None:
        """Decoded mono buffer + rate for a biocal's voice (None if unavailable).

        Failures aren't cached, so dropping the file in mid-session just works.
        """
        if key in self._voice_cache:
            return self._voice_cache[key]
        path = resolve_biocal_voice(biocals.BIOCALS_BY_KEY[key].filename)
        try:
            data, rate = sf.read(path, dtype="float32")
        except Exception as exc:
            self.session.logger.warning(
                f"Biocal voice unavailable ({path.name}): {exc}"
            )
            return None
        if data.ndim > 1:  # down-mix to mono
            data = data.mean(axis=1)
        entry = (np.ascontiguousarray(data, dtype=np.float32), int(rate))
        self._voice_cache[key] = entry
        return entry

    def _start_voice(self, key: str) -> bool:
        """Open the voice output(s) for ``key``; False when nothing could play."""
        loaded = self._load_voice(key)
        if loaded is None:
            return False
        data, rate = loaded
        self._stop_voice()  # safety: never two announcements at once
        device = require_device(
            self.session,
            "play_audio_cue",
            devices.OUTPUT,
            failure="Could not start the biocal voice output",
            parent=self,
        )
        if device is None:
            return False
        primary = self._open_output(data, rate, device)
        if primary is None:
            return False
        self._outputs = [primary]
        monitor_device = resolve_device(
            self.session.devices.device_for("listen_audio_cue"), devices.OUTPUT
        )
        if monitor_device is not None and monitor_device != device:
            monitor = self._open_output(data, rate, monitor_device, optional=True)
            if monitor is not None:
                self._outputs.append(monitor)
        return True

    def _open_output(
        self,
        data: np.ndarray,
        file_rate: int,
        device: int | str | None,
        *,
        optional: bool = False,
    ) -> CueOutput | None:
        """Open one voice output (mixer + stream) on ``device``; None on failure.

        A failed *optional* (monitor) output is swallowed so the participant
        still hears the instruction; a failed primary output surfaces an error.
        """
        rate = _device_samplerate(device)
        mixer = audio.CueMixer()
        mixer.start(
            utils.resample_to(data, file_rate, rate),
            volume=self.voiceVolumeSpin.value(),
        )
        try:
            stream = sd.OutputStream(
                channels=1,
                samplerate=rate,
                device=device,
                callback=partial(self._render_output, mixer),
            )
            stream.start()
        except Exception as err:
            if not optional:
                self.session.show_error_popup(
                    "Could not start the biocal voice output", str(err), parent=self
                )
            return None
        return CueOutput(mixer, stream)

    def _render_output(self, mixer, outdata, frames, time, status) -> None:
        """sounddevice callback (audio thread): render one voice block."""
        if status:
            self.session.logger.warning(f"Audio output status: {status}")
        # The master safety cap is the single final gain stage (read live).
        outdata[:, 0] = mixer.render(frames) * self.session.volume_cap

    def _stop_voice(self) -> None:
        for out in self._outputs:
            out.stream.abort()
            out.stream.close()
        self._outputs = []

    def _on_voice_volume(self, value: float) -> None:
        """Set the shared voice volume (live if an announcement is playing)."""
        for out in self._outputs:
            out.mixer.volume = value
        self.session.log_interaction(
            f"Biocal voice volume set to {value:.2f}", debug=True
        )

    # ----- panel plumbing ------------------------------------------------------

    def refresh_device_indicator(self) -> None:
        """Show where the voice resolves (the cue route + its monitor fan-out)."""
        text = describe_action(self.session, "play_audio_cue")
        if self.session.devices.equipment_for("listen_audio_cue"):
            text += (
                f"   •   monitor: {describe_action(self.session, 'listen_audio_cue')}"
            )
        self.deviceLabel.setText(text)

    def is_streaming(self) -> bool:
        """True while a voice announcement holds an open output stream."""
        return bool(self._outputs)

    def gather_state(self) -> dict:
        return {
            "biocals": {
                "voice_volume": self.voiceVolumeSpin.value(),
                "rows": biocals.rows_to_list(
                    biocals.BiocalRow(
                        row.key,
                        sequence=row.seqCheckBox.isChecked(),
                        voice=row.voiceCheckBox.isChecked(),
                        duration_s=int(row.durationSpin.value()),
                    )
                    for row in self.rows
                ),
            }
        }

    def apply_state(self, state: dict) -> None:
        block = state.get("biocals")
        if not isinstance(block, dict):
            return  # pre-v7 study: keep the default stack
        if self._run.active:
            # A loaded study replaces the stack; close the run out honestly.
            self._apply_actions(self._run.cancel_all())
        rows = biocals.rows_from_list(block.get("rows"))
        if rows is not None:
            self._set_rows(rows)
        if (v := block.get("voice_volume")) is not None:
            try:
                self.voiceVolumeSpin.setValue(float(v))
            except (TypeError, ValueError):
                pass

    def cleanup(self) -> None:
        self._timer.stop()
        if self._run.active:
            # Quitting mid-biocal: record the cancellation honestly.
            self._apply_actions(self._run.cancel_all())
        self._stop_voice()
