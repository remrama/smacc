"""Section forms for the hardware-free Study Editor (#301).

Each form is a :class:`SectionForm` — a ``QWidget`` view over one leaf of a
:class:`~smacc.studyconfig.StudyConfig`. :meth:`SectionForm.load` populates its
widgets from the model; :meth:`SectionForm.commit` writes the widget values back.
The editor commits every form into the model before saving or checking for unsaved
changes, so a form owns exactly the fields it surfaces and leaves the rest
untouched (a section without a form preserves its model values verbatim).

For a well-formed study, ``load`` then ``commit`` is the identity on the model, so
opening a file reads as clean. A malformed value the form can't represent (an
out-of-range number, an unknown noise color) is normalized on load and so reads as
an unsaved change — the editor offering to persist the cleanup, which is intended.

Like the editor window, this module is hardware-free by construction: it imports
only Qt and the pure model — never the session, the run-time panels, ``sounddevice``
or ``pylsl`` (the import-linter contract proves it transitively via
``smacc.studyeditor``).
"""

from __future__ import annotations

from typing import cast

from PyQt6 import QtCore, QtGui, QtWidgets

from . import biocals, devices
from .studyconfig import AudioCue, StudyConfig, VisualCue

# The spectral colors the built-in noise generator can synthesize (mirrors the
# live Noise panel's dropdown).
NOISE_COLORS = ("white", "pink", "brown")

# Visual-cue pattern keys and labels (mirror lights.STEADY/PULSE/FLASH; hardcoded
# so the editor needs no import of the light-rendering module).
_VISUAL_PATTERNS = (("steady", "Steady"), ("pulse", "Pulse"), ("flash", "Flash"))
# UI ceiling for the pulse/flash rate, mirroring the Visual panel (RATE_MAX_HZ).
_RATE_MAX_HZ = 20.0

# The combo entry for an action routed to nothing (matches the Devices panel).
_NONE_LABEL = "(none)"


def section_title(text: str) -> QtWidgets.QLabel:
    """A centered 18pt header.

    A panel-free copy of :func:`smacc.panels.base.make_section_title` (that module
    pulls in ``sounddevice``, which the editor must never reach).
    """
    label = QtWidgets.QLabel(text)
    label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
    font = QtGui.QFont()
    font.setPointSize(18)
    label.setFont(font)
    return label


class SectionForm(QtWidgets.QWidget):
    """Base for an editor section form: a view over one part of a StudyConfig."""

    def load(self, config: StudyConfig) -> None:
        """Populate this form's widgets from the model."""
        raise NotImplementedError

    def commit(self, config: StudyConfig) -> None:
        """Write this form's widget values back into the model."""
        raise NotImplementedError


class DataDirectoryForm(SectionForm):
    """The folder a study's session recordings are written to (``data_directory``)."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.edit = QtWidgets.QLineEdit(self)
        self.edit.setStatusTip(
            "Folder where sessions started from this study write their recordings."
        )
        browse = QtWidgets.QPushButton("Browse…", self)
        browse.setStatusTip("Choose the data directory.")
        browse.clicked.connect(self._browse)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.edit, 1)
        row.addWidget(browse)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        form.addRow("Data directory:", row)

        hint = QtWidgets.QLabel(
            "Stored relative to the SMACC file when the folder sits beside it, so a "
            "study folder stays portable; otherwise an absolute path is kept."
        )
        hint.setWordWrap(True)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(section_title("Data directory"))
        layout.addWidget(hint)
        layout.addLayout(form)
        layout.addStretch(1)

    def load(self, config: StudyConfig) -> None:
        self.edit.setText(config.data_directory)

    def commit(self, config: StudyConfig) -> None:
        config.data_directory = self.edit.text().strip() or "data"

    def _browse(self) -> None:
        chosen = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Choose data directory", self.edit.text().strip()
        )
        if chosen:
            self.edit.setText(chosen)


class RoutingForm(SectionForm):
    """Route each action to a piece of equipment — the portable device config.

    This is the *study* half of the device split (#300): which equipment each action
    uses (the bedroom speaker, a mic, a light). It never enumerates this machine's
    real devices — equipment→device binding is the rig's job (the Rig setup tool) —
    so the editor authoring routing stays hardware-free. Mirrors the routing column
    of the live Devices window: one combo per action, offering the equipment of the
    matching kind, plus ``(none)`` for the optional (monitoring) routes.
    """

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._combos: dict[str, QtWidgets.QComboBox] = {}
        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        for action in devices.ACTIONS:
            combo = QtWidgets.QComboBox(self)
            if action.optional:
                combo.addItem(_NONE_LABEL, "")
            for equipment in devices.EQUIPMENT:
                if equipment.kind == action.kind:
                    combo.addItem(equipment.label, equipment.key)
            combo.setStatusTip(action.description)
            self._combos[action.key] = combo
            form.addRow(f"{action.label} using:", combo)

        hint = QtWidgets.QLabel(
            "Route each action to a piece of equipment. This routing travels with the "
            "study; which real device each piece of equipment is depends on the "
            "machine and is set once in Rig setup."
        )
        hint.setWordWrap(True)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(section_title("Routing"))
        layout.addWidget(hint)
        layout.addLayout(form)
        layout.addStretch(1)

    def load(self, config: StudyConfig) -> None:
        cfg = config.devices
        for action_key, combo in self._combos.items():
            index = combo.findData(cfg.equipment_for(action_key))
            combo.setCurrentIndex(index if index >= 0 else 0)

    def commit(self, config: StudyConfig) -> None:
        for action_key, combo in self._combos.items():
            config.devices.routing[action_key] = combo.currentData() or ""


class _ColorButton(QtWidgets.QPushButton):
    """A table-cell button that shows a cue's color and opens a picker on click."""

    def __init__(self, hex_color: str, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.set_hex(hex_color)
        self.clicked.connect(self._pick)

    def set_hex(self, hex_color: str) -> None:
        self.hex = hex_color or "#ff0000"
        self.setText(self.hex)
        # A readable label whatever the swatch: contrast the text against the fill.
        color = QtGui.QColor(self.hex)
        ink = "#000000" if color.lightnessF() > 0.5 else "#ffffff"
        self.setStyleSheet(f"background-color: {self.hex}; color: {ink};")

    def _pick(self) -> None:
        chosen = QtWidgets.QColorDialog.getColor(
            QtGui.QColor(self.hex), self, "Pick cue color"
        )
        if chosen.isValid():
            self.set_hex(chosen.name())


class _CueTableForm(SectionForm):
    """Shared scaffold for the audio/visual cue tables: a table + add/remove + fades.

    Subclasses define the columns, how a row is built from / read back into a cue,
    and which cue list and fade fields on the model they own.
    """

    TITLE = ""
    COLUMNS: tuple[str, ...] = ()
    STRETCH_COLUMN = 0  # the column that expands to fill width

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.table = QtWidgets.QTableWidget(0, len(self.COLUMNS), self)
        self.table.setHorizontalHeaderLabels(list(self.COLUMNS))
        self.table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        vheader = self.table.verticalHeader()
        assert vheader is not None
        vheader.setVisible(False)
        header = self.table.horizontalHeader()
        assert header is not None
        header.setSectionResizeMode(
            self.STRETCH_COLUMN, QtWidgets.QHeaderView.ResizeMode.Stretch
        )

        add = QtWidgets.QPushButton("Add cue", self)
        add.setStatusTip("Add a new cue.")
        add.clicked.connect(self._add_default_row)
        self.remove = QtWidgets.QPushButton("Remove selected", self)
        self.remove.setStatusTip("Remove the selected cue.")
        self.remove.clicked.connect(self._remove_selected)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addWidget(add)
        buttons.addWidget(self.remove)
        self._extra_buttons(buttons)
        buttons.addStretch(1)

        self.attack = self._fade_spin("Fade-in (attack) before each cue, in seconds.")
        self.release = self._fade_spin("Fade-out (release) after each cue, in seconds.")
        fades = QtWidgets.QFormLayout()
        fades.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        fades.addRow("Attack (s):", self.attack)
        fades.addRow("Release (s):", self.release)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(section_title(self.TITLE))
        layout.addWidget(self.table, 1)
        layout.addLayout(buttons)
        layout.addLayout(fades)

    @staticmethod
    def _fade_spin(tip: str) -> QtWidgets.QDoubleSpinBox:
        spin = QtWidgets.QDoubleSpinBox()
        spin.setRange(0, 10)
        spin.setSingleStep(0.01)
        spin.setDecimals(2)
        spin.setStatusTip(tip)
        return spin

    @staticmethod
    def _spin(
        low: float, high: float, value: float, *, step: float = 0.01, suffix: str = ""
    ) -> QtWidgets.QDoubleSpinBox:
        spin = QtWidgets.QDoubleSpinBox()
        spin.setRange(low, high)
        spin.setSingleStep(step)
        spin.setDecimals(2)
        spin.setSuffix(suffix)
        spin.setValue(value)
        return spin

    def _extra_buttons(self, layout: QtWidgets.QHBoxLayout) -> None:
        """Hook for a subclass to add buttons (e.g. Browse) to the action row."""

    def _add_default_row(self) -> None:
        raise NotImplementedError

    def _remove_selected(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)


class AudioCuesForm(_CueTableForm):
    """The audio cues a study can play: name, WAV file, volume, loop — plus fades."""

    TITLE = "Audio cues"
    COLUMNS = ("Name", "File", "Volume", "Loop")
    STRETCH_COLUMN = 1

    def _extra_buttons(self, layout: QtWidgets.QHBoxLayout) -> None:
        browse = QtWidgets.QPushButton("Browse file…", self)
        browse.setStatusTip("Choose the WAV file for the selected cue.")
        browse.clicked.connect(self._browse_file)
        layout.addWidget(browse)

    def _add_default_row(self) -> None:
        self._add_row(AudioCue())

    def _add_row(self, cue: AudioCue) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QtWidgets.QTableWidgetItem(cue.name))
        self.table.setItem(row, 1, QtWidgets.QTableWidgetItem(cue.file))
        self.table.setCellWidget(row, 2, self._spin(0, 1, cue.volume))
        loop = QtWidgets.QCheckBox()
        loop.setChecked(cue.loop)
        self.table.setCellWidget(row, 3, loop)

    def _browse_file(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        item = self.table.item(row, 1)
        chosen, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Choose cue WAV", item.text() if item else "", "WAV file (*.wav)"
        )
        if chosen:
            self.table.setItem(row, 1, QtWidgets.QTableWidgetItem(chosen))

    def load(self, config: StudyConfig) -> None:
        audio = config.cueing.audio
        self.table.setRowCount(0)
        for cue in audio.cues:
            self._add_row(cue)
        self.attack.setValue(audio.attack)
        self.release.setValue(audio.release)

    def commit(self, config: StudyConfig) -> None:
        cues = []
        for row in range(self.table.rowCount()):
            name = self.table.item(row, 0)
            file = self.table.item(row, 1)
            volume = cast(QtWidgets.QDoubleSpinBox, self.table.cellWidget(row, 2))
            loop = cast(QtWidgets.QCheckBox, self.table.cellWidget(row, 3))
            cues.append(
                AudioCue(
                    name=name.text() if name else "",
                    file=file.text() if file else "",
                    volume=volume.value(),
                    loop=loop.isChecked(),
                )
            )
        config.cueing.audio.cues = cues
        config.cueing.audio.attack = self.attack.value()
        config.cueing.audio.release = self.release.value()


class VisualCuesForm(_CueTableForm):
    """The visual cues a study can play: color, brightness, pattern, rate, length."""

    TITLE = "Visual cues"
    COLUMNS = ("Name", "Color", "Brightness", "Pattern", "Rate", "Length", "Loop")
    STRETCH_COLUMN = 0

    def _add_default_row(self) -> None:
        self._add_row(VisualCue())

    def _add_row(self, cue: VisualCue) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QtWidgets.QTableWidgetItem(cue.name))
        self.table.setCellWidget(row, 1, _ColorButton(cue.color))
        self.table.setCellWidget(row, 2, self._spin(0, 1, cue.brightness))
        pattern = QtWidgets.QComboBox()
        for key, label in _VISUAL_PATTERNS:
            pattern.addItem(label, key)
        index = pattern.findData(cue.pattern)
        pattern.setCurrentIndex(index if index >= 0 else 0)
        self.table.setCellWidget(row, 3, pattern)
        self.table.setCellWidget(
            row, 4, self._spin(0.1, _RATE_MAX_HZ, cue.rate, step=0.1, suffix=" Hz")
        )
        self.table.setCellWidget(row, 5, self._spin(0, 600, cue.length, step=0.1))
        loop = QtWidgets.QCheckBox()
        loop.setChecked(cue.loop)
        self.table.setCellWidget(row, 6, loop)

    def load(self, config: StudyConfig) -> None:
        visual = config.cueing.visual
        self.table.setRowCount(0)
        for cue in visual.cues:
            self._add_row(cue)
        self.attack.setValue(visual.attack)
        self.release.setValue(visual.release)

    def commit(self, config: StudyConfig) -> None:
        cues = []
        for row in range(self.table.rowCount()):
            name = self.table.item(row, 0)
            color = cast(_ColorButton, self.table.cellWidget(row, 1))
            brightness = cast(QtWidgets.QDoubleSpinBox, self.table.cellWidget(row, 2))
            pattern = cast(QtWidgets.QComboBox, self.table.cellWidget(row, 3))
            rate = cast(QtWidgets.QDoubleSpinBox, self.table.cellWidget(row, 4))
            length = cast(QtWidgets.QDoubleSpinBox, self.table.cellWidget(row, 5))
            loop = cast(QtWidgets.QCheckBox, self.table.cellWidget(row, 6))
            cues.append(
                VisualCue(
                    name=name.text() if name else "",
                    color=color.hex,
                    brightness=brightness.value(),
                    pattern=pattern.currentData(),
                    rate=rate.value(),
                    length=length.value(),
                    loop=loop.isChecked(),
                )
            )
        config.cueing.visual.cues = cues
        config.cueing.visual.attack = self.attack.value()
        config.cueing.visual.release = self.release.value()


class BiocalsForm(SectionForm):
    """The study's biocalibration stack: voice volume plus the per-row table.

    The stack uses the model's ``None`` sentinel: a study that doesn't customize it
    keeps the app default at runtime. The "Customize the stack" toggle preserves
    that — left off, the study omits the stack (``rows`` stays ``None``) and
    round-trips untouched; turned on, the table's rows are written explicitly (an
    empty table is a deliberate empty stack).
    """

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.voiceVolume = QtWidgets.QDoubleSpinBox(self)
        self.voiceVolume.setRange(0, 1)
        self.voiceVolume.setSingleStep(0.01)
        self.voiceVolume.setDecimals(2)
        self.voiceVolume.setStatusTip("Volume of the spoken biocal instructions (0-1).")
        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        form.addRow("Voice volume:", self.voiceVolume)

        self.customize = QtWidgets.QCheckBox("Customize the biocal stack", self)
        self.customize.setStatusTip(
            "Off: use SMACC's default stack at runtime. On: author the stack here."
        )
        self.customize.toggled.connect(self._sync_enabled)

        self.table = QtWidgets.QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(
            ["Biocal", "In sequence", "Voice", "Duration (s)"]
        )
        self.table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        vheader = self.table.verticalHeader()
        assert vheader is not None
        vheader.setVisible(False)
        header = self.table.horizontalHeader()
        assert header is not None
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)

        self.picker = QtWidgets.QComboBox(self)
        for b in biocals.default_biocals():
            self.picker.addItem(b.label, b.key)
        self.picker.setStatusTip("Choose a biocal to add as a row.")
        add = QtWidgets.QPushButton("Add", self)
        add.setStatusTip("Add the chosen biocal to the stack.")
        add.clicked.connect(self._add_selected_biocal)
        remove = QtWidgets.QPushButton("Remove", self)
        remove.setStatusTip("Remove the selected row.")
        remove.clicked.connect(self._remove_selected)
        up = QtWidgets.QPushButton("Move up", self)
        up.clicked.connect(lambda: self._move(-1))
        down = QtWidgets.QPushButton("Move down", self)
        down.clicked.connect(lambda: self._move(1))
        self._row_controls = [self.table, self.picker, add, remove, up, down]
        buttons = QtWidgets.QHBoxLayout()
        for widget in (self.picker, add, remove, up, down):
            buttons.addWidget(widget)
        buttons.addStretch(1)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(section_title("Biocals"))
        layout.addLayout(form)
        layout.addWidget(self.customize)
        layout.addWidget(self.table, 1)
        layout.addLayout(buttons)

    def _add_row(self, row: biocals.BiocalRow) -> None:
        b = biocals.BIOCALS_BY_KEY.get(row.key)
        r = self.table.rowCount()
        self.table.insertRow(r)
        item = QtWidgets.QTableWidgetItem(b.label if b else row.key)
        item.setData(QtCore.Qt.ItemDataRole.UserRole, row.key)
        item.setFlags(item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(r, 0, item)
        sequence = QtWidgets.QCheckBox()
        sequence.setChecked(row.sequence)
        self.table.setCellWidget(r, 1, sequence)
        voice = QtWidgets.QCheckBox()
        voice.setChecked(row.voice)
        self.table.setCellWidget(r, 2, voice)
        duration = QtWidgets.QSpinBox()
        duration.setRange(biocals.MIN_DURATION_S, biocals.MAX_DURATION_S)
        duration.setValue(row.duration_s)
        self.table.setCellWidget(r, 3, duration)

    def _add_selected_biocal(self) -> None:
        key = self.picker.currentData()
        b = biocals.BIOCALS_BY_KEY[key]
        self._add_row(
            biocals.BiocalRow(
                key, sequence=b.standard, voice=True, duration_s=b.duration_s
            )
        )

    def _read_rows(self) -> list[biocals.BiocalRow]:
        rows = []
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            key = item.data(QtCore.Qt.ItemDataRole.UserRole) if item else ""
            sequence = cast(QtWidgets.QCheckBox, self.table.cellWidget(r, 1))
            voice = cast(QtWidgets.QCheckBox, self.table.cellWidget(r, 2))
            duration = cast(QtWidgets.QSpinBox, self.table.cellWidget(r, 3))
            rows.append(
                biocals.BiocalRow(
                    key,
                    sequence=sequence.isChecked(),
                    voice=voice.isChecked(),
                    duration_s=duration.value(),
                )
            )
        return rows

    def _set_rows(self, rows: list[biocals.BiocalRow]) -> None:
        self.table.setRowCount(0)
        for row in rows:
            self._add_row(row)

    def _remove_selected(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def _move(self, delta: int) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        rows = self._read_rows()
        target = row + delta
        if not 0 <= target < len(rows):
            return
        rows[row], rows[target] = rows[target], rows[row]
        self._set_rows(rows)
        self.table.setCurrentCell(target, 0)

    def _sync_enabled(self) -> None:
        on = self.customize.isChecked()
        for widget in self._row_controls:
            widget.setEnabled(on)

    def load(self, config: StudyConfig) -> None:
        bio = config.cueing.biocals
        self.voiceVolume.setValue(bio.voice_volume)
        if bio.rows is None:
            self.customize.setChecked(False)
            self._set_rows(biocals.default_rows())  # a starting point if customized
        else:
            self.customize.setChecked(True)
            self._set_rows(bio.rows)
        self._sync_enabled()

    def commit(self, config: StudyConfig) -> None:
        bio = config.cueing.biocals
        bio.voice_volume = self.voiceVolume.value()
        bio.rows = self._read_rows() if self.customize.isChecked() else None


class NoiseForm(SectionForm):
    """Background noise: volume, color, and a built-in generator vs a WAV file."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.volume = QtWidgets.QDoubleSpinBox(self)
        self.volume.setRange(0, 1)
        self.volume.setSingleStep(0.01)
        self.volume.setDecimals(2)
        self.volume.setStatusTip(
            "Background-noise level (0-1); multiplied by the output safety cap."
        )

        self.color = QtWidgets.QComboBox(self)
        for color in NOISE_COLORS:
            self.color.addItem(color)
        self.color.setStatusTip("Spectral color of the built-in noise generator.")

        self.builtinRadio = QtWidgets.QRadioButton("Built-in generator", self)
        self.fileRadio = QtWidgets.QRadioButton("WAV file", self)
        self.builtinRadio.toggled.connect(self._sync_source_enabled)
        source_row = QtWidgets.QHBoxLayout()
        source_row.addWidget(self.builtinRadio)
        source_row.addWidget(self.fileRadio)
        source_row.addStretch(1)

        self.fileEdit = QtWidgets.QLineEdit(self)
        self.fileEdit.setStatusTip("WAV file played as the noise source.")
        self.browseButton = QtWidgets.QPushButton("Browse…", self)
        self.browseButton.setStatusTip("Choose the noise WAV file.")
        self.browseButton.clicked.connect(self._browse)
        file_row = QtWidgets.QHBoxLayout()
        file_row.addWidget(self.fileEdit, 1)
        file_row.addWidget(self.browseButton)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        form.addRow("Volume:", self.volume)
        form.addRow("Color:", self.color)
        form.addRow("Source:", source_row)
        form.addRow("File:", file_row)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(section_title("Noise"))
        layout.addLayout(form)
        layout.addStretch(1)

    def load(self, config: StudyConfig) -> None:
        noise = config.cueing.noise
        self.volume.setValue(noise.volume)
        index = self.color.findText(noise.color)
        self.color.setCurrentIndex(index if index >= 0 else 0)
        self.fileEdit.setText(noise.file)
        target = self.fileRadio if noise.source == "file" else self.builtinRadio
        target.setChecked(True)
        self._sync_source_enabled()

    def commit(self, config: StudyConfig) -> None:
        noise = config.cueing.noise
        noise.volume = self.volume.value()
        noise.color = self.color.currentText()
        noise.source = "file" if self.fileRadio.isChecked() else "builtin"
        noise.file = self.fileEdit.text().strip()

    def _sync_source_enabled(self) -> None:
        use_file = self.fileRadio.isChecked()
        self.fileEdit.setEnabled(use_file)
        self.browseButton.setEnabled(use_file)

    def _browse(self) -> None:
        chosen, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Choose noise WAV", self.fileEdit.text().strip(), "WAV file (*.wav)"
        )
        if chosen:
            self.fileEdit.setText(chosen)


class InterfaceForm(SectionForm):
    """Interface choices that travel with the study: output cap/latency, chat text.

    The runtime-only interface fields (the live-log preview levels, the always-on-top
    toggles) and the chat presets are intentionally not surfaced here; they round-trip
    untouched because :meth:`commit` writes only the four fields this form owns.
    """

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.volumeCap = QtWidgets.QDoubleSpinBox(self)
        self.volumeCap.setRange(0, 1)
        self.volumeCap.setSingleStep(0.01)
        self.volumeCap.setDecimals(2)
        self.volumeCap.setStatusTip(
            "Master ceiling on cue + noise output (1.00 = no cap): a safety limit so "
            "a full-volume cue can't blast the participant."
        )

        self.latency = QtWidgets.QComboBox(self)
        self.latency.addItem("High (robust)", "high")
        self.latency.addItem("Low (less delay)", "low")
        self.latency.setStatusTip(
            "Output buffer for cue + noise: High is robust; Low trims marker-to-sound "
            "delay but risks underruns."
        )

        self.fontSize = QtWidgets.QSpinBox(self)
        self.fontSize.setRange(8, 72)
        self.fontSize.setStatusTip("Font size of the participant/experimenter chat.")

        self.redText = QtWidgets.QCheckBox("Red chat text", self)
        self.redText.setStatusTip(
            "Show chat in red (dimmer on a dark-adapted eye than white)."
        )

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        form.addRow("Output safety cap:", self.volumeCap)
        form.addRow("Output latency:", self.latency)
        form.addRow("Chat font size:", self.fontSize)
        form.addRow("", self.redText)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(section_title("Interface"))
        layout.addLayout(form)
        layout.addStretch(1)

    def load(self, config: StudyConfig) -> None:
        ui = config.interface
        self.volumeCap.setValue(ui.volume_cap)
        index = self.latency.findData(ui.output_latency)
        self.latency.setCurrentIndex(index if index >= 0 else 0)
        self.fontSize.setValue(ui.chat_font_size)
        self.redText.setChecked(ui.chat_red_text)

    def commit(self, config: StudyConfig) -> None:
        ui = config.interface
        ui.volume_cap = self.volumeCap.value()
        ui.output_latency = self.latency.currentData()
        ui.chat_font_size = self.fontSize.value()
        ui.chat_red_text = self.redText.isChecked()
