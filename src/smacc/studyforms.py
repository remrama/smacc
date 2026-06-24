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

from PyQt6 import QtCore, QtGui, QtWidgets

from .studyconfig import StudyConfig

# The spectral colors the built-in noise generator can synthesize (mirrors the
# live Noise panel's dropdown).
NOISE_COLORS = ("white", "pink", "brown")


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
