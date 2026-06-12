"""Tests for the EEG review window (#136) — offscreen, no MNE.

``io.open_recording``/``io.embedded_annotations`` are monkeypatched with a
fake recording, so the window's whole flow — open, sidecar precedence,
annotate, edit, delete, save, dirty/close — runs without the eeg extra.
Preferences are pointed at a temp file (the launcher-test pattern) so no test
touches the machine's real ``preferences.yaml``.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime, timedelta
from importlib.util import find_spec
from pathlib import Path

import numpy as np
import pytest
from PyQt6 import QtCore, QtGui, QtWidgets

from smacc import preferences
from smacc.config import VERSION
from smacc.eeg import dsp
from smacc.eeg import window as window_mod
from smacc.eeg.__main__ import pick_recording_path
from smacc.eeg.annotations import (
    Annotation,
    read_annotations_tsv,
    sidecar_paths,
    write_annotations_tsv,
)
from smacc.eeg.window import SEED_LABELS, EegReviewWindow, LabelDialog

SFREQ = 100.0
DURATION = 600.0
MEAS_DATE = datetime(2026, 6, 5, 22, 0, 0, tzinfo=UTC)


class FakeRecording:
    """Stands in for io.Recording: metadata plus constant slices."""

    ch_names = ["C3", "C4", "EOG", "EMG"]
    ch_types = ["eeg", "eeg", "eog", "emg"]
    sfreq = SFREQ
    duration = DURATION
    meas_date = MEAS_DATE

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def get_slice(self, start_s: float, stop_s: float):
        start = max(0, int(round(max(0.0, start_s) * SFREQ)))
        stop = min(int(DURATION * SFREQ), int(round(min(DURATION, stop_s) * SFREQ)))
        n = max(0, stop - start)
        return (start + np.arange(n)) / SFREQ, np.zeros((4, n))


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    """An EegReviewWindow over faked IO, isolated prefs, and silent dialogs."""
    monkeypatch.setattr(window_mod, "preferences_path", tmp_path / "prefs.yaml")
    monkeypatch.setattr(window_mod.io, "open_recording", FakeRecording)
    monkeypatch.setattr(window_mod.io, "embedded_annotations", lambda rec: [])
    # Tests routinely leave unsaved annotations, and pytest-qt closes added
    # widgets in its runtest-teardown hook — *before* fixture cleanup could
    # reset any state — so a dirty close would raise a real (blocking)
    # Save/Discard/Cancel prompt with no event loop to answer it and hang the
    # offscreen suite. Default the prompt to Discard; the close-flow tests
    # re-patch it to exercise the other answers.
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "question",
        lambda *a, **k: QtWidgets.QMessageBox.StandardButton.Discard,
    )
    win = EegReviewWindow()
    qtbot.addWidget(win)
    win.show()
    win._prefs_path = tmp_path / "prefs.yaml"  # test convenience handle
    return win


@pytest.fixture
def recording_path(tmp_path):
    path = tmp_path / "night1.edf"
    path.write_bytes(b"")  # only the name matters; IO is faked
    return path


def _answer_label(monkeypatch, answer):
    """Make the label dialog answer without exec()-ing (None = cancelled)."""
    monkeypatch.setattr(
        window_mod.LabelDialog, "get_label", staticmethod(lambda *a, **k: answer)
    )


# ----- opening ------------------------------------------------------------------


def test_loading_enables_the_window_and_shows_the_file(window, recording_path):
    assert not window.saveButton.isEnabled()  # nothing loaded yet
    window._load(recording_path)
    assert window.saveButton.isEnabled()
    assert "night1.edf" in window.windowTitle()
    assert "4 ch" in window.fileInfoLabel.text()
    assert "22:00:00" in window.fileInfoLabel.text()  # meas_date clock
    # 600 s file, 30 s window, tenth-of-a-second ticks.
    assert window.scrollBar.maximum() == int((DURATION - 30) * 10)


def test_fresh_review_seeds_from_embedded_events(window, recording_path, monkeypatch):
    embedded = [Annotation(1.0, 0.0, "Cue started: Piano")]
    monkeypatch.setattr(window_mod.io, "embedded_annotations", lambda rec: embedded)
    window._load(recording_path)
    assert window._annotations == embedded
    assert not window._dirty  # imported events aren't user edits
    assert window.annotationList.count() == 1


def test_existing_sidecar_wins_over_embedded_events(
    window, recording_path, monkeypatch
):
    # Re-importing embedded events on every open would duplicate them into the
    # sidecar; once a sidecar exists it is the single source of truth.
    saved = [Annotation(5.0, 2.0, "REM period")]
    tsv_path, _ = sidecar_paths(recording_path)
    write_annotations_tsv(saved, tsv_path)
    monkeypatch.setattr(
        window_mod.io,
        "embedded_annotations",
        lambda rec: pytest.fail("embedded events must not be imported"),
    )
    window._load(recording_path)
    assert window._annotations == saved


def test_corrupt_sidecar_aborts_the_open(window, recording_path, silence_dialogs):
    # The sidecar is the reviewer's data: loading with an empty list would
    # overwrite it on the next save, so the open must refuse instead.
    tsv_path, _ = sidecar_paths(recording_path)
    tsv_path.write_text("not\ta\tsidecar\n", encoding="utf-8")
    window._load(recording_path)
    assert window._recording is None
    assert not window.saveButton.isEnabled()


# ----- annotating -----------------------------------------------------------------


def test_drawn_region_becomes_a_labeled_annotation(window, recording_path, monkeypatch):
    window._load(recording_path)
    _answer_label(monkeypatch, ("LRLR", False))
    window._on_region_drawn(10.0, 14.0)
    assert window._annotations == [Annotation(10.0, 4.0, "LRLR")]
    assert window._dirty
    assert window.windowTitle().endswith("*")
    # The label lands in the recents that seed the next dialog.
    prefs = preferences.load_preferences(window._prefs_path)
    assert prefs["eeg_recent_labels"] == ["LRLR"]


def test_instant_checkbox_drops_the_drawn_duration(window, recording_path, monkeypatch):
    window._load(recording_path)
    _answer_label(monkeypatch, ("LRLR", True))
    window._on_region_drawn(10.0, 14.0)
    assert window._annotations == [Annotation(10.0, 0.0, "LRLR")]


def test_cancelled_label_dialog_adds_nothing(window, recording_path, monkeypatch):
    window._load(recording_path)
    _answer_label(monkeypatch, None)
    window._on_region_drawn(10.0, 14.0)
    assert window._annotations == []
    assert not window._dirty


def test_edit_renames_but_keeps_the_span(window, recording_path, monkeypatch):
    window._load(recording_path)
    _answer_label(monkeypatch, ("Arousal", False))
    window._on_region_drawn(10.0, 14.0)
    window.annotationList.setCurrentRow(0)
    _answer_label(monkeypatch, ("Artifact", False))
    window.edit_selected()
    assert window._annotations == [Annotation(10.0, 4.0, "Artifact")]


def test_delete_removes_the_selected_annotation(window, recording_path, monkeypatch):
    window._load(recording_path)
    _answer_label(monkeypatch, ("Arousal", False))
    window._on_region_drawn(10.0, 14.0)
    window.annotationList.setCurrentRow(0)
    window.delete_selected()
    assert window._annotations == []
    assert window._dirty


def test_go_to_selected_jumps_the_view(window, recording_path, monkeypatch):
    window._load(recording_path)
    _answer_label(monkeypatch, ("Arousal", False))
    window._on_region_drawn(50.0, 51.0)
    window.annotationList.setCurrentRow(0)
    window.go_to_selected()
    # A quarter-window of lead-in before the annotation (30 s window).
    assert window.view.window_start == pytest.approx(50.0 - 7.5)


def test_ctrl_click_path_adds_a_point_mark(window, recording_path, monkeypatch):
    window._load(recording_path)
    _answer_label(monkeypatch, ("LRLR", False))
    window.view.pointMarkRequested.emit(42.0)  # the ctrl-click signal
    assert window._annotations == [Annotation(42.0, 0.0, "LRLR")]
    assert window._dirty


def test_mark_key_marks_at_the_last_cursor_position(
    window, recording_path, monkeypatch
):
    window._load(recording_path)
    window._on_cursor_moved(33.0)  # remember where the cursor is
    _answer_label(monkeypatch, ("LRLR", False))
    window._mark_at_cursor()
    assert window._annotations == [Annotation(33.0, 0.0, "LRLR")]


def test_mark_key_falls_back_to_the_view_center(window, recording_path, monkeypatch):
    window._load(recording_path)  # cursor never moved; window 0–30 → center 15
    _answer_label(monkeypatch, ("LRLR", False))
    window._mark_at_cursor()
    assert window._annotations == [Annotation(15.0, 0.0, "LRLR")]


# ----- saving and closing -----------------------------------------------------------


def test_save_writes_both_sidecars_and_clears_dirty(
    window, recording_path, monkeypatch
):
    window._load(recording_path)
    _answer_label(monkeypatch, ("LRLR", False))
    window._on_region_drawn(10.0, 14.0)
    window.save_annotations()
    tsv_path, json_path = sidecar_paths(recording_path)
    assert read_annotations_tsv(tsv_path) == [Annotation(10.0, 4.0, "LRLR")]
    assert json_path.is_file()
    assert not window._dirty
    assert not window.windowTitle().endswith("*")


def test_dirty_close_can_be_cancelled(window, recording_path, monkeypatch):
    window._load(recording_path)
    _answer_label(monkeypatch, ("LRLR", False))
    window._on_region_drawn(10.0, 14.0)
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "question",
        lambda *a, **k: QtWidgets.QMessageBox.StandardButton.Cancel,
    )
    assert not window.close()
    assert window.isVisible()
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "question",
        lambda *a, **k: QtWidgets.QMessageBox.StandardButton.Discard,
    )
    assert window.close()


def test_clean_close_needs_no_prompt(window, recording_path, monkeypatch):
    window._load(recording_path)
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "question",
        lambda *a, **k: pytest.fail("no prompt expected on a clean close"),
    )
    assert window.close()


# ----- display controls ----------------------------------------------------------------


def test_filter_controls_build_the_spec(window, recording_path):
    window._load(recording_path)
    window.highpassSpin.setValue(0.3)
    window.lowpassSpin.setValue(35.0)
    window.notchCombo.setCurrentIndex(2)  # 60 Hz
    assert window.view._spec == dsp.FilterSpec(highpass=0.3, lowpass=35.0, notch=60.0)


def test_inverted_band_is_rejected_and_filters_kept(window, recording_path):
    window._load(recording_path)
    window.highpassSpin.setValue(0.3)
    window.lowpassSpin.setValue(35.0)
    window.highpassSpin.setValue(40.0)  # above the low-pass: must not apply
    assert window.view._spec.highpass == 0.3


def test_window_length_change_reconfigures_the_scrollbar(window, recording_path):
    window._load(recording_path)
    window.windowCombo.setCurrentIndex(3)  # 120 s
    assert window.view.window_seconds == 120.0
    assert window.scrollBar.maximum() == int((DURATION - 120) * 10)
    assert window.scrollBar.pageStep() == 1200


def test_scrollbar_moves_the_view_and_back(window, recording_path):
    window._load(recording_path)
    window.scrollBar.setValue(450)  # 45.0 s
    assert window.view.window_start == pytest.approx(45.0)
    window.view.scroll_by(1.0)  # keyboard/wheel path reports back
    assert window.scrollBar.value() == 750


def test_cursor_readout_shows_data_and_clock_time(window, recording_path):
    window._load(recording_path)
    window._on_cursor_moved(90.0)
    status_bar = window.statusBar()
    assert status_bar is not None
    message = status_bar.currentMessage()
    assert "t = 90.000 s" in message
    assert "22:01:30" in message  # 22:00:00 meas_date + 90 s, amp wall clock


# ----- epoch model (#173) ----------------------------------------------------------


def test_epoch_spin_sets_the_epoch_length(window, recording_path):
    window._load(recording_path)
    window.epochSpin.setValue(20)
    assert window.view.epoch_seconds == 20.0


def test_time_axis_defaults_to_clock_when_the_file_has_a_start(window, recording_path):
    window._load(recording_path)  # FakeRecording carries a meas_date
    assert window.axisModeCombo.currentData() == "clock"
    assert window.view._time_axis._mode == "clock"


def test_time_axis_defaults_to_elapsed_without_a_start(
    window, recording_path, monkeypatch
):
    def no_date(path):
        rec = FakeRecording(path)
        rec.meas_date = None  # anonymized: only elapsed/epoch time is meaningful
        return rec

    monkeypatch.setattr(window_mod.io, "open_recording", no_date)
    window._load(recording_path)
    assert window.axisModeCombo.currentData() == "elapsed"
    assert window.view._time_axis._mode == "elapsed"


def test_anchor_button_anchors_epochs_to_the_view(window, recording_path):
    window._load(recording_path)
    window.scrollBar.setValue(450)  # 45.0 s
    assert window.view.window_start == pytest.approx(45.0)
    window.anchorButton.click()
    assert window.view.epoch_anchor == pytest.approx(45.0)
    window.resetAnchorButton.click()  # back to the start of the recording
    assert window.view.epoch_anchor == 0.0


# ----- keyboard navigation (#174) --------------------------------------------------


def _key(key, *, shift=False):
    mods = (
        QtCore.Qt.KeyboardModifier.ShiftModifier
        if shift
        else QtCore.Qt.KeyboardModifier.NoModifier
    )
    return QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, key, mods)


@pytest.fixture
def nav_window(window, recording_path, monkeypatch):
    """A loaded window with focus pinned to nothing, so the key filter acts."""
    window._load(recording_path)
    monkeypatch.setattr(
        QtWidgets.QApplication, "focusWidget", staticmethod(lambda: None)
    )
    return window


def test_left_right_arrows_page_by_one_epoch(nav_window):
    window = nav_window  # 30 s epochs by default
    assert window._handle_nav_key(_key(QtCore.Qt.Key.Key_Right)) is True
    assert window.view.window_start == pytest.approx(30.0)
    window._handle_nav_key(_key(QtCore.Qt.Key.Key_Left))
    assert window.view.window_start == pytest.approx(0.0)


def test_shift_arrows_nudge_finely(nav_window):
    nav_window._handle_nav_key(_key(QtCore.Qt.Key.Key_Right, shift=True))
    assert nav_window.view.window_start == pytest.approx(1.0)  # a 1 s fine nudge


def test_up_down_arrows_step_the_amplitude(nav_window):
    window = nav_window
    window.scaleSpin.setValue(100)
    window._handle_nav_key(_key(QtCore.Qt.Key.Key_Up))  # louder → smaller µV/lane
    assert window.scaleSpin.value() == 80  # 100 / 1.25
    window._handle_nav_key(_key(QtCore.Qt.Key.Key_Down))
    assert window.scaleSpin.value() == 100  # 80 * 1.25


def test_shift_up_down_step_the_amplitude_finely(nav_window):
    window = nav_window
    window.scaleSpin.setValue(100)
    window._handle_nav_key(_key(QtCore.Qt.Key.Key_Up, shift=True))
    assert window.scaleSpin.value() == 91  # round(100 / 1.1)


def test_home_and_end_jump_to_the_edges(nav_window):
    window = nav_window
    window._handle_nav_key(_key(QtCore.Qt.Key.Key_End))
    span = DURATION - window.view.window_seconds
    assert window.view.window_start == pytest.approx(span)
    window._handle_nav_key(_key(QtCore.Qt.Key.Key_Home))
    assert window.view.window_start == 0.0


def test_epoch_readout_tracks_the_current_epoch(nav_window):
    window = nav_window
    assert window.epochLabel.text() == "Epoch 1"
    window._handle_nav_key(_key(QtCore.Qt.Key.Key_Right))  # to 30 s → epoch 2
    assert window.epochLabel.text() == "Epoch 2"


def test_a_focused_spinbox_keeps_its_arrow_keys(window, recording_path, monkeypatch):
    window._load(recording_path)
    monkeypatch.setattr(
        QtWidgets.QApplication, "focusWidget", staticmethod(lambda: window.scaleSpin)
    )
    assert window._handle_nav_key(_key(QtCore.Qt.Key.Key_Right)) is False
    assert window.view.window_start == 0.0  # the spin box kept the key


def test_a_focused_list_keeps_up_down_but_yields_left_right(
    window, recording_path, monkeypatch
):
    window._load(recording_path)
    monkeypatch.setattr(
        QtWidgets.QApplication,
        "focusWidget",
        staticmethod(lambda: window.annotationList),
    )
    assert window._handle_nav_key(_key(QtCore.Qt.Key.Key_Down)) is False  # row nav
    assert window._handle_nav_key(_key(QtCore.Qt.Key.Key_Right)) is True  # still pages


def test_event_filter_routes_keys_only_when_active(
    window, recording_path, monkeypatch
):
    window._load(recording_path)
    monkeypatch.setattr(
        QtWidgets.QApplication, "focusWidget", staticmethod(lambda: None)
    )
    monkeypatch.setattr(window, "isActiveWindow", lambda: False)
    assert window.eventFilter(window, _key(QtCore.Qt.Key.Key_Right)) is False
    assert window.view.window_start == 0.0  # inactive: the key is left alone
    monkeypatch.setattr(window, "isActiveWindow", lambda: True)
    assert window.eventFilter(window, _key(QtCore.Qt.Key.Key_Right)) is True
    assert window.view.window_start == pytest.approx(30.0)


# ----- save safety (#175) ----------------------------------------------------------


def test_save_button_states_the_no_modify_contract(window):
    assert "never modified" in window.saveButton.toolTip()


def test_fresh_save_with_no_existing_sidecar_does_not_prompt(
    window, recording_path, monkeypatch
):
    window._load(recording_path)  # fresh review, no sidecar on disk yet
    _answer_label(monkeypatch, ("LRLR", False))
    window._on_region_drawn(10.0, 14.0)
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "question",
        lambda *a, **k: pytest.fail("no prompt when nothing is overwritten"),
    )
    window.save_annotations()
    assert not window._dirty


def test_resuming_a_sidecar_saves_without_a_prompt(window, recording_path, monkeypatch):
    tsv_path, _ = sidecar_paths(recording_path)
    write_annotations_tsv([Annotation(5.0, 2.0, "REM period")], tsv_path)
    window._load(recording_path)  # loaded from it → we own it
    _answer_label(monkeypatch, ("LRLR", False))
    window._on_region_drawn(10.0, 14.0)
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "question",
        lambda *a, **k: pytest.fail("no overwrite prompt when resuming our own sidecar"),
    )
    window.save_annotations()
    assert not window._dirty


def test_save_prompts_before_overwriting_a_foreign_sidecar(
    window, recording_path, monkeypatch
):
    window._load(recording_path)  # fresh review (we do not own a sidecar)
    _answer_label(monkeypatch, ("LRLR", False))
    window._on_region_drawn(10.0, 14.0)
    tsv_path, _ = sidecar_paths(recording_path)
    foreign = [Annotation(1.0, 0.0, "other rater")]
    write_annotations_tsv(foreign, tsv_path)  # a sidecar appeared meanwhile
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "question",
        lambda *a, **k: QtWidgets.QMessageBox.StandardButton.No,
    )
    window.save_annotations()
    assert read_annotations_tsv(tsv_path) == foreign  # declined: left untouched
    assert window._dirty  # still unsaved


def test_save_overwrites_a_foreign_sidecar_once_confirmed(
    window, recording_path, monkeypatch
):
    window._load(recording_path)
    _answer_label(monkeypatch, ("LRLR", False))
    window._on_region_drawn(10.0, 14.0)
    tsv_path, _ = sidecar_paths(recording_path)
    write_annotations_tsv([Annotation(1.0, 0.0, "other rater")], tsv_path)
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "question",
        lambda *a, **k: QtWidgets.QMessageBox.StandardButton.Yes,
    )
    window.save_annotations()
    assert read_annotations_tsv(tsv_path) == [Annotation(10.0, 4.0, "LRLR")]
    assert not window._dirty


# ----- label dialog / entry point -----------------------------------------------------


def test_failed_save_keeps_the_dirty_flag(
    window, recording_path, monkeypatch, silence_dialogs
):
    # If the sidecar write fails, the annotations are still unsaved — clearing
    # the flag would let the close prompt silently discard them.
    window._load(recording_path)
    _answer_label(monkeypatch, ("LRLR", False))
    window._on_region_drawn(10.0, 14.0)

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(window_mod, "write_annotations_tsv", boom)
    window.save_annotations()
    assert window._dirty
    assert window.windowTitle().endswith("*")


def test_open_file_respects_a_cancelled_discard_prompt(
    window, recording_path, monkeypatch
):
    window._load(recording_path)
    _answer_label(monkeypatch, ("LRLR", False))
    window._on_region_drawn(10.0, 14.0)
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "question",
        lambda *a, **k: QtWidgets.QMessageBox.StandardButton.Cancel,
    )
    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getOpenFileName",
        lambda *a, **k: pytest.fail("the file dialog must not open"),
    )
    window.open_file()  # cancelled prompt: no dialog, annotations intact
    assert window._annotations  # nothing was discarded


def test_open_dialog_starts_in_the_last_used_folder(
    window, recording_path, monkeypatch
):
    window._load(recording_path)  # records eeg_last_dir
    seen_dirs: list[str] = []

    def fake_dialog(parent, caption, directory, file_filter):
        seen_dirs.append(directory)
        return "", ""

    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", fake_dialog)
    window.open_file()
    assert seen_dirs == [str(recording_path.parent)]


def test_trace_click_highlights_the_list_row(window, recording_path, monkeypatch):
    window._load(recording_path)
    _answer_label(monkeypatch, ("Arousal", False))
    window._on_region_drawn(10.0, 14.0)
    _answer_label(monkeypatch, ("LRLR", False))
    window._on_region_drawn(30.0, 31.0)
    window.view._on_clicked(30.5)  # inside the second annotation
    assert window.annotationList.currentRow() == 1
    window.view._on_clicked(20.0)  # empty space deselects
    assert window.annotationList.currentRow() == -1


def test_edit_and_delete_without_a_selection_are_no_ops(
    window, recording_path, monkeypatch
):
    window._load(recording_path)
    monkeypatch.setattr(
        window_mod.LabelDialog,
        "get_label",
        staticmethod(lambda *a, **k: pytest.fail("no dialog expected")),
    )
    window.edit_selected()
    window.delete_selected()
    assert window._annotations == []
    assert not window._dirty


def test_double_click_jumps_to_the_annotation(window, recording_path, monkeypatch):
    window._load(recording_path)
    _answer_label(monkeypatch, ("Arousal", False))
    window._on_region_drawn(50.0, 51.0)
    window.annotationList.setCurrentRow(0)
    item = window.annotationList.item(0)
    window.annotationList.itemDoubleClicked.emit(item)
    assert window.view.window_start == pytest.approx(50.0 - 7.5)


def test_geometry_is_persisted_on_close(window, recording_path):
    # The layout's minimum size may override a small resize request, so pin
    # the expectation to whatever geometry the window actually had at close.
    window.resize(1600, 800)
    expected = {
        "x": window.x(),
        "y": window.y(),
        "w": window.width(),
        "h": window.height(),
    }
    assert window.close()
    prefs = preferences.load_preferences(window._prefs_path)
    assert preferences.window_geometry(prefs, "eeg-review") == expected


def test_recent_labels_are_capped_and_deduplicated(window):
    for i in range(14):
        window._remember_label(f"label-{i}")
    window._remember_label("label-5")  # an old one used again moves up front
    recents = window._recent_labels()
    assert len(recents) == 12
    assert recents[0] == "label-5"
    assert recents[1] == "label-13"


def test_label_dialog_merges_recents_over_seeds(qtbot):
    dialog = LabelDialog(None, ["Custom", SEED_LABELS[0]])
    qtbot.addWidget(dialog)
    items = [dialog.labelCombo.itemText(i) for i in range(dialog.labelCombo.count())]
    assert items == ["Custom", *SEED_LABELS]  # deduplicated, recents first


def test_pick_recording_path_takes_the_last_non_flag_argument():
    assert pick_recording_path(["exe"]) is None
    assert pick_recording_path(["exe", "--debug", "a.edf"]) == "a.edf"
    assert pick_recording_path(["exe", "a.edf", "b.fif"]) == "b.fif"


# ----- wall-clock display ---------------------------------------------------------


def test_wall_time_shows_edf_stamps_as_recorded(tmp_path):
    # EDF start times are the tech's wall-clock stamps (MNE tags them UTC pro
    # forma); converting them would lie about what the bedside clock said.
    rec = FakeRecording(tmp_path / "night1.edf")
    clock = window_mod.wall_time(rec, 90.0)
    assert clock == MEAS_DATE + timedelta(seconds=90)
    assert clock.strftime("%H:%M:%S") == "22:01:30"


def test_wall_time_converts_fif_instants_to_local(tmp_path):
    # A FIF meas_date is a true UTC instant; showing it raw would display
    # UTC, not the wall clock the tech saw. astimezone() is right whenever
    # the file is reviewed in the timezone it was recorded in.
    rec = FakeRecording(tmp_path / "night1_raw.fif")
    clock = window_mod.wall_time(rec, 0.0)
    assert clock == MEAS_DATE.astimezone()


def test_wall_time_without_meas_date_is_none(tmp_path):
    rec = FakeRecording(tmp_path / "night1.edf")
    rec.meas_date = None
    assert window_mod.wall_time(rec, 0.0) is None


# ----- process hygiene (subprocess checks) --------------------------------------------


def test_eeg_window_never_imports_the_live_session_stack():
    # The EEG tool runs as its own process and the frozen SMACC-EEG.exe will
    # not ship the live-session stack — importing it here (e.g. panels.base,
    # which imports sounddevice and SmaccSession at module scope) would break
    # the packaged build and the documented process isolation.
    code = (
        "import sys; import smacc.eeg.window; "
        "leaks = [m for m in ('sounddevice', 'smacc.session', 'smacc.devices', "
        "'smacc.panels.base') if m in sys.modules]; "
        "sys.exit('leaked: ' + ', '.join(leaks) if leaks else 0)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 0, proc.stderr


def test_version_flag_exits_zero_without_a_window():
    # The release workflow smoke-tests the frozen SMACC-EEG.exe with exactly
    # this invocation; the import tree resolving and exit code 0 are the test.
    proc = subprocess.run(
        [sys.executable, "-m", "smacc.eeg", "--version"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert VERSION in proc.stdout


def test_selftest_round_trips_through_mne():
    # The stronger frozen-bundle smoke test (MNE is lazy, so --version alone
    # can't catch a broken MNE bundling). Exercised here on the dev install so
    # a selftest regression is caught before a release build trips on it.
    if find_spec("mne") is None:
        pytest.skip("needs the eeg extra (mne)")
    proc = subprocess.run(
        [sys.executable, "-m", "smacc.eeg", "--selftest"],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    assert "selftest ok" in proc.stdout
