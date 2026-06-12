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

from PyQt6 import QtCore, QtGui, QtWidgets

from .. import preferences, windowstate
from ..paths import LOGO_PATH, preferences_path
from . import dsp, io
from .annotations import (
    Annotation,
    autosave_path,
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


class EegReviewWindow(QtWidgets.QMainWindow):
    """Review and annotate one recording; the EEG component's main window."""

    def __init__(self, file_path: str | Path | None = None) -> None:
        super().__init__()
        self._recording: io.Recording | None = None
        self._annotations: list[Annotation] = []
        self._dirty = False
        self._cursor_seconds: float | None = None  # last mouse time over the traces
        # True once this review's annotations live in the canonical sidecar (we
        # loaded it, or we have saved at least once); gates the overwrite prompt.
        self._owns_sidecar = False
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
        layout.addWidget(self._build_contract_caption())
        layout.addWidget(self._build_recovery_banner())
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
        # Opened cleanly: stop autosaving the recording we're leaving and drop its
        # recovery file (the user already saved or discarded it via open_file).
        self._autosave_timer.stop()
        self._clear_autosave()
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

    # ----- autosave / crash recovery (#176) ----------------------------------------

    def _write_autosave(self) -> None:
        """Write the recovery file (best-effort, atomic); fired by the debounce timer."""
        if self._recording is None or not self._dirty:
            return
        path = autosave_path(self._recording.path)
        tmp = path.with_suffix(".tmp")  # write-then-rename so a crash never half-writes
        try:
            write_annotations_tsv(self._annotations, tmp)
            tmp.replace(path)
        except OSError:
            pass  # autosave must never interrupt the review

    def _clear_autosave(self) -> None:
        """Delete the current recording's recovery file, if any."""
        if self._recording is not None:
            autosave_path(self._recording.path).unlink(missing_ok=True)

    def _check_for_recovery(self, tsv_path: Path) -> None:
        """On open, offer to restore a recovery file newer than the saved sidecar."""
        self.recoveryBanner.setVisible(False)
        self._recovery_annotations = None
        if self._recording is None:
            return
        recovery = autosave_path(self._recording.path)
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
            and self._handle_nav_key(event)
        ):
            return True
        return super().eventFilter(obj, event)

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
