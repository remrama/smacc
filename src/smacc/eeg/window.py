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

from datetime import datetime, timedelta
from pathlib import Path

from PyQt6 import QtCore, QtGui, QtWidgets

from .. import preferences, windowstate
from ..paths import LOGO_PATH, preferences_path
from . import dsp, io
from .annotations import (
    Annotation,
    insert,
    read_annotations_tsv,
    remove,
    replace,
    sidecar_paths,
    write_annotations_json,
    write_annotations_tsv,
)
from .view import DEFAULT_EPOCH_SECONDS, TraceView

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


class EegReviewWindow(QtWidgets.QMainWindow):
    """Review and annotate one recording; the EEG component's main window."""

    def __init__(self, file_path: str | Path | None = None) -> None:
        super().__init__()
        self._recording: io.Recording | None = None
        self._annotations: list[Annotation] = []
        self._dirty = False
        self._cursor_seconds: float | None = None  # last mouse time over the traces
        self.setWindowTitle("SMACC — EEG review")
        if LOGO_PATH.is_file():
            self.setWindowIcon(QtGui.QIcon(str(LOGO_PATH)))
        self._build()
        self._set_loaded(False)
        if file_path is not None:
            # After the event loop starts, so the window is up before any
            # open-error dialog (and a long load doesn't block the first paint).
            QtCore.QTimer.singleShot(0, lambda: self._load(Path(file_path)))

    # ----- UI construction ----------------------------------------------------

    def _build(self) -> None:
        central = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)
        layout.addWidget(_section_title("EEG review"))
        layout.addLayout(self._build_controls_row())
        layout.addLayout(self._build_epoch_row())

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
        # Permanent (right-aligned) recording summary; transient messages and
        # the cursor clock use the normal message area.
        self.fileInfoLabel = QtWidgets.QLabel("", self)
        status_bar = self.statusBar()
        assert status_bar is not None
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
        self.scaleSpin.valueChanged.connect(
            lambda value: self.view.set_scale(float(value))
        )
        row.addWidget(self.scaleSpin)

        row.addStretch(1)
        self.saveButton = QtWidgets.QPushButton("Save annotations", self)
        self.saveButton.setStatusTip(
            "Write the annotations TSV/JSON sidecar next to the recording."
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
        self.epochSpin.valueChanged.connect(
            lambda value: self.view.set_epoch_seconds(float(value))
        )
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
        self.anchorButton.clicked.connect(
            lambda: self.view.set_epoch_anchor(self.view.window_start)
        )
        row.addWidget(self.anchorButton)
        self.resetAnchorButton = QtWidgets.QPushButton("Reset anchor", self)
        self.resetAnchorButton.setStatusTip(
            "Put epoch 1 back at the start of the recording."
        )
        self.resetAnchorButton.clicked.connect(lambda: self.view.set_epoch_anchor(0.0))
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
        return row

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
        """Window-wide paging on PageUp/PageDown only.

        Arrows and Home/End live on the TraceView itself (click the traces,
        then navigate): as window shortcuts they would be consumed by whichever
        spin box or list last had focus. No text widget steals PageUp/Down, so
        paging works from anywhere.
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
        ):
            widget.setEnabled(loaded)

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
        try:
            recording = io.open_recording(path)
        except (ValueError, OSError, RuntimeError) as exc:
            self._error("Could not open the recording.", str(exc))
            return
        tsv_path, _ = sidecar_paths(path)
        if tsv_path.is_file():
            # Resume a previous review. A sidecar that exists but won't parse
            # aborts the open: it is the reviewer's data, and proceeding would
            # overwrite it with an empty list on the next save.
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
            # A fresh review starts from the events embedded in the recording
            # (amp markers, SMACC's own portcodes…), so they end up in the
            # sidecar alongside the reviewer's marks.
            annotations = io.embedded_annotations(recording)
        self._recording = recording
        self._annotations = annotations
        self._dirty = False
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
        self._refresh_list()
        self._refresh_title()
        self._configure_scrollbar()
        self._set_loaded(True)
        preferences.update_preferences(
            preferences_path, {"eeg_last_dir": str(path.parent)}
        )
        clock = f" · started {started.strftime('%H:%M:%S')}" if started else ""
        self.fileInfoLabel.setText(
            f"{path.name} — {len(recording.ch_names)} ch · "
            f"{recording.sfreq:g} Hz · {recording.duration:.0f} s{clock}"
        )

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
        seconds = min(max(0.0, seconds), self._recording.duration)
        result = LabelDialog.get_label(self, self._recent_labels(), offer_instant=False)
        if result is None:
            return
        label, _ = result
        annotation = Annotation(seconds, 0.0, label)
        self._annotations = insert(self._annotations, annotation)
        self._remember_label(label)
        self._mark_dirty()
        self._select(self._annotations.index(annotation))

    def _mark_at_cursor(self) -> None:
        """Mark at the last cursor position, or the view's center if unknown."""
        if self._recording is None:
            return
        seconds = self._cursor_seconds
        if seconds is None:  # the mouse never entered the traces
            seconds = self.view.window_start + self.view.window_seconds / 2
        self._add_point_mark(seconds)

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
        tsv_path, json_path = sidecar_paths(self._recording.path)
        try:
            write_annotations_tsv(self._annotations, tsv_path)
            write_annotations_json(
                json_path,
                source_name=self._recording.path.name,
                meas_date=self._recording.meas_date,
            )
        except OSError as exc:
            self._error("Could not save the annotations.", str(exc))
            return
        self._dirty = False
        self._refresh_title()
        status_bar = self.statusBar()
        assert status_bar is not None
        status_bar.showMessage(
            f"Saved {len(self._annotations)} annotations to {tsv_path.name}", 5000
        )

    # ----- annotation bookkeeping ----------------------------------------------------

    def _mark_dirty(self) -> None:
        self._dirty = True
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
        star = " *" if self._dirty else ""
        self.setWindowTitle(f"SMACC — EEG review{name}{star}")

    def _recent_labels(self) -> list[str]:
        prefs = preferences.load_preferences(preferences_path)
        recents = prefs.get("eeg_recent_labels")
        return [r for r in recents if isinstance(r, str)] if recents else []

    def _remember_label(self, label: str) -> None:
        recents = preferences.push_recent(
            self._recent_labels(), label, limit=_MAX_RECENT_LABELS
        )
        preferences.update_preferences(preferences_path, {"eeg_recent_labels": recents})

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

    def _sync_scrollbar(self, window_start: float) -> None:
        self.scrollBar.blockSignals(True)
        self.scrollBar.setValue(int(window_start * _SCROLL_TICKS_PER_SECOND))
        self.scrollBar.blockSignals(False)

    def _on_window_length_changed(self) -> None:
        self.view.set_window_seconds(float(self.windowCombo.currentData()))
        self._configure_scrollbar()

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
            applied = self.view._spec
            for spin, value in (
                (self.highpassSpin, applied.highpass),
                (self.lowpassSpin, applied.lowpass),
            ):
                spin.blockSignals(True)
                spin.setValue(value or 0.0)  # 0.0 displays as "Off"
                spin.blockSignals(False)
            return
        self.view.set_spec(spec)

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
        # Remember where this window sat for next launch (best-effort, never raises).
        preferences.update_window_geometry(
            preferences_path, _EEG_WINDOW_ID, windowstate.geometry_of(self)
        )
        if event is not None:
            event.accept()
