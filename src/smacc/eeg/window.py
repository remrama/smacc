"""The EEG review window: open a recording, scroll it, annotate it (#136).

A standalone top-level window with its own process and ``QApplication`` (see
the package docstring) — not a launcher-managed :class:`~smacc.toolwindow
.ToolWindow`, since the launcher can't signal across processes. It owns a
:class:`~smacc.eeg.view.TraceView` plus the controls around it: open/save,
display filters, window length, amplitude scale, a scrollbar, and the
annotation list.

Annotation flow: a drag on the traces draws a span, the label dialog asks what
it was (seeded with sleep-research vocabulary and the operator's recent
labels), and Save writes the TSV/JSON sidecar next to the source recording.
Opening a file that already has a sidecar resumes from it; only a *fresh*
review imports the events embedded in the recording itself (re-importing on
every open would duplicate them into the saved sidecar). Unsaved changes mark
the title and prompt on close.

This is a *daytime* analysis tool: unlike the session windows there is no dark
theme, no always-on-top, and nothing here may import from the live-session
modules (the frozen ``SMACC-EEG.exe`` doesn't ship them all — and review work
must never share a process with a running night).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6 import QtCore, QtGui, QtWidgets

from .. import preferences, windowstate
from ..paths import LOGO_PATH, preferences_path
from . import blind, dsp, io
from .annotations import (
    Annotation,
    autosave_path,
    insert,
    rater_autosave_path,
    rater_sidecar_paths,
    read_annotations_tsv,
    remove,
    replace,
    sanitize_rater_id,
    sidecar_paths,
    write_annotations_json,
    write_annotations_tsv,
)
from .profiles import FILE_FILTER as PROFILE_FILE_FILTER
from .profiles import PROFILE_SUFFIX, ViewProfile, read_view_profile, write_view_profile
from .view import DEFAULT_EPOCH_SECONDS, TraceView

if TYPE_CHECKING:  # matplotlib is heavy: import the export module only on demand
    from .export import ExportOptions

# Stable id for this window's geometry entry in the per-window prefs map.
_EEG_WINDOW_ID = "eeg-review"

# Starting points for the label dropdown before an operator has any recents:
# the marks dream-engineering reviewers actually place (see the
# dream-engineering skill / docs). Free text is always allowed on top.
SEED_LABELS = ["LRLR", "Arousal", "Artifact", "Cue response"]
_MAX_RECENT_LABELS = 12

# Selectable page lengths, seconds. 30 s — the sleep-scoring epoch — is the
# default; the rest bracket it for fine inspection and context.
WINDOW_LENGTHS = (10, 30, 60, 120)
DEFAULT_WINDOW_LENGTH = 30

# The scrollbar works in tenths of a second: fine enough to land anywhere,
# coarse enough that an 8 h night stays within QScrollBar's int range.
_SCROLL_TICKS_PER_SECOND = 10

# Autosave (#176) is debounced: each annotation change restarts this timer, so a
# burst of edits writes the recovery file once, shortly after the last of them.
_AUTOSAVE_DEBOUNCE_MS = 2000

# Keyboard navigation (#174). Plain Left/Right page by one epoch; Shift nudges a
# second to peek across a boundary. Up/Down step the amplitude multiplicatively
# (Shift = a gentler factor) — louder means a smaller µV/lane, i.e. bigger traces.
_FINE_NUDGE_SECONDS = 1.0
_SCALE_KEY_FACTOR = 1.25
_SCALE_KEY_FACTOR_FINE = 1.1
_NAV_KEYS = frozenset(
    {
        QtCore.Qt.Key.Key_Left,
        QtCore.Qt.Key.Key_Right,
        QtCore.Qt.Key.Key_Up,
        QtCore.Qt.Key.Key_Down,
        QtCore.Qt.Key.Key_Home,
        QtCore.Qt.Key.Key_End,
    }
)
# Keys a focused combo box, list, or spin box uses for its own up/down selection;
# the filter yields these to such widgets but still claims Left/Right for paging.
_VERTICAL_NAV_KEYS = frozenset(
    {
        QtCore.Qt.Key.Key_Up,
        QtCore.Qt.Key.Key_Down,
        QtCore.Qt.Key.Key_Home,
        QtCore.Qt.Key.Key_End,
    }
)


def _section_title(text: str) -> QtWidgets.QLabel:
    """A centered 18pt section header (QFont, not stylesheet, so it follows
    the palette).

    Deliberately duplicated from ``panels.base.make_section_title``: importing
    ``panels.base`` executes ``import sounddevice`` and pulls in the whole
    live-session stack, which this process must never load (see the module
    docstring) and the frozen ``SMACC-EEG.exe`` will not ship.
    """
    label = QtWidgets.QLabel(text)
    label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
    font = QtGui.QFont()
    font.setPointSize(18)
    label.setFont(font)
    return label


def wall_time(recording: io.Recording, seconds: float) -> datetime | None:
    """The wall-clock time at ``seconds`` into ``recording``, or ``None``.

    Format-aware on purpose: EDF/BrainVision start times are the tech's
    wall-clock stamps that MNE only tags UTC pro forma, so they display as-is;
    a FIF ``meas_date`` is a true UTC instant, so it converts to this
    machine's local zone (the right answer whenever the file is reviewed in
    the timezone it was recorded in — the overwhelmingly common case).
    """
    start = recording.meas_date
    if start is None:
        return None
    if recording.path.suffix.lower() == ".fif":
        start = start.astimezone()
    return start + timedelta(seconds=seconds)


class LabelDialog(QtWidgets.QDialog):
    """Ask for an annotation's label: editable dropdown of recents + free text.

    The "instant" checkbox turns a drawn span into a zero-duration mark — the
    natural unit for events like an LRLR signal, where the moment matters and
    the drawn width was just the drag.
    """

    def __init__(
        self, parent: QtWidgets.QWidget | None, recents: list[str], initial: str = ""
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Annotation label")
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel("Label for this annotation:", self))
        self.labelCombo = QtWidgets.QComboBox(self)
        self.labelCombo.setEditable(True)
        seen: list[str] = []
        for label in [*recents, *SEED_LABELS]:
            if label not in seen:
                seen.append(label)
        self.labelCombo.addItems(seen)
        self.labelCombo.setCurrentText(initial)
        layout.addWidget(self.labelCombo)
        self.instantCheck = QtWidgets.QCheckBox(
            "Instantaneous mark (drop the drawn duration)", self
        )
        layout.addWidget(self.instantCheck)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def get_label(
        parent: QtWidgets.QWidget | None,
        recents: list[str],
        initial: str = "",
        *,
        offer_instant: bool = True,
    ) -> tuple[str, bool] | None:
        """Run the dialog; return ``(label, instant)`` or ``None`` on cancel.

        Cancel includes confirming an empty label — there is nothing useful to
        do with an unnamed span, so it reads as "never mind".
        """
        dialog = LabelDialog(parent, recents, initial)
        dialog.instantCheck.setVisible(offer_instant)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return None
        label = " ".join(dialog.labelCombo.currentText().split())
        if not label:
            return None
        return label, offer_instant and dialog.instantCheck.isChecked()


class ChannelPickerDialog(QtWidgets.QDialog):
    """Pick and order which channels the trace view shows (#177).

    Each channel has a checkbox (checked = shown); the Up/Down buttons reorder.
    Visible channels lead, in display order, then the hidden ones — so the common
    "hide a few, nudge the order" edit is quick.
    """

    def __init__(
        self, parent: QtWidgets.QWidget | None, ch_names: list[str], visible: list[int]
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Channels")
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(
            QtWidgets.QLabel("Shown channels (checked), top to bottom:", self)
        )
        body = QtWidgets.QHBoxLayout()
        self.listWidget = QtWidgets.QListWidget(self)
        self.listWidget.setMinimumWidth(240)
        hidden = [i for i in range(len(ch_names)) if i not in visible]
        for i in [*visible, *hidden]:
            item = QtWidgets.QListWidgetItem(ch_names[i])
            item.setData(QtCore.Qt.ItemDataRole.UserRole, i)
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                QtCore.Qt.CheckState.Checked
                if i in visible
                else QtCore.Qt.CheckState.Unchecked
            )
            self.listWidget.addItem(item)
        body.addWidget(self.listWidget, 1)
        buttonColumn = QtWidgets.QVBoxLayout()
        upButton = QtWidgets.QPushButton("Up", self)
        upButton.clicked.connect(lambda: self._move(-1))
        downButton = QtWidgets.QPushButton("Down", self)
        downButton.clicked.connect(lambda: self._move(1))
        buttonColumn.addWidget(upButton)
        buttonColumn.addWidget(downButton)
        buttonColumn.addStretch(1)
        body.addLayout(buttonColumn)
        layout.addLayout(body)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _move(self, delta: int) -> None:
        row = self.listWidget.currentRow()
        target = row + delta
        if row < 0 or not 0 <= target < self.listWidget.count():
            return
        item = self.listWidget.takeItem(row)
        self.listWidget.insertItem(target, item)
        self.listWidget.setCurrentRow(target)

    def result_indices(self) -> list[int]:
        out: list[int] = []
        for row in range(self.listWidget.count()):
            item = self.listWidget.item(row)
            if item is not None and item.checkState() == QtCore.Qt.CheckState.Checked:
                out.append(int(item.data(QtCore.Qt.ItemDataRole.UserRole)))
        return out

    @staticmethod
    def get_visible(
        parent: QtWidgets.QWidget | None, ch_names: list[str], visible: list[int]
    ) -> list[int] | None:
        """Run the dialog; return the chosen channel order, or ``None`` on cancel.

        An empty selection also reads as ``None`` (no change) — a montage with no
        channels is never what the operator wants.
        """
        dialog = ChannelPickerDialog(parent, ch_names, visible)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return None
        return dialog.result_indices() or None


class PaletteEditorDialog(QtWidgets.QDialog):
    """Edit the quick-mark palette: a reorderable list of labels (#181).

    The list order is the button order (and the first nine map to keys 1–9).
    Items rename in place (double-click); Add appends a new label. Labels are
    whitespace-normalized and blanks dropped, matching the annotation model.
    """

    def __init__(self, parent: QtWidgets.QWidget | None, labels: list[str]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Quick-mark palette")
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(
            QtWidgets.QLabel(
                "Quick-mark buttons, top to bottom (the first nine get keys 1–9):",
                self,
            )
        )
        body = QtWidgets.QHBoxLayout()
        self.listWidget = QtWidgets.QListWidget(self)
        self.listWidget.setMinimumWidth(220)
        for label in labels:
            self._append_item(label)
        body.addWidget(self.listWidget, 1)
        column = QtWidgets.QVBoxLayout()
        addButton = QtWidgets.QPushButton("Add…", self)
        addButton.clicked.connect(self._add)
        removeButton = QtWidgets.QPushButton("Remove", self)
        removeButton.clicked.connect(self._remove)
        upButton = QtWidgets.QPushButton("Up", self)
        upButton.clicked.connect(lambda: self._move(-1))
        downButton = QtWidgets.QPushButton("Down", self)
        downButton.clicked.connect(lambda: self._move(1))
        for button in (addButton, removeButton, upButton, downButton):
            column.addWidget(button)
        column.addStretch(1)
        body.addLayout(column)
        layout.addLayout(body)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _append_item(self, label: str) -> None:
        item = QtWidgets.QListWidgetItem(label)
        item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsEditable)
        self.listWidget.addItem(item)

    def _add(self) -> None:
        text, ok = QtWidgets.QInputDialog.getText(self, "Add quick mark", "Label:")
        if ok and text.strip():
            self._append_item(text.strip())
            self.listWidget.setCurrentRow(self.listWidget.count() - 1)

    def _remove(self) -> None:
        row = self.listWidget.currentRow()
        if row >= 0:
            self.listWidget.takeItem(row)

    def _move(self, delta: int) -> None:
        row = self.listWidget.currentRow()
        target = row + delta
        if row < 0 or not 0 <= target < self.listWidget.count():
            return
        item = self.listWidget.takeItem(row)
        self.listWidget.insertItem(target, item)
        self.listWidget.setCurrentRow(target)

    def result_labels(self) -> list[str]:
        out: list[str] = []
        for row in range(self.listWidget.count()):
            item = self.listWidget.item(row)
            text = " ".join(item.text().split()) if item is not None else ""
            if text:
                out.append(text)
        return out

    @staticmethod
    def get_palette(
        parent: QtWidgets.QWidget | None, labels: list[str]
    ) -> list[str] | None:
        """Run the dialog; return the edited label list, or ``None`` on cancel."""
        dialog = PaletteEditorDialog(parent, labels)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return None
        return dialog.result_labels()


class ExportDialog(QtWidgets.QDialog):
    """Choose what to export and how, for a publication figure (#180).

    Faithful to the on-screen view by construction; the controls only strip
    chrome (epoch grid, span shading), relabel marks (per-annotation editable
    text), set line weight, pick channels (via the #177 picker), and select the
    output format/resolution. Returns plain values — the window builds the
    ``ExportOptions`` so this dialog never imports matplotlib.
    """

    def __init__(
        self,
        parent: QtWidgets.QWidget | None,
        ch_names: list[str],
        visible: list[int],
        window_annotations: list[tuple[float, float, str]],
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export figure")
        self._ch_names = ch_names
        self._chosen_channels: list[int] | None = None
        # (onset, duration) per table row, parallel to the annotation rows.
        self._anno_spans = [
            (onset, duration) for onset, duration, _ in window_annotations
        ]
        form = QtWidgets.QFormLayout()

        self.channelsLabel = QtWidgets.QLabel(f"{len(visible)} shown", self)
        channelsButton = QtWidgets.QPushButton("Channels…", self)
        channelsButton.setStatusTip(
            "Choose and reorder which channels the figure shows."
        )
        channelsButton.clicked.connect(lambda: self._pick_channels(ch_names, visible))
        channelsRow = QtWidgets.QHBoxLayout()
        channelsRow.addWidget(self.channelsLabel)
        channelsRow.addWidget(channelsButton)
        channelsRow.addStretch(1)
        form.addRow("Channels:", channelsRow)

        self.titleEdit = QtWidgets.QLineEdit(self)
        self.titleEdit.setPlaceholderText("optional caption")
        form.addRow("Title:", self.titleEdit)

        self.formatCombo = QtWidgets.QComboBox(self)
        for label, value in (
            ("PNG (raster)", "png"),
            ("PDF (vector)", "pdf"),
            ("SVG (vector)", "svg"),
        ):
            self.formatCombo.addItem(label, value)
        self.formatCombo.currentIndexChanged.connect(self._on_format_changed)
        form.addRow("Format:", self.formatCombo)

        self.dpiCombo = QtWidgets.QComboBox(self)
        for dpi in (150, 300, 600):
            self.dpiCombo.addItem(f"{dpi} dpi", dpi)
        self.dpiCombo.setCurrentIndex(1)  # 300
        self.dpiCombo.setStatusTip(
            "Pixel density (PNG) and the rasterized trace layer in PDF/SVG."
        )
        form.addRow("Resolution:", self.dpiCombo)

        self.widthSpin = QtWidgets.QDoubleSpinBox(self)
        self.widthSpin.setRange(2.0, 30.0)
        self.widthSpin.setSingleStep(0.5)
        self.widthSpin.setValue(10.0)
        self.widthSpin.setSuffix(" in")
        form.addRow("Width:", self.widthSpin)

        self.lineWidthSpin = QtWidgets.QDoubleSpinBox(self)
        self.lineWidthSpin.setRange(0.2, 3.0)
        self.lineWidthSpin.setSingleStep(0.1)
        self.lineWidthSpin.setValue(0.7)
        self.lineWidthSpin.setSuffix(" pt")
        form.addRow("Trace weight:", self.lineWidthSpin)

        self.channelLabelsCheck = QtWidgets.QCheckBox("Channel labels", self)
        self.channelLabelsCheck.setChecked(True)
        self.epochGridCheck = QtWidgets.QCheckBox(
            "Epoch gridlines", self
        )  # off = clean
        self.shadingCheck = QtWidgets.QCheckBox(
            "Annotation shading", self
        )  # off = clean
        self.markLabelsCheck = QtWidgets.QCheckBox("Annotation labels", self)
        self.markLabelsCheck.setChecked(True)
        self.svgTextCheck = QtWidgets.QCheckBox("Editable SVG text", self)
        self.svgTextCheck.setChecked(True)
        self.svgTextCheck.setEnabled(False)  # only meaningful for SVG
        for check in (
            self.channelLabelsCheck,
            self.epochGridCheck,
            self.shadingCheck,
            self.markLabelsCheck,
            self.svgTextCheck,
        ):
            form.addRow("", check)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(QtWidgets.QLabel("Annotations in this window:", self))
        self.annoTable = QtWidgets.QTableWidget(len(window_annotations), 2, self)
        self.annoTable.setHorizontalHeaderLabels(["Show", "Label"])
        self.annoTable.setMinimumWidth(320)
        vheader = self.annoTable.verticalHeader()
        if vheader is not None:
            vheader.setVisible(False)
        header = self.annoTable.horizontalHeader()
        assert header is not None
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        for row, (_onset, _duration, description) in enumerate(window_annotations):
            include = QtWidgets.QTableWidgetItem()
            include.setFlags(
                QtCore.Qt.ItemFlag.ItemIsUserCheckable
                | QtCore.Qt.ItemFlag.ItemIsEnabled
            )
            include.setCheckState(QtCore.Qt.CheckState.Checked)
            self.annoTable.setItem(row, 0, include)
            self.annoTable.setItem(row, 1, QtWidgets.QTableWidgetItem(description))
        layout.addWidget(self.annoTable, 1)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_format_changed(self) -> None:
        self.svgTextCheck.setEnabled(self.formatCombo.currentData() == "svg")

    def _pick_channels(self, ch_names: list[str], visible: list[int]) -> None:
        current = (
            self._chosen_channels if self._chosen_channels is not None else visible
        )
        result = ChannelPickerDialog.get_visible(self, ch_names, current)
        if result is not None:
            self._chosen_channels = result
            self.channelsLabel.setText(f"{len(result)} shown")

    def result_values(
        self,
    ) -> tuple[ExportOptions, list[tuple[float, float, str]], list[int] | None]:
        """Return ``(options, marks, chosen_channels)`` from the controls.

        Lazy-imports the export module (matplotlib) only here, once the dialog is
        accepted — never at window startup.
        """
        from . import export

        marks: list[tuple[float, float, str]] = []
        for row, (onset, duration) in enumerate(self._anno_spans):
            include = self.annoTable.item(row, 0)
            label_item = self.annoTable.item(row, 1)
            if (
                include is not None
                and include.checkState() == QtCore.Qt.CheckState.Checked
            ):
                label = label_item.text().strip() if label_item is not None else ""
                marks.append((onset, duration, label))
        options = export.ExportOptions(
            fmt=self.formatCombo.currentData(),
            dpi=int(self.dpiCombo.currentData()),
            width_in=float(self.widthSpin.value()),
            line_width_pt=float(self.lineWidthSpin.value()),
            show_channel_labels=self.channelLabelsCheck.isChecked(),
            show_epoch_grid=self.epochGridCheck.isChecked(),
            show_mark_shading=self.shadingCheck.isChecked(),
            show_mark_labels=self.markLabelsCheck.isChecked(),
            svg_text_as_text=self.svgTextCheck.isChecked(),
            title=self.titleEdit.text().strip(),
        )
        return options, marks, self._chosen_channels

    @staticmethod
    def get_export(
        parent: QtWidgets.QWidget | None,
        ch_names: list[str],
        visible: list[int],
        window_annotations: list[tuple[float, float, str]],
    ) -> tuple[ExportOptions, list[tuple[float, float, str]], list[int] | None] | None:
        """Run the dialog; return ``(options, marks, channels)`` or ``None`` on cancel."""
        dialog = ExportDialog(parent, ch_names, visible, window_annotations)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return None
        return dialog.result_values()


class EegReviewWindow(QtWidgets.QMainWindow):
    """Review and annotate one recording; the EEG component's main window."""

    def __init__(
        self,
        file_path: str | Path | None = None,
        rater_id: str | None = None,
        blind_spec: str | None = None,
    ) -> None:
        super().__init__()
        self._recording: io.Recording | None = None
        self._annotations: list[Annotation] = []
        self._dirty = False
        self._cursor_seconds: float | None = None  # last mouse time over the traces
        # True once this review's annotations live in the canonical sidecar (we
        # loaded it, or we have saved at least once); gates the overwrite prompt.
        self._owns_sidecar = False
        # The rater whose sidecar this review reads and writes (#181): None is an
        # ordinary single-rater review on the plain sidecar; a value routes every
        # save/load/autosave to a per-rater path. Resolved arg → pref → none (no
        # prompt — a solo reviewer is never nagged).
        self._rater_id: str | None = self._resolve_rater_id(rater_id)
        # Rater ids confirmed at save this session, so the confirm-before-save
        # prompt fires once per id, not on every save.
        self._confirmed_raters: set[str] = set()
        # Blind-rater mode (#181): a filter applied at load so a rater never sees
        # hidden marks. None is an ordinary review. A bad --blind value is held
        # and surfaced after the window shows (see the deferred error below).
        self._blind: blind.BlindConfig | None = None
        self._blind_error: str | None = None
        if blind_spec:
            try:
                self._blind = blind.resolve_blind(blind_spec)
            except (OSError, ValueError) as exc:
                self._blind_error = str(exc)
        # Annotations recovered from an autosave, held until the user restores or
        # dismisses them (#176).
        self._recovery_annotations: list[Annotation] | None = None
        # Debounced crash-recovery autosave (#176): restarted on every change.
        self._autosave_timer = QtCore.QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(_AUTOSAVE_DEBOUNCE_MS)
        self._autosave_timer.timeout.connect(self._write_autosave)
        self.setWindowTitle("SMACC — EEG review")
        if LOGO_PATH.is_file():
            self.setWindowIcon(QtGui.QIcon(str(LOGO_PATH)))
        self._build()
        self._set_loaded(False)
        # An application-level filter so epoch/amplitude keys work from anywhere in
        # the window, not only after clicking the traces (#174); removed on close.
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        if self._blind_error is not None:
            # A bad --blind value: warn once the window is up (a constructor-time
            # dialog would race the first paint), then proceed unblinded.
            QtCore.QTimer.singleShot(
                0,
                lambda: self._error(
                    "Could not apply the blind config.", self._blind_error
                ),
            )
        if file_path is not None:
            # After the event loop starts, so the window is up before any
            # open-error dialog (and a long load doesn't block the first paint).
            QtCore.QTimer.singleShot(0, lambda: self._load(Path(file_path)))

    # ----- rater identity (#181) ----------------------------------------------

    def _resolve_rater_id(self, rater_id: str | None) -> str | None:
        """Pick the active rater id: explicit arg, else the saved pref, else none.

        Deliberately no prompt for the bare default — a solo reviewer keeps the
        plain sidecar and is never asked; a rater id only appears when one was
        passed (``--rater``) or set in a prior session. An unusable saved/passed
        id falls back to single-rater rather than failing to open.
        """
        if rater_id is None:
            prefs = preferences.load_preferences(preferences_path)
            rater_id = prefs.get("eeg_rater_id")
        if not rater_id:
            return None
        try:
            return sanitize_rater_id(rater_id)
        except ValueError:
            return None

    def _sidecar_for(self, source: str | Path) -> tuple[Path, Path]:
        """The (TSV, JSON) sidecar paths for the active rater (plain if none)."""
        if self._rater_id is None:
            return sidecar_paths(source)
        return rater_sidecar_paths(source, self._rater_id)

    def _autosave_for(self, source: str | Path) -> Path:
        """The crash-recovery autosave path for the active rater (plain if none)."""
        if self._rater_id is None:
            return autosave_path(source)
        return rater_autosave_path(source, self._rater_id)

    def _refresh_rater_button(self) -> None:
        """Keep the rater button (and so the toolbar) showing the active id."""
        self.raterButton.setText(
            f"Rater: {self._rater_id}" if self._rater_id else "Rater…"
        )

    def _set_rater_id(self) -> None:
        """Prompt for the rater id and switch to it (blank clears it)."""
        text, ok = QtWidgets.QInputDialog.getText(
            self,
            "Rater id",
            "Rater id (annotations save to a per-rater sidecar; "
            "leave blank for a single-rater review):",
            text=self._rater_id or "",
        )
        if not ok:
            return
        text = text.strip()
        if not text:
            self._apply_rater_id(None)
            return
        try:
            self._apply_rater_id(sanitize_rater_id(text))
        except ValueError:
            self._error(
                "That rater id can't be used.",
                "A rater id needs at least one letter, digit, dash, or underscore.",
            )

    def _apply_rater_id(self, new_id: str | None) -> None:
        """Switch the active rater id, re-pointing this review's output to it.

        A correction, not a merge (#181): the current marks are *this* rater's,
        so the previous id's autosave is dropped (it was misattributed) and the
        marks now save under ``new_id``. We have not loaded the new id's sidecar,
        so ``_owns_sidecar`` re-arms — the first save into an existing foreign
        file then prompts via the usual overwrite guard.
        """
        if new_id == self._rater_id:
            return
        self._autosave_timer.stop()
        self._clear_autosave()  # uses the *old* id (still current here)
        self._rater_id = new_id
        self._owns_sidecar = False
        # Re-confirm the new id on its next save (discard is a no-op for None).
        self._confirmed_raters.discard(new_id)
        preferences.update_preferences(preferences_path, {"eeg_rater_id": new_id})
        self._refresh_rater_button()
        if self._recording is not None and self._annotations:
            self._mark_dirty()  # unsaved work now belongs to the new id
        self._refresh_title()

    def _confirm_rater_identity(self) -> bool:
        """Confirm the active rater id once per id per session before its first save.

        A single-rater review (no id) never prompts; once an id is confirmed it
        stays confirmed until it changes, so routine saves are silent. The rater
        button stays visible to fix a wrong id without saving.
        """
        if self._rater_id is None or self._rater_id in self._confirmed_raters:
            return True
        button = QtWidgets.QMessageBox.question(
            self,
            "Confirm rater",
            f"Save these annotations as rater '{self._rater_id}'?\n\n"
            "Use the Rater button to change it.",
            QtWidgets.QMessageBox.StandardButton.Save
            | QtWidgets.QMessageBox.StandardButton.Cancel,
        )
        if button == QtWidgets.QMessageBox.StandardButton.Save:
            self._confirmed_raters.add(self._rater_id)
            return True
        return False

    # ----- UI construction ----------------------------------------------------

    def _build(self) -> None:
        central = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)
        layout.addWidget(_section_title("EEG review"))
        layout.addWidget(self._build_contract_caption())
        layout.addWidget(self._build_recovery_banner())
        layout.addLayout(self._build_controls_row())
        layout.addLayout(self._build_epoch_row())
        layout.addLayout(self._build_palette_row())

        body = QtWidgets.QHBoxLayout()
        viewColumn = QtWidgets.QVBoxLayout()
        self.view = TraceView()
        self.view.regionDrawn.connect(self._on_region_drawn)
        self.view.annotationSelected.connect(self._on_view_selection)
        self.view.windowChanged.connect(self._sync_scrollbar)
        self.view.cursorMoved.connect(self._on_cursor_moved)
        self.view.pointMarkRequested.connect(self._add_point_mark)
        viewColumn.addWidget(self.view, 1)
        self.scrollBar = QtWidgets.QScrollBar(QtCore.Qt.Orientation.Horizontal, self)
        self.scrollBar.setStatusTip("Scroll through the recording.")
        self.scrollBar.valueChanged.connect(self._on_scrollbar)
        viewColumn.addWidget(self.scrollBar)
        body.addLayout(viewColumn, 1)
        body.addLayout(self._build_annotation_panel())
        layout.addLayout(body, 1)

        self.statusBar()
        # Permanent (right-aligned) state: the epoch at the left edge of the view
        # and the recording summary. Transient messages and the cursor clock use
        # the normal message area.
        self.epochLabel = QtWidgets.QLabel("", self)
        self.epochLabel.setStatusTip("The epoch at the left edge of the view.")
        self.fileInfoLabel = QtWidgets.QLabel("", self)
        status_bar = self.statusBar()
        assert status_bar is not None
        status_bar.addPermanentWidget(self.epochLabel)
        status_bar.addPermanentWidget(self.fileInfoLabel)

        self._build_shortcuts()
        self.setCentralWidget(central)
        prefs = preferences.load_preferences(preferences_path)
        geometry = preferences.window_geometry(prefs, _EEG_WINDOW_ID)
        windowstate.restore_geometry(self, geometry, default_size=(1150, 700))

    def _build_controls_row(self) -> QtWidgets.QLayout:
        row = QtWidgets.QHBoxLayout()
        openButton = QtWidgets.QPushButton("Open recording…", self)
        openButton.setStatusTip(
            "Open an EEG recording (EDF, BrainVision, FIF, Neuroscan .cnt, EEGLAB .set)."
        )
        openButton.clicked.connect(self.open_file)
        row.addWidget(openButton)
        row.addSpacing(12)

        # Per-type display (#177): the filter and scale controls below edit the
        # channel type selected here. "All channels" edits the base that every
        # type without its own override inherits.
        row.addWidget(QtWidgets.QLabel("Apply to:", self))
        self.filterScopeCombo = QtWidgets.QComboBox(self)
        self.filterScopeCombo.addItem("All channels", None)
        self.filterScopeCombo.setStatusTip(
            "Which channels the filter and scale below edit (a type, or all)."
        )
        self.filterScopeCombo.currentIndexChanged.connect(self._on_scope_changed)
        row.addWidget(self.filterScopeCombo)
        row.addSpacing(8)

        # Display filters. 0 reads as "Off" (special value text): the viewer
        # opens unfiltered — silently rewriting amplitudes before the operator
        # asked would misrepresent the recording.
        row.addWidget(QtWidgets.QLabel("High-pass:", self))
        self.highpassSpin = QtWidgets.QDoubleSpinBox(self)
        self.highpassSpin.setRange(0.0, 100.0)
        self.highpassSpin.setDecimals(2)
        self.highpassSpin.setSingleStep(0.1)
        self.highpassSpin.setSuffix(" Hz")
        self.highpassSpin.setSpecialValueText("Off")
        self.highpassSpin.setStatusTip(
            "Drop slow drift below this frequency (0.3 Hz is the usual sleep view)."
        )
        row.addWidget(self.highpassSpin)
        row.addWidget(QtWidgets.QLabel("Low-pass:", self))
        self.lowpassSpin = QtWidgets.QDoubleSpinBox(self)
        self.lowpassSpin.setRange(0.0, 500.0)
        self.lowpassSpin.setDecimals(1)
        self.lowpassSpin.setSingleStep(5.0)
        self.lowpassSpin.setSuffix(" Hz")
        self.lowpassSpin.setSpecialValueText("Off")
        self.lowpassSpin.setStatusTip(
            "Drop fast noise above this frequency (35 Hz is the usual sleep view)."
        )
        row.addWidget(self.lowpassSpin)
        row.addWidget(QtWidgets.QLabel("Notch:", self))
        self.notchCombo = QtWidgets.QComboBox(self)
        self.notchCombo.addItem("Off", None)
        self.notchCombo.addItem("50 Hz", 50.0)
        self.notchCombo.addItem("60 Hz", 60.0)
        self.notchCombo.setStatusTip("Remove mains interference (50 Hz EU, 60 Hz US).")
        row.addWidget(self.notchCombo)
        for widget in (self.highpassSpin, self.lowpassSpin):
            widget.valueChanged.connect(self._on_filters_changed)
        self.notchCombo.currentIndexChanged.connect(self._on_filters_changed)
        row.addSpacing(12)

        row.addWidget(QtWidgets.QLabel("Window:", self))
        self.windowCombo = QtWidgets.QComboBox(self)
        for seconds in WINDOW_LENGTHS:
            self.windowCombo.addItem(f"{seconds} s", float(seconds))
        self.windowCombo.setCurrentIndex(WINDOW_LENGTHS.index(DEFAULT_WINDOW_LENGTH))
        self.windowCombo.setStatusTip(
            "How many seconds are on screen (30 s is one scoring epoch)."
        )
        self.windowCombo.currentIndexChanged.connect(self._on_window_length_changed)
        row.addWidget(self.windowCombo)

        row.addWidget(QtWidgets.QLabel("Scale:", self))
        self.scaleSpin = QtWidgets.QDoubleSpinBox(self)
        self.scaleSpin.setRange(1.0, 10000.0)
        self.scaleSpin.setDecimals(0)
        self.scaleSpin.setValue(100.0)
        self.scaleSpin.setSuffix(" µV")
        self.scaleSpin.setStatusTip(
            "Microvolts per channel lane — smaller means visually bigger traces."
        )
        self.scaleSpin.valueChanged.connect(self._on_scale_changed)
        row.addWidget(self.scaleSpin)

        row.addStretch(1)
        # Blind-rater mode (#181): hide/blank marks before they render, for blind
        # scoring. Needs a rater id (so marks save to the rater's own sidecar).
        self.blindButton = QtWidgets.QPushButton(self)
        self.blindButton.setStatusTip(
            "Blind-rater mode: hide or blank marks before they are shown "
            "(needs a rater id)."
        )
        self.blindButton.clicked.connect(self._choose_blind_mode)
        self._refresh_blind_button()
        row.addWidget(self.blindButton)
        # Rater identity (#181): blank for a single-rater review; set it and every
        # save/load/autosave routes to a per-rater sidecar. Always enabled — the id
        # can be set before a recording is open and persists for next launch.
        self.raterButton = QtWidgets.QPushButton(self)
        self.raterButton.setStatusTip(
            "Set the rater id; annotations then save to a per-rater sidecar "
            "(night1.annotations.<id>.tsv). Blank means a single-rater review."
        )
        self.raterButton.clicked.connect(self._set_rater_id)
        self._refresh_rater_button()
        row.addWidget(self.raterButton)
        self.saveButton = QtWidgets.QPushButton("Save annotations", self)
        self.saveButton.setStatusTip(
            "Write the annotation sidecar next to the recording; the recording "
            "itself is never modified."
        )
        self.saveButton.setToolTip(
            "Saves the annotation sidecar (TSV/JSON) next to the recording.\n"
            "The recording is never modified; filters, scaling, channel selection "
            "and the epoch grid are view-only."
        )
        self.saveButton.clicked.connect(self.save_annotations)
        row.addWidget(self.saveButton)
        return row

    def _build_epoch_row(self) -> QtWidgets.QLayout:
        """The epoch model controls (#173): length, grid, anchor, time-axis mode.

        A second row so the busy filter/window/scale row above stays legible. The
        epoch length is deliberately *separate* from the on-screen window length —
        a 30 s scoring epoch can be inspected inside a 60 s window.
        """
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Epoch:", self))
        self.epochSpin = QtWidgets.QSpinBox(self)
        self.epochSpin.setRange(1, 300)
        self.epochSpin.setValue(int(DEFAULT_EPOCH_SECONDS))
        self.epochSpin.setSuffix(" s")
        self.epochSpin.setStatusTip(
            "Scoring-epoch length (30 s is standard) — independent of the window."
        )
        self.epochSpin.valueChanged.connect(self._on_epoch_seconds_changed)
        row.addWidget(self.epochSpin)

        self.epochGridCheck = QtWidgets.QCheckBox("Epoch grid", self)
        self.epochGridCheck.setChecked(True)
        self.epochGridCheck.setStatusTip("Show faint, numbered epoch boundaries.")
        self.epochGridCheck.toggled.connect(
            lambda checked: self.view.set_epochs_visible(checked)
        )
        row.addWidget(self.epochGridCheck)

        self.anchorButton = QtWidgets.QPushButton("Anchor epochs to view", self)
        self.anchorButton.setStatusTip(
            "Start an epoch at the left edge of the view (back/front-fills the grid)."
        )
        self.anchorButton.clicked.connect(self._anchor_epochs_to_view)
        row.addWidget(self.anchorButton)
        self.resetAnchorButton = QtWidgets.QPushButton("Reset anchor", self)
        self.resetAnchorButton.setStatusTip(
            "Put epoch 1 back at the start of the recording."
        )
        self.resetAnchorButton.clicked.connect(self._reset_epoch_anchor)
        row.addWidget(self.resetAnchorButton)

        row.addSpacing(12)
        row.addWidget(QtWidgets.QLabel("Time axis:", self))
        self.axisModeCombo = QtWidgets.QComboBox(self)
        self.axisModeCombo.addItem("Clock", "clock")
        self.axisModeCombo.addItem("Elapsed", "elapsed")
        self.axisModeCombo.setStatusTip(
            "Label the time axis with wall-clock time or seconds from the start."
        )
        self.axisModeCombo.currentIndexChanged.connect(
            lambda: self.view.set_time_axis_mode(self.axisModeCombo.currentData())
        )
        row.addWidget(self.axisModeCombo)
        row.addStretch(1)
        self.channelsButton = QtWidgets.QPushButton("Channels…", self)
        self.channelsButton.setStatusTip("Choose and reorder which channels are shown.")
        self.channelsButton.clicked.connect(self._open_channel_picker)
        row.addWidget(self.channelsButton)
        self.saveProfileButton = QtWidgets.QPushButton("Save profile…", self)
        self.saveProfileButton.setStatusTip(
            "Save this montage (channels, filters, scale, window/epoch) to a file."
        )
        self.saveProfileButton.clicked.connect(self._save_profile)
        row.addWidget(self.saveProfileButton)
        self.loadProfileButton = QtWidgets.QPushButton("Load profile…", self)
        self.loadProfileButton.setStatusTip("Apply a saved montage to this recording.")
        self.loadProfileButton.clicked.connect(self._load_profile)
        row.addWidget(self.loadProfileButton)
        self.exportButton = QtWidgets.QPushButton("Export figure…", self)
        self.exportButton.setStatusTip(
            "Export the current window as a publication PNG, PDF, or SVG."
        )
        self.exportButton.clicked.connect(self._export_figure)
        row.addWidget(self.exportButton)
        return row

    def _build_palette_row(self) -> QtWidgets.QLayout:
        """The quick-mark palette (#181): one-click labels dropped at the cursor.

        A configurable row of buttons, each inserting a labeled point mark with no
        dialog — the fast path for a rater scoring signals. The first nine also
        answer to number keys 1–9 (see :meth:`_handle_palette_key`)."""
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Quick marks:", self))
        self.paletteButtonsLayout = QtWidgets.QHBoxLayout()
        self.paletteButtonsLayout.setSpacing(4)
        self._palette_buttons: list[QtWidgets.QPushButton] = []
        row.addLayout(self.paletteButtonsLayout)
        row.addStretch(1)
        self.editPaletteButton = QtWidgets.QPushButton("Edit palette…", self)
        self.editPaletteButton.setStatusTip(
            "Choose the quick-mark buttons (each drops its label at the cursor)."
        )
        self.editPaletteButton.clicked.connect(self._edit_palette)
        row.addWidget(self.editPaletteButton)
        self._rebuild_palette_buttons()
        return row

    def _build_contract_caption(self) -> QtWidgets.QLabel:
        """A quiet, always-visible reminder of the tool's safety contract (#175)."""
        caption = QtWidgets.QLabel(
            "Saves annotations to a sidecar — your recording is never modified.",
            self,
        )
        caption.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        caption.setEnabled(False)  # renders dimmed, following the palette
        return caption

    def _build_recovery_banner(self) -> QtWidgets.QWidget:
        """A non-modal bar offering to restore autosaved annotations (#176).

        Hidden until a recovery file is found on open; restoring is always an
        explicit choice, never applied silently.
        """
        banner = QtWidgets.QFrame(self)
        banner.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        banner.setVisible(False)
        row = QtWidgets.QHBoxLayout(banner)
        row.setContentsMargins(8, 4, 8, 4)
        self.recoveryLabel = QtWidgets.QLabel("", banner)
        row.addWidget(self.recoveryLabel, 1)
        restoreButton = QtWidgets.QPushButton("Restore", banner)
        restoreButton.setStatusTip("Load the autosaved annotations into this review.")
        restoreButton.clicked.connect(self._restore_autosave)
        row.addWidget(restoreButton)
        dismissButton = QtWidgets.QPushButton("Dismiss", banner)
        dismissButton.setStatusTip("Discard the autosaved annotations and delete them.")
        dismissButton.clicked.connect(self._dismiss_autosave)
        row.addWidget(dismissButton)
        self.recoveryBanner = banner
        return banner

    def _build_annotation_panel(self) -> QtWidgets.QLayout:
        panel = QtWidgets.QVBoxLayout()
        panel.addWidget(QtWidgets.QLabel("Annotations:", self))
        self.annotationList = QtWidgets.QListWidget(self)
        self.annotationList.setMinimumWidth(230)
        self.annotationList.setStatusTip(
            "Click to highlight; double-click to jump the view there."
        )
        self.annotationList.currentRowChanged.connect(self._on_list_selection)
        self.annotationList.itemDoubleClicked.connect(
            lambda _item: self.go_to_selected()
        )
        panel.addWidget(self.annotationList, 1)
        buttons = QtWidgets.QHBoxLayout()
        self.editButton = QtWidgets.QPushButton("Edit…", self)
        self.editButton.setStatusTip("Rename the selected annotation.")
        self.editButton.clicked.connect(self.edit_selected)
        self.deleteButton = QtWidgets.QPushButton("Delete", self)
        self.deleteButton.setStatusTip("Delete the selected annotation.")
        self.deleteButton.clicked.connect(self.delete_selected)
        buttons.addWidget(self.editButton)
        buttons.addWidget(self.deleteButton)
        panel.addLayout(buttons)
        return panel

    def _build_shortcuts(self) -> None:
        """Window-wide paging on PageUp/PageDown, plus M to drop a point mark.

        Arrow/Home/End navigation and amplitude are handled by the application
        event filter (see :meth:`eventFilter`), which works regardless of focus;
        no text widget steals PageUp/Down or a bare M, so those stay plain
        QShortcuts here.
        """
        for keys, fraction in (
            (QtCore.Qt.Key.Key_PageDown, 1.0),
            (QtCore.Qt.Key.Key_PageUp, -1.0),
        ):
            shortcut = QtGui.QShortcut(QtGui.QKeySequence(keys), self)
            shortcut.activated.connect(lambda f=fraction: self.view.scroll_by(f))
        mark = QtGui.QShortcut(QtGui.QKeySequence(QtCore.Qt.Key.Key_M), self)
        mark.activated.connect(self._mark_at_cursor)

    def _set_loaded(self, loaded: bool) -> None:
        for widget in (
            self.saveButton,
            self.editButton,
            self.deleteButton,
            self.scrollBar,
            self.filterScopeCombo,
            self.channelsButton,
            self.saveProfileButton,
            self.loadProfileButton,
            self.exportButton,
        ):
            widget.setEnabled(loaded)
        for button in self._palette_buttons:  # no recording → nothing to mark
            button.setEnabled(loaded)

    # ----- quick-mark palette (#181) ---------------------------------------------

    def _palette_labels(self) -> list[str]:
        """The active quick-mark labels: a blind config's palette wins, else prefs.

        A loaded blind config can ship its own classification vocabulary so a
        coordinator hands out the buttons too; otherwise the operator's saved
        palette applies (falling back to the seed labels if it is unreadable).
        """
        if self._blind is not None and self._blind.palette:
            return list(self._blind.palette)
        prefs = preferences.load_preferences(preferences_path)
        labels = prefs.get("eeg_palette_labels")
        if not isinstance(labels, list):
            return list(SEED_LABELS)
        return [s for s in labels if isinstance(s, str) and s.strip()]

    def _rebuild_palette_buttons(self) -> None:
        """Recreate the quick-mark buttons from the saved palette."""
        while self.paletteButtonsLayout.count():
            item = self.paletteButtonsLayout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        self._palette_buttons = []
        for index, label in enumerate(self._palette_labels()):
            button = QtWidgets.QPushButton(label, self)
            hint = "Drop this label at the cursor"
            if index < 9:  # the first nine answer to number keys 1–9
                hint += f" (key {index + 1})"
            button.setStatusTip(hint + ".")
            button.clicked.connect(
                lambda _checked=False, text=label: self._insert_label_at_cursor(text)
            )
            button.setEnabled(self._recording is not None)
            self.paletteButtonsLayout.addWidget(button)
            self._palette_buttons.append(button)

    def _edit_palette(self) -> None:
        """Edit and persist the quick-mark palette, then rebuild the buttons."""
        result = PaletteEditorDialog.get_palette(self, self._palette_labels())
        if result is None:
            return
        preferences.update_preferences(preferences_path, {"eeg_palette_labels": result})
        self._rebuild_palette_buttons()

    # ----- blind-rater mode (#181) -----------------------------------------------

    def _refresh_blind_button(self) -> None:
        """Keep the Blind button showing the active preset (or off)."""
        self.blindButton.setText(
            f"Blind: {self._blind.preset}" if self._blind is not None else "Blind: off"
        )

    def _choose_blind_mode(self) -> None:
        """Pop up the blind-mode menu: a preset, a config file, or off."""
        menu = QtWidgets.QMenu(self)
        menu.addAction("Off", lambda: self._set_blind(None))
        menu.addAction(
            "Fully naive",
            lambda: self._set_blind(blind.preset_config(blind.PRESET_NAIVE)),
        )
        menu.addAction(
            "Reports visible",
            lambda: self._set_blind(blind.preset_config(blind.PRESET_REPORTS)),
        )
        menu.addAction(
            "Signal-present (classify only)",
            lambda: self._set_blind(blind.preset_config(blind.PRESET_CLASSIFY)),
        )
        menu.addSeparator()
        menu.addAction("Load config file…", self._load_blind_config)
        menu.exec(self.blindButton.mapToGlobal(self.blindButton.rect().bottomLeft()))

    def _set_blind(self, config: blind.BlindConfig | None) -> None:
        """Switch the blind mode, re-resolving the open recording through it.

        Blinding needs a rater id (so marks save to the rater's own sidecar, never
        the coordinator's truth). Changing the view re-reads the recording from
        the data boundary, discarding in-progress edits, so confirm first.
        """
        if config is not None and self._rater_id is None:
            self._error(
                "Blind review needs a rater id.",
                "Set a rater id with the Rater button first, so the rater's marks "
                "save to their own sidecar.",
            )
            return
        if self._recording is not None and not self._confirm_discard():
            return
        self._blind = config
        self._refresh_blind_button()
        self._rebuild_palette_buttons()  # a config may carry its own palette
        if self._recording is not None:
            self._load(self._recording.path)  # re-resolve marks under the new mode
        self._refresh_title()

    def _load_blind_config(self) -> None:
        """Load a shareable .smacc-blind.json and switch to it."""
        prefs = preferences.load_preferences(preferences_path)
        start_dir = prefs.get("eeg_last_blind_dir") or (
            str(self._recording.path.parent)
            if self._recording is not None
            else str(Path.home())
        )
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load blind config", str(start_dir), blind.FILE_FILTER
        )
        if not path:
            return
        try:
            config = blind.read_blind_config(path)
        except (OSError, ValueError) as exc:
            self._error("Could not read the blind config.", str(exc))
            return
        preferences.update_preferences(
            preferences_path, {"eeg_last_blind_dir": str(Path(path).parent)}
        )
        self._set_blind(config)

    # ----- opening a recording ---------------------------------------------------

    def open_file(self) -> None:
        if not self._confirm_discard():
            return
        prefs = preferences.load_preferences(preferences_path)
        start_dir = prefs.get("eeg_last_dir") or str(Path.home())
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open EEG recording", str(start_dir), io.FILE_FILTER
        )
        if path:
            self._load(Path(path))

    def _load(self, path: Path) -> None:
        # Blind review must write to a rater's own sidecar, never the coordinator's
        # truth file: without a rater id the resume/save would clobber the truth.
        # Refuse before opening anything (the data-loss guard for #181c).
        if self._blind is not None and self._rater_id is None:
            self._error(
                "Blind review needs a rater id.",
                "Set a rater id (the Rater button or --rater) before a blind "
                "review, so the rater's marks save to their own sidecar and never "
                "overwrite the coordinator's truth file.",
            )
            return
        try:
            recording = io.open_recording(path)
        except (ValueError, OSError, RuntimeError) as exc:
            self._error("Could not open the recording.", str(exc))
            return
        # Opened cleanly: stop autosaving the recording we're leaving and drop its
        # recovery file (the user already saved or discarded it via open_file).
        self._autosave_timer.stop()
        self._clear_autosave()
        tsv_path, _ = self._sidecar_for(path)
        if tsv_path.is_file():
            # Resume a previous review. A sidecar that exists but won't parse
            # aborts the open: it is the reviewer's data, and proceeding would
            # overwrite it with an empty list on the next save. A rater's own
            # resumed marks are theirs, so they are never re-blinded.
            try:
                annotations = read_annotations_tsv(tsv_path)
            except (OSError, ValueError) as exc:
                self._error(
                    "Could not read the existing annotations sidecar.",
                    f"{tsv_path.name}: {exc}\n\nFix or rename the sidecar, "
                    "then open the recording again.",
                )
                return
        else:
            fresh = self._fresh_annotations(path, recording)
            if fresh is None:  # a blind seed sidecar that won't parse
                return
            annotations = fresh
        self._recording = recording
        self._annotations = annotations
        self._dirty = False
        # We own the sidecar when we loaded from it; a fresh review does not yet,
        # so its first save guards against overwriting one that appeared meanwhile.
        self._owns_sidecar = tsv_path.is_file()
        self.view.set_provider(recording)
        self.view.set_annotations(annotations)
        # Hand the view the localized recording start so the time axis can label
        # clock time; default to clock when the file carries one, else elapsed.
        started = wall_time(recording, 0.0)
        self.view.set_time_origin(started)
        self.axisModeCombo.blockSignals(True)
        self.axisModeCombo.setCurrentIndex(0 if started is not None else 1)
        self.axisModeCombo.blockSignals(False)
        self.view.set_time_axis_mode(self.axisModeCombo.currentData())
        # Rebuild the per-type filter scope from this recording's types and show
        # the base filter/scale in the controls (#177).
        self._populate_scope_combo()
        self._load_scope_into_controls()
        self._refresh_list()
        self._refresh_title()
        self._configure_scrollbar()
        self._update_epoch_readout()
        self._set_loaded(True)
        preferences.update_preferences(
            preferences_path, {"eeg_last_dir": str(path.parent)}
        )
        clock = f" · started {started.strftime('%H:%M:%S')}" if started else ""
        self.fileInfoLabel.setText(
            f"{path.name} — {len(recording.ch_names)} ch · "
            f"{recording.sfreq:g} Hz · {recording.duration:.0f} s{clock}"
        )
        self._check_for_recovery(tsv_path)

    def _fresh_annotations(
        self, path: Path, recording: io.Recording
    ) -> list[Annotation] | None:
        """Annotations to start a fresh review from; ``None`` on a read error.

        A plain review starts from the events embedded in the recording (amp
        markers, SMACC's own portcodes…). A blind review instead seeds from the
        coordinator's truth sidecar (the plain one) when it exists — so the
        blinding hides *its* marks — falling back to the embedded events, and
        runs the blind filter before anything is shown. This is the load-time
        safety invariant (#181c): the filter covers both fresh sources, so a
        naive rater never glimpses the recording's cue/portcode markers.
        """
        if self._blind is None:
            return io.embedded_annotations(recording)
        truth_tsv, _ = sidecar_paths(path)
        if truth_tsv.is_file():
            try:
                seed = read_annotations_tsv(truth_tsv)
            except (OSError, ValueError) as exc:
                self._error(
                    "Could not read the coordinator's annotations sidecar.",
                    f"{truth_tsv.name}: {exc}\n\nFix or rename it, then open the "
                    "recording again.",
                )
                return None
        else:
            seed = io.embedded_annotations(recording)
        return blind.apply_blind(seed, self._blind)

    # ----- annotation editing -----------------------------------------------------

    def _on_region_drawn(self, lo: float, hi: float) -> None:
        result = LabelDialog.get_label(self, self._recent_labels())
        if result is None:
            return
        label, instant = result
        annotation = Annotation(lo, 0.0 if instant else hi - lo, label)
        self._annotations = insert(self._annotations, annotation)
        self._remember_label(label)
        self._mark_dirty()
        self._select(self._annotations.index(annotation))

    def _add_point_mark(self, seconds: float) -> None:
        """Drop a zero-duration mark at ``seconds`` (ctrl-click or the M key).

        Goes straight to the label picker with no span to draw and no instant
        checkbox to tick — the mark is already a point.
        """
        if self._recording is None:
            return
        result = LabelDialog.get_label(self, self._recent_labels(), offer_instant=False)
        if result is None:
            return
        label, _ = result
        self._insert_point_mark(seconds, label)

    def _insert_label_at_cursor(self, label: str) -> None:
        """Drop ``label`` as a point mark at the cursor (a quick-mark button/key).

        No dialog: the label is already chosen, so a rater scoring signals places
        the mark in one action, at the last cursor time (or the view center if the
        mouse never entered the traces).
        """
        if self._recording is None:
            return
        self._insert_point_mark(self._cursor_or_center(), label)

    def _insert_point_mark(self, seconds: float, label: str) -> None:
        """Insert a clamped zero-duration mark, select it, and mark the review dirty.

        The shared tail of every point-mark path: ctrl-click/M (which prompt for a
        label first) and the quick-mark palette (which already has one).
        """
        assert self._recording is not None
        seconds = min(max(0.0, seconds), self._recording.duration)
        annotation = Annotation(seconds, 0.0, label)
        self._annotations = insert(self._annotations, annotation)
        self._remember_label(label)
        self._mark_dirty()
        self._select(self._annotations.index(annotation))

    def _cursor_or_center(self) -> float:
        """The last cursor time over the traces, or the view center if never set."""
        if self._cursor_seconds is not None:
            return self._cursor_seconds
        return self.view.window_start + self.view.window_seconds / 2

    def _mark_at_cursor(self) -> None:
        """Mark at the last cursor position, or the view's center if unknown."""
        if self._recording is None:
            return
        self._add_point_mark(self._cursor_or_center())

    def edit_selected(self) -> None:
        index = self.annotationList.currentRow()
        if not 0 <= index < len(self._annotations):
            return
        current = self._annotations[index]
        result = LabelDialog.get_label(
            self, self._recent_labels(), current.description, offer_instant=False
        )
        if result is None:
            return
        label, _ = result
        edited = Annotation(current.onset, current.duration, label)
        self._annotations = replace(self._annotations, index, edited)
        self._remember_label(label)
        self._mark_dirty()
        self._select(self._annotations.index(edited))

    def delete_selected(self) -> None:
        index = self.annotationList.currentRow()
        if not 0 <= index < len(self._annotations):
            return
        self._annotations = remove(self._annotations, index)
        self._mark_dirty()
        self._select(-1)

    def go_to_selected(self) -> None:
        """Jump the view so the selected annotation sits a quarter-window in."""
        index = self.annotationList.currentRow()
        if not 0 <= index < len(self._annotations):
            return
        onset = self._annotations[index].onset
        self._jump_to(onset - self.view.window_seconds / 4)

    def save_annotations(self) -> None:
        if self._recording is None:
            return
        # In a per-rater review, confirm the identity once before its first save,
        # so a forgotten/stale rater id is caught before it writes a file.
        if not self._confirm_rater_identity():
            return
        tsv_path, json_path = self._sidecar_for(self._recording.path)
        # Guard the one case where a save would silently clobber someone else's
        # work: a sidecar we did not open (a fresh review, or one that appeared
        # while we worked). A sidecar we loaded — or already saved — is ours.
        if not self._owns_sidecar and tsv_path.is_file():
            if not self._confirm_overwrite(tsv_path):
                return
        try:
            write_annotations_tsv(self._annotations, tsv_path)
            write_annotations_json(
                json_path,
                source_name=self._recording.path.name,
                meas_date=self._recording.meas_date,
                rater_id=self._rater_id,
            )
        except OSError as exc:
            self._error("Could not save the annotations.", str(exc))
            return
        self._dirty = False
        self._owns_sidecar = True  # ours now; later saves don't re-prompt
        self._autosave_timer.stop()
        self._clear_autosave()  # the work is persisted; no recovery needed
        self._refresh_title()
        status_bar = self.statusBar()
        assert status_bar is not None
        status_bar.showMessage(
            f"Saved {len(self._annotations)} annotations to {tsv_path.name}", 5000
        )

    def _confirm_overwrite(self, tsv_path: Path) -> bool:
        """Ask before overwriting a sidecar this review did not open."""
        button = QtWidgets.QMessageBox.question(
            self,
            "Overwrite annotations?",
            f"{tsv_path.name} already exists and was not opened in this review.\n\n"
            "Overwrite it with the current annotations?",
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
        )
        return button == QtWidgets.QMessageBox.StandardButton.Yes

    # ----- annotation bookkeeping ----------------------------------------------------

    def _mark_dirty(self) -> None:
        self._dirty = True
        self._autosave_timer.start()  # (re)arm the debounced recovery write
        self._refresh_title()

    def _select(self, index: int) -> None:
        """Sync the list widget and the view to one selected annotation.

        The row is set with signals blocked: letting currentRowChanged fire
        would rebuild the view's overlay a second time right before the
        explicit set_annotations below (and that explicit call must stay —
        deselection never fires currentRowChanged, the row is already -1
        after the blocked rebuild).
        """
        self._refresh_list()
        self.annotationList.blockSignals(True)
        self.annotationList.setCurrentRow(index)
        self.annotationList.blockSignals(False)
        self.view.set_annotations(self._annotations, index)

    def _refresh_list(self) -> None:
        self.annotationList.blockSignals(True)  # programmatic fill: not a selection
        self.annotationList.clear()
        for a in self._annotations:
            span = f"{a.onset:.3f}s" + (f" +{a.duration:.3f}s" if a.duration else "")
            self.annotationList.addItem(f"{span}  {a.description}")
        self.annotationList.blockSignals(False)

    def _refresh_title(self) -> None:
        name = f" — {self._recording.path.name}" if self._recording else ""
        rater = f" · rater {self._rater_id}" if self._rater_id else ""
        blinded = f" · blind:{self._blind.preset}" if self._blind is not None else ""
        star = " *" if self._dirty else ""
        self.setWindowTitle(f"SMACC — EEG review{name}{rater}{blinded}{star}")

    def _recent_labels(self) -> list[str]:
        prefs = preferences.load_preferences(preferences_path)
        recents = prefs.get("eeg_recent_labels")
        return [r for r in recents if isinstance(r, str)] if recents else []

    def _remember_label(self, label: str) -> None:
        recents = preferences.push_recent(
            self._recent_labels(), label, limit=_MAX_RECENT_LABELS
        )
        preferences.update_preferences(preferences_path, {"eeg_recent_labels": recents})

    # ----- autosave / crash recovery (#176) ----------------------------------------

    def _write_autosave(self) -> None:
        """Write the recovery file (best-effort, atomic); fired by the debounce timer."""
        if self._recording is None or not self._dirty:
            return
        path = self._autosave_for(self._recording.path)
        tmp = path.with_suffix(".tmp")  # write-then-rename so a crash never half-writes
        try:
            write_annotations_tsv(self._annotations, tmp)
            tmp.replace(path)
        except OSError:
            pass  # autosave must never interrupt the review

    def _clear_autosave(self) -> None:
        """Delete the active rater's recovery file for this recording, if any."""
        if self._recording is not None:
            self._autosave_for(self._recording.path).unlink(missing_ok=True)

    def _check_for_recovery(self, tsv_path: Path) -> None:
        """On open, offer to restore a recovery file newer than the saved sidecar."""
        self.recoveryBanner.setVisible(False)
        self._recovery_annotations = None
        if self._recording is None:
            return
        recovery = self._autosave_for(self._recording.path)
        if not recovery.is_file():
            return
        # A recovery file with a clean save strictly newer than it is stale — the
        # save happened after the autosave, so there is nothing left to recover.
        # Strict so a same-second tie errs toward offering recovery, never losing it.
        stale = (
            tsv_path.is_file() and tsv_path.stat().st_mtime > recovery.stat().st_mtime
        )
        if stale:
            recovery.unlink(missing_ok=True)
            return
        try:
            recovered = read_annotations_tsv(recovery)
        except (OSError, ValueError):
            return  # an unreadable recovery file must not block the open
        self._recovery_annotations = recovered
        self.recoveryLabel.setText(
            f"Recovered {len(recovered)} unsaved annotation(s) from a previous session."
        )
        self.recoveryBanner.setVisible(True)

    def _restore_autosave(self) -> None:
        if self._recovery_annotations is None:
            return
        self._annotations = self._recovery_annotations
        self._recovery_annotations = None
        self.recoveryBanner.setVisible(False)
        self.view.set_annotations(self._annotations)
        self._refresh_list()
        self._mark_dirty()  # restored but not yet saved — keep the recovery alive

    def _dismiss_autosave(self) -> None:
        self._recovery_annotations = None
        self.recoveryBanner.setVisible(False)
        self._clear_autosave()  # the user declined the recovery; drop it

    # ----- selection sync ---------------------------------------------------------

    def _on_view_selection(self, index: int) -> None:
        self.annotationList.blockSignals(True)
        self.annotationList.setCurrentRow(index)
        self.annotationList.blockSignals(False)

    def _on_list_selection(self, row: int) -> None:
        self.view.set_annotations(self._annotations, row)

    # ----- navigation / display controls ----------------------------------------------

    def _jump_to(self, seconds: float) -> None:
        self.view.set_window_start(seconds)  # the view clamps
        self._sync_scrollbar(self.view.window_start)

    def _configure_scrollbar(self) -> None:
        duration = self._recording.duration if self._recording else 0.0
        span = max(0.0, duration - self.view.window_seconds)
        self.scrollBar.blockSignals(True)
        self.scrollBar.setRange(0, int(span * _SCROLL_TICKS_PER_SECOND))
        self.scrollBar.setPageStep(
            int(self.view.window_seconds * _SCROLL_TICKS_PER_SECOND)
        )
        self.scrollBar.setValue(int(self.view.window_start * _SCROLL_TICKS_PER_SECOND))
        self.scrollBar.blockSignals(False)

    def _on_scrollbar(self, value: int) -> None:
        self.view.set_window_start(value / _SCROLL_TICKS_PER_SECOND)
        self._update_epoch_readout()

    def _sync_scrollbar(self, window_start: float) -> None:
        self.scrollBar.blockSignals(True)
        self.scrollBar.setValue(int(window_start * _SCROLL_TICKS_PER_SECOND))
        self.scrollBar.blockSignals(False)
        self._update_epoch_readout()

    def _on_window_length_changed(self) -> None:
        self.view.set_window_seconds(float(self.windowCombo.currentData()))
        self._configure_scrollbar()
        self._update_epoch_readout()

    # ----- epoch model + keyboard navigation (#173, #174) -----------------------------

    def _on_epoch_seconds_changed(self, value: int) -> None:
        self.view.set_epoch_seconds(float(value))
        self._update_epoch_readout()

    def _anchor_epochs_to_view(self) -> None:
        self.view.set_epoch_anchor(self.view.window_start)
        self._update_epoch_readout()

    def _reset_epoch_anchor(self) -> None:
        self.view.set_epoch_anchor(0.0)
        self._update_epoch_readout()

    def _update_epoch_readout(self) -> None:
        """Show the epoch number at the left edge of the view in the status bar."""
        if self._recording is None:
            self.epochLabel.clear()
            return
        number = (
            math.floor(
                (self.view.window_start - self.view.epoch_anchor)
                / self.view.epoch_seconds
            )
            + 1
        )
        self.epochLabel.setText(f"Epoch {number}")

    def eventFilter(
        self, obj: QtCore.QObject | None, event: QtCore.QEvent | None
    ) -> bool:
        """Route epoch/amplitude keys to the view regardless of which child has focus.

        Installed on the application so the keys work without first clicking the
        traces; scoped to this window being active (so a modal dialog keeps them)
        and to a recording being loaded.
        """
        if (
            isinstance(event, QtGui.QKeyEvent)
            and event.type() == QtCore.QEvent.Type.KeyPress
            and self.isActiveWindow()
            and self._recording is not None
            and (self._handle_nav_key(event) or self._handle_palette_key(event))
        ):
            return True
        return super().eventFilter(obj, event)

    def _handle_palette_key(self, event: QtGui.QKeyEvent) -> bool:
        """Drop the n-th quick mark on a bare digit 1–9; return whether consumed.

        Yields the digit to any text/number entry that has focus (so typing a
        scale or a label is never hijacked) and ignores it when a modifier other
        than the numeric keypad is held.
        """
        key = event.key()
        if not QtCore.Qt.Key.Key_1 <= key <= QtCore.Qt.Key.Key_9:
            return False
        if event.modifiers() & ~QtCore.Qt.KeyboardModifier.KeypadModifier:
            return False  # only a bare digit (keypad ok), not Ctrl/Alt/Shift+digit
        focus = QtWidgets.QApplication.focusWidget()
        if isinstance(
            focus,
            QtWidgets.QAbstractSpinBox | QtWidgets.QLineEdit | QtWidgets.QComboBox,
        ):
            return False
        index = key - QtCore.Qt.Key.Key_1
        if index >= len(self._palette_buttons):
            return False
        self._insert_label_at_cursor(self._palette_buttons[index].text())
        return True

    def _focus_wants(self, key: int) -> bool:
        """True if the focused widget should keep ``key`` for its own editing/nav.

        Text/number entry (spin box, line edit) keeps every navigation key; a
        combo box or the annotation list keeps only the vertical keys, so
        Left/Right still page epochs while the list has focus.
        """
        focus = QtWidgets.QApplication.focusWidget()
        if isinstance(focus, QtWidgets.QAbstractSpinBox | QtWidgets.QLineEdit):
            return True
        if isinstance(focus, QtWidgets.QComboBox | QtWidgets.QAbstractItemView):
            return key in _VERTICAL_NAV_KEYS
        return False

    def _handle_nav_key(self, event: QtGui.QKeyEvent) -> bool:
        """Apply one navigation/amplitude key; return whether it was consumed."""
        key = event.key()
        if key not in _NAV_KEYS or self._focus_wants(key):
            return False
        shift = bool(event.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier)
        if key in (QtCore.Qt.Key.Key_Left, QtCore.Qt.Key.Key_Right):
            sign = 1 if key == QtCore.Qt.Key.Key_Right else -1
            if shift:
                self.view.nudge_seconds(sign * _FINE_NUDGE_SECONDS)
            else:
                self.view.step_epochs(sign)
        elif key == QtCore.Qt.Key.Key_Up:
            self._nudge_scale(louder=True, fine=shift)
        elif key == QtCore.Qt.Key.Key_Down:
            self._nudge_scale(louder=False, fine=shift)
        elif key == QtCore.Qt.Key.Key_Home:
            self._jump_to(0.0)
        elif key == QtCore.Qt.Key.Key_End:
            self._jump_to(float("inf"))
        return True

    def _nudge_scale(self, *, louder: bool, fine: bool) -> None:
        """Step the amplitude through the scale spin box (louder → smaller µV/lane)."""
        factor = _SCALE_KEY_FACTOR_FINE if fine else _SCALE_KEY_FACTOR
        current = self.scaleSpin.value()
        target = current / factor if louder else current * factor
        clamped = max(self.scaleSpin.minimum(), min(self.scaleSpin.maximum(), target))
        self.scaleSpin.setValue(
            round(clamped)
        )  # drives view.set_scale, shows the value

    def _on_filters_changed(self) -> None:
        highpass = self.highpassSpin.value() or None  # 0.0 displays as "Off"
        lowpass = self.lowpassSpin.value() or None
        notch = self.notchCombo.currentData()
        try:
            spec = dsp.FilterSpec(highpass=highpass, lowpass=lowpass, notch=notch)
        except ValueError:
            # Invalid band (high-pass >= low-pass): keep the previous filter,
            # say why, and snap the controls back to it — a control left
            # showing a rejected value would silently apply the moment the
            # *other* edge moved, a filter the operator never confirmed.
            status_bar = self.statusBar()
            assert status_bar is not None
            status_bar.showMessage(
                "High-pass must stay below low-pass — filters unchanged.", 4000
            )
            applied = self._scoped_applied_spec()
            for spin, value in (
                (self.highpassSpin, applied.highpass),
                (self.lowpassSpin, applied.lowpass),
            ):
                spin.blockSignals(True)
                spin.setValue(value or 0.0)  # 0.0 displays as "Off"
                spin.blockSignals(False)
            return
        scope = self._current_scope()
        if scope is None:
            self.view.set_spec(spec)
        else:
            self.view.set_type_spec(scope, spec)

    # ----- per-type display + view profiles (#177) ------------------------------------

    def _current_scope(self) -> str | None:
        """The channel type the filter/scale controls edit (``None`` = the base)."""
        return self.filterScopeCombo.currentData()

    def _scoped_applied_spec(self) -> dsp.FilterSpec:
        scope = self._current_scope()
        return self.view.spec if scope is None else self.view.effective_spec(scope)

    def _notch_index(self, notch: float | None) -> int:
        for index in range(self.notchCombo.count()):
            if self.notchCombo.itemData(index) == notch:
                return index
        return 0

    def _populate_scope_combo(self) -> None:
        """Rebuild the per-type scope list from the loaded recording's types."""
        self.filterScopeCombo.blockSignals(True)
        self.filterScopeCombo.clear()
        self.filterScopeCombo.addItem("All channels", None)
        seen: list[str] = []
        for ch_type in self.view.channel_types:
            if ch_type not in seen:
                seen.append(ch_type)
                self.filterScopeCombo.addItem(ch_type.upper(), ch_type)
        self.filterScopeCombo.setCurrentIndex(0)
        self.filterScopeCombo.blockSignals(False)

    def _load_scope_into_controls(self) -> None:
        """Show the current scope's filter + scale in the controls (no signals)."""
        scope = self._current_scope()
        spec = self.view.spec if scope is None else self.view.effective_spec(scope)
        scale = (
            self.view.scale_uv if scope is None else self.view.effective_scale(scope)
        )
        for spin, value in (
            (self.highpassSpin, spec.highpass),
            (self.lowpassSpin, spec.lowpass),
        ):
            spin.blockSignals(True)
            spin.setValue(value or 0.0)  # 0.0 displays as "Off"
            spin.blockSignals(False)
        self.notchCombo.blockSignals(True)
        self.notchCombo.setCurrentIndex(self._notch_index(spec.notch))
        self.notchCombo.blockSignals(False)
        self.scaleSpin.blockSignals(True)
        self.scaleSpin.setValue(scale)
        self.scaleSpin.blockSignals(False)

    def _on_scope_changed(self) -> None:
        self._load_scope_into_controls()

    def _on_scale_changed(self, value: float) -> None:
        scope = self._current_scope()
        if scope is None:
            self.view.set_scale(float(value))
        else:
            self.view.set_type_scale(scope, float(value))

    def _open_channel_picker(self) -> None:
        if self._recording is None:
            return
        result = ChannelPickerDialog.get_visible(
            self, self.view.channel_names, self.view.visible_indices
        )
        if result is not None:
            self.view.set_visible_channels(result)

    def _current_profile(self) -> ViewProfile:
        """Capture the current montage as a profile."""
        return ViewProfile(
            channels=tuple(self.view.visible_channels),
            base_scale_uv=self.view.scale_uv,
            type_scales=self.view.type_scales(),
            base_filter=self.view.spec,
            type_filters=self.view.type_specs(),
            window_seconds=self.view.window_seconds,
            epoch_seconds=self.view.epoch_seconds,
        )

    def _apply_profile(self, profile: ViewProfile) -> None:
        """Apply a saved montage; channels are matched by name (missing skipped)."""
        names = self.view.channel_names
        if profile.channels:
            index_of = {name: i for i, name in enumerate(names)}
            indices = [index_of[name] for name in profile.channels if name in index_of]
            self.view.set_visible_channels(indices or list(range(len(names))))
        else:
            self.view.set_visible_channels(list(range(len(names))))
        self.view.set_scale(profile.base_scale_uv)
        self.view.set_type_scales(profile.type_scales)
        self.view.set_spec(profile.base_filter)
        self.view.set_type_specs(profile.type_filters)
        self._select_window_seconds(profile.window_seconds)
        self.epochSpin.setValue(int(profile.epoch_seconds))  # drives the view
        self._populate_scope_combo()
        self._load_scope_into_controls()
        self._update_epoch_readout()

    def _select_window_seconds(self, seconds: float) -> None:
        options = [float(s) for s in WINDOW_LENGTHS]
        if seconds in options:
            self.windowCombo.setCurrentIndex(options.index(seconds))  # drives the view
        else:
            self.view.set_window_seconds(seconds)
            self._configure_scrollbar()

    def _save_profile(self) -> None:
        if self._recording is None:
            return
        prefs = preferences.load_preferences(preferences_path)
        start_dir = prefs.get("eeg_last_profile_dir") or str(
            self._recording.path.parent
        )
        default = str(Path(start_dir) / f"montage{PROFILE_SUFFIX}")
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save view profile", default, PROFILE_FILE_FILTER
        )
        if not path:
            return
        target = Path(path)
        if target.suffix != ".json":  # the dialog may drop the compound suffix
            target = target.with_name(target.name + PROFILE_SUFFIX)
        try:
            write_view_profile(self._current_profile(), target)
        except OSError as exc:
            self._error("Could not save the view profile.", str(exc))
            return
        preferences.update_preferences(
            preferences_path, {"eeg_last_profile_dir": str(target.parent)}
        )
        status_bar = self.statusBar()
        assert status_bar is not None
        status_bar.showMessage(f"Saved view profile to {target.name}", 5000)

    def _load_profile(self) -> None:
        if self._recording is None:
            return
        prefs = preferences.load_preferences(preferences_path)
        start_dir = prefs.get("eeg_last_profile_dir") or str(
            self._recording.path.parent
        )
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load view profile", str(start_dir), PROFILE_FILE_FILTER
        )
        if not path:
            return
        try:
            profile = read_view_profile(path)
        except (OSError, ValueError) as exc:
            self._error("Could not read the view profile.", str(exc))
            return
        self._apply_profile(profile)
        preferences.update_preferences(
            preferences_path, {"eeg_last_profile_dir": str(Path(path).parent)}
        )
        status_bar = self.statusBar()
        assert status_bar is not None
        status_bar.showMessage(f"Applied view profile {Path(path).name}", 5000)

    def _export_figure(self) -> None:
        if self._recording is None or not self.view.visible_indices:
            return
        lo = self.view.window_start
        hi = lo + self.view.window_seconds
        in_window = [
            (a.onset, a.duration, a.description)
            for a in self._annotations
            if not (a.onset + a.duration < lo or a.onset > hi)
        ]
        result = ExportDialog.get_export(
            self, self.view.channel_names, self.view.visible_indices, in_window
        )
        if result is None:
            return
        options, marks, channels = result
        if channels is not None:  # the dialog's picker also updates the live view
            self.view.set_visible_channels(channels)
        from . import export  # lazy: matplotlib is heavy and only needed here

        snapshot = self.view.build_snapshot(
            marks=marks, show_epochs=options.show_epoch_grid
        )
        path = self._ask_export_path(options.fmt)
        if path is None:
            return
        try:
            export.render(snapshot, options, path)
        except (OSError, ValueError) as exc:
            self._error("Could not export the figure.", str(exc))
            return
        status_bar = self.statusBar()
        assert status_bar is not None
        status_bar.showMessage(f"Exported {path.name}", 5000)

    def _ask_export_path(self, fmt: str) -> Path | None:
        """Prompt for the figure path (remembering the folder); ``None`` on cancel."""
        assert self._recording is not None
        prefs = preferences.load_preferences(preferences_path)
        start_dir = prefs.get("eeg_last_export_dir") or str(self._recording.path.parent)
        default = str(Path(start_dir) / f"{self._recording.path.stem}.{fmt}")
        chosen, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export figure", default, f"{fmt.upper()} (*.{fmt})"
        )
        if not chosen:
            return None
        target = Path(chosen)
        if target.suffix.lower() != f".{fmt}":
            target = target.with_name(f"{target.name}.{fmt}")
        preferences.update_preferences(
            preferences_path, {"eeg_last_export_dir": str(target.parent)}
        )
        return target

    def _on_cursor_moved(self, seconds: float) -> None:
        if self._recording is None:
            return
        self._cursor_seconds = seconds  # remembered for the M (mark) shortcut
        text = f"t = {seconds:.3f} s"
        clock = wall_time(self._recording, seconds) if seconds >= 0 else None
        if clock is not None:
            text += f" · {clock.strftime('%H:%M:%S')}"
        status_bar = self.statusBar()
        assert status_bar is not None
        status_bar.showMessage(text)

    # ----- helpers / lifecycle -------------------------------------------------------

    def _confirm_discard(self) -> bool:
        """True when it's safe to drop the current annotations (saved or confirmed)."""
        if not self._dirty:
            return True
        button = QtWidgets.QMessageBox.question(
            self,
            "Unsaved annotations",
            "Save the annotations before closing this recording?",
            QtWidgets.QMessageBox.StandardButton.Save
            | QtWidgets.QMessageBox.StandardButton.Discard
            | QtWidgets.QMessageBox.StandardButton.Cancel,
        )
        if button == QtWidgets.QMessageBox.StandardButton.Save:
            self.save_annotations()
            return not self._dirty  # a failed save keeps the recording open
        return button == QtWidgets.QMessageBox.StandardButton.Discard

    def _error(self, short: str, detail: str | None = None) -> None:
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        box.setWindowTitle("EEG review")
        box.setText(short)
        if detail is not None:
            box.setInformativeText(detail)
        box.exec()

    def closeEvent(self, event: QtGui.QCloseEvent | None) -> None:
        if not self._confirm_discard():
            if event is not None:
                event.ignore()
            return
        # Closing cleanly (saved or discarded): there is no unsaved work to
        # recover, so drop the recovery file and stop the autosave timer.
        self._autosave_timer.stop()
        self._clear_autosave()
        # Drop the app-level key filter before this window goes away, so a stray
        # late event can never reach a half-deleted window.
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        # Remember where this window sat for next launch (best-effort, never raises).
        preferences.update_window_geometry(
            preferences_path, _EEG_WINDOW_ID, windowstate.geometry_of(self)
        )
        if event is not None:
            event.accept()
