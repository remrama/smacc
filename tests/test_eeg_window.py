"""Tests for the EEG review window (#136) — offscreen, no MNE.

``io.open_recording``/``io.embedded_annotations`` are monkeypatched with a
fake recording, so the window's whole flow — open, sidecar precedence,
annotate, edit, delete, save, dirty/close — runs without the eeg extra.
Preferences are pointed at a temp file (the launcher-test pattern) so no test
touches the machine's real ``preferences.yaml``.
"""

from __future__ import annotations

import json
import os
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
from smacc.eeg import blind, dsp
from smacc.eeg import window as window_mod
from smacc.eeg.__main__ import pick_blind_spec, pick_rater_id, pick_recording_path
from smacc.eeg.annotations import (
    Annotation,
    autosave_path,
    rater_autosave_path,
    rater_sidecar_paths,
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


def test_event_filter_routes_keys_only_when_active(window, recording_path, monkeypatch):
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
        lambda *a, **k: pytest.fail(
            "no overwrite prompt when resuming our own sidecar"
        ),
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


# ----- autosave / crash recovery (#176) --------------------------------------------


def test_autosave_writes_a_recovery_file(window, recording_path, monkeypatch):
    window._load(recording_path)
    _answer_label(monkeypatch, ("LRLR", False))
    window._on_region_drawn(10.0, 14.0)
    window._write_autosave()  # fire the debounced write directly
    recovery = autosave_path(recording_path)
    assert recovery.is_file()
    assert read_annotations_tsv(recovery) == [Annotation(10.0, 4.0, "LRLR")]
    # The recovery file must be distinct from the canonical sidecar.
    tsv_path, _ = sidecar_paths(recording_path)
    assert recovery != tsv_path and not tsv_path.is_file()


def test_clean_save_removes_the_recovery_file(window, recording_path, monkeypatch):
    window._load(recording_path)
    _answer_label(monkeypatch, ("LRLR", False))
    window._on_region_drawn(10.0, 14.0)
    window._write_autosave()
    assert autosave_path(recording_path).is_file()
    window.save_annotations()
    assert not autosave_path(recording_path).is_file()


def test_recovery_is_offered_and_can_be_restored(window, recording_path):
    recovery = autosave_path(recording_path)
    write_annotations_tsv([Annotation(7.0, 0.0, "LRLR")], recovery)  # a crashed session
    window._load(recording_path)
    assert window.recoveryBanner.isVisible()
    window._restore_autosave()
    assert window._annotations == [Annotation(7.0, 0.0, "LRLR")]
    assert window._dirty  # restored but not yet saved
    assert not window.recoveryBanner.isVisible()


def test_recovery_can_be_dismissed_and_is_deleted(window, recording_path):
    recovery = autosave_path(recording_path)
    write_annotations_tsv([Annotation(7.0, 0.0, "LRLR")], recovery)
    window._load(recording_path)
    assert window.recoveryBanner.isVisible()
    window._dismiss_autosave()
    assert not window.recoveryBanner.isVisible()
    assert not recovery.is_file()


def test_stale_autosave_older_than_the_sidecar_is_ignored(window, recording_path):
    tsv_path, _ = sidecar_paths(recording_path)
    write_annotations_tsv([Annotation(5.0, 2.0, "saved")], tsv_path)  # a clean save
    recovery = autosave_path(recording_path)
    write_annotations_tsv([Annotation(7.0, 0.0, "old")], recovery)
    os.utime(recovery, (1000, 1000))  # force the autosave to look old
    window._load(recording_path)
    assert not window.recoveryBanner.isVisible()
    assert not recovery.is_file()  # stale autosave is cleaned on open


def test_clean_close_removes_the_recovery_file(window, recording_path, monkeypatch):
    window._load(recording_path)
    _answer_label(monkeypatch, ("LRLR", False))
    window._on_region_drawn(10.0, 14.0)
    window._write_autosave()
    assert autosave_path(recording_path).is_file()
    assert window.close()  # the fixture answers the dirty prompt with Discard
    assert not autosave_path(recording_path).is_file()


# ----- channel picker + per-type display + view profiles (#177) --------------------


def test_scope_combo_lists_all_channels_then_present_types(window, recording_path):
    window._load(recording_path)  # FakeRecording types: eeg, eeg, eog, emg
    datas = [
        window.filterScopeCombo.itemData(i)
        for i in range(window.filterScopeCombo.count())
    ]
    assert datas == [None, "eeg", "eog", "emg"]


def test_filter_controls_edit_the_base_by_default(window, recording_path):
    window._load(recording_path)  # scope defaults to "All channels"
    window.highpassSpin.setValue(0.3)
    assert window.view.spec == dsp.FilterSpec(highpass=0.3)


def test_filter_controls_edit_one_type_when_scoped(window, recording_path):
    window._load(recording_path)
    window.filterScopeCombo.setCurrentIndex(3)  # EMG
    window.highpassSpin.setValue(10.0)
    assert window.view.effective_spec("emg") == dsp.FilterSpec(highpass=10.0)
    assert window.view.spec == dsp.FilterSpec()  # base left alone


def test_scale_control_edits_one_type_when_scoped(window, recording_path):
    window._load(recording_path)
    window.filterScopeCombo.setCurrentIndex(1)  # EEG
    window.scaleSpin.setValue(60.0)
    assert window.view.effective_scale("eeg") == 60.0


def test_scope_change_loads_that_types_settings_into_the_controls(
    window, recording_path
):
    window._load(recording_path)
    window.filterScopeCombo.setCurrentIndex(3)  # EMG defaults to a 200 µV lane
    assert window.scaleSpin.value() == 200.0
    window.filterScopeCombo.setCurrentIndex(0)  # back to the 100 µV base
    assert window.scaleSpin.value() == 100.0


def test_channel_picker_applies_the_chosen_order(window, recording_path, monkeypatch):
    window._load(recording_path)
    monkeypatch.setattr(
        window_mod.ChannelPickerDialog,
        "get_visible",
        staticmethod(lambda *a, **k: [2, 0]),  # EOG then C3
    )
    window._open_channel_picker()
    assert window.view.visible_channels == ["EOG", "C3"]


def test_save_then_load_profile_round_trips(
    window, recording_path, tmp_path, monkeypatch
):
    window._load(recording_path)
    window.view.set_visible_channels([0, 3])  # C3, EMG
    window.filterScopeCombo.setCurrentIndex(1)  # EEG scope
    window.scaleSpin.setValue(70.0)
    window.highpassSpin.setValue(0.5)
    path = tmp_path / "montage.smacc-view.json"
    monkeypatch.setattr(
        QtWidgets.QFileDialog, "getSaveFileName", lambda *a, **k: (str(path), "")
    )
    window._save_profile()
    assert path.is_file()
    # Wipe the montage, then load it back.
    window.view.set_visible_channels([0, 1, 2, 3])
    window.view.set_scale(100.0)
    window.view.set_type_scales({})
    window.view.set_type_specs({})
    monkeypatch.setattr(
        QtWidgets.QFileDialog, "getOpenFileName", lambda *a, **k: (str(path), "")
    )
    window._load_profile()
    assert window.view.visible_channels == ["C3", "EMG"]
    assert window.view.effective_scale("eeg") == 70.0
    assert window.view.effective_spec("eeg") == dsp.FilterSpec(highpass=0.5)


def test_load_profile_skips_channels_not_in_the_recording(
    window, recording_path, tmp_path, monkeypatch
):
    from smacc.eeg.profiles import ViewProfile, write_view_profile

    path = tmp_path / "m.smacc-view.json"
    write_view_profile(ViewProfile(channels=("C4", "NOSUCH", "C3")), path)
    window._load(recording_path)
    monkeypatch.setattr(
        QtWidgets.QFileDialog, "getOpenFileName", lambda *a, **k: (str(path), "")
    )
    window._load_profile()
    assert window.view.visible_channels == ["C4", "C3"]  # NOSUCH skipped


# ----- figure export (#180) --------------------------------------------------------


def test_export_dialog_collects_marks_and_options(qtbot):
    from smacc.eeg.window import ExportDialog

    dialog = ExportDialog(
        None, ["C3", "C4"], [0, 1], [(12.0, 0.0, "tech-A"), (20.0, 3.0, "tech-B")]
    )
    qtbot.addWidget(dialog)
    dialog.annoTable.item(0, 1).setText("LRLR x3")  # relabel the first mark
    dialog.annoTable.item(1, 0).setCheckState(
        QtCore.Qt.CheckState.Unchecked
    )  # drop 2nd
    dialog.formatCombo.setCurrentIndex(2)  # SVG
    dialog.epochGridCheck.setChecked(True)
    options, marks, channels = dialog.result_values()
    assert options.fmt == "svg"
    assert options.show_epoch_grid is True
    assert marks == [(12.0, 0.0, "LRLR x3")]  # second mark excluded
    assert channels is None  # the picker was not opened


def test_export_figure_renders_with_the_dialog_choices(
    window, recording_path, tmp_path, monkeypatch
):
    from smacc.eeg import export as export_mod

    window._load(recording_path)
    _answer_label(monkeypatch, ("Cue response", False))
    window._on_region_drawn(10.0, 14.0)  # an in-window span annotation
    options = export_mod.ExportOptions(fmt="png", show_epoch_grid=False)
    monkeypatch.setattr(
        window_mod.ExportDialog,
        "get_export",
        staticmethod(lambda *a, **k: (options, [(10.0, 4.0, "two-way comms")], None)),
    )
    out = tmp_path / "figure.png"
    monkeypatch.setattr(
        QtWidgets.QFileDialog, "getSaveFileName", lambda *a, **k: (str(out), "")
    )
    captured: dict = {}
    real_render = export_mod.render

    def spy_render(snapshot, opts, path):
        captured["snapshot"] = snapshot
        real_render(snapshot, opts, path)

    monkeypatch.setattr(export_mod, "render", spy_render)
    window._export_figure()
    assert out.is_file()
    snap = captured["snapshot"]
    assert [m.label for m in snap.marks] == ["two-way comms"]  # the relabel reached it
    assert snap.marks[0].onset == pytest.approx(10.0)  # window starts at 0
    prefs = preferences.load_preferences(window._prefs_path)
    assert prefs["eeg_last_export_dir"] == str(out.parent)


def test_export_figure_appends_a_missing_suffix(
    window, recording_path, tmp_path, monkeypatch
):
    from smacc.eeg import export as export_mod

    window._load(recording_path)
    options = export_mod.ExportOptions(fmt="pdf")
    monkeypatch.setattr(
        window_mod.ExportDialog,
        "get_export",
        staticmethod(lambda *a, **k: (options, [], None)),
    )
    bare = tmp_path / "figure"  # no extension typed
    monkeypatch.setattr(
        QtWidgets.QFileDialog, "getSaveFileName", lambda *a, **k: (str(bare), "")
    )
    window._export_figure()
    assert (tmp_path / "figure.pdf").is_file()


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


def test_pick_recording_path_skips_value_flag_values(tmp_path):
    # --rater/--blind values must not be mistaken for the recording.
    assert (
        pick_recording_path(["exe", "--rater", "alice", "night1.edf"]) == "night1.edf"
    )
    assert pick_recording_path(["exe", "--rater", "alice"]) is None
    assert pick_recording_path(["exe", "--rater=alice", "night1.edf"]) == "night1.edf"
    assert (
        pick_recording_path(["exe", "--blind", "naive", "night1.edf"]) == "night1.edf"
    )
    assert (
        pick_recording_path(["exe", "--rater", "a", "--blind", "naive", "n.edf"])
        == "n.edf"
    )


def test_pick_rater_id_reads_both_forms():
    assert pick_rater_id(["exe", "--rater", "alice", "night1.edf"]) == "alice"
    assert pick_rater_id(["exe", "--rater=bob", "night1.edf"]) == "bob"
    assert pick_rater_id(["exe", "night1.edf"]) is None
    assert pick_rater_id(["exe", "--rater"]) is None  # dangling flag, no value


def test_pick_blind_spec_reads_both_forms():
    assert pick_blind_spec(["exe", "--blind", "naive", "night1.edf"]) == "naive"
    assert pick_blind_spec(["exe", "--blind=study.smacc-blind.json"]) == (
        "study.smacc-blind.json"
    )
    assert pick_blind_spec(["exe", "night1.edf"]) is None


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


# ----- rater identity (#181) ------------------------------------------------


@pytest.fixture
def make_window(qtbot, tmp_path, monkeypatch):
    """Build EegReviewWindows (optionally with a rater id) over the faked IO,
    isolated prefs, and auto-answered dialogs the ``window`` fixture uses."""
    monkeypatch.setattr(window_mod, "preferences_path", tmp_path / "prefs.yaml")
    monkeypatch.setattr(window_mod.io, "open_recording", FakeRecording)
    monkeypatch.setattr(window_mod.io, "embedded_annotations", lambda rec: [])
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "question",
        lambda *a, **k: QtWidgets.QMessageBox.StandardButton.Discard,
    )

    def build(
        rater_id: str | None = None, blind_spec: str | None = None
    ) -> EegReviewWindow:
        win = EegReviewWindow(rater_id=rater_id, blind_spec=blind_spec)
        qtbot.addWidget(win)
        win.show()
        win._prefs_path = tmp_path / "prefs.yaml"  # test convenience handle
        return win

    return build


def test_constructor_resolves_rater_from_the_pref(make_window, tmp_path):
    preferences.update_preferences(tmp_path / "prefs.yaml", {"eeg_rater_id": "carol"})
    win = make_window()  # no explicit arg → falls back to the saved pref
    assert win._rater_id == "carol"


def test_explicit_rater_arg_beats_the_pref(make_window, tmp_path):
    preferences.update_preferences(tmp_path / "prefs.yaml", {"eeg_rater_id": "carol"})
    assert make_window("alice")._rater_id == "alice"


def test_unusable_rater_falls_back_to_single_rater(make_window, tmp_path):
    preferences.update_preferences(tmp_path / "prefs.yaml", {"eeg_rater_id": "!!!"})
    assert make_window()._rater_id is None  # nothing safe → plain sidecar, no crash


def test_rater_button_shows_the_active_id(make_window):
    win = make_window("alice")
    assert win.raterButton.text() == "Rater: alice"
    win._apply_rater_id(None)
    assert win.raterButton.text() == "Rater…"


def test_title_shows_the_rater(make_window, recording_path):
    win = make_window("alice")
    win._load(recording_path)
    assert "rater alice" in win.windowTitle()


def test_rater_save_writes_the_rater_sidecar_only(
    make_window, recording_path, monkeypatch
):
    win = make_window("alice")
    win._confirmed_raters.add("alice")  # identity confirmed (tested separately)
    win._load(recording_path)
    _answer_label(monkeypatch, ("LRLR", False))
    win._on_region_drawn(10.0, 14.0)
    win.save_annotations()
    rater_tsv, rater_json = rater_sidecar_paths(recording_path, "alice")
    plain_tsv, _ = sidecar_paths(recording_path)
    assert read_annotations_tsv(rater_tsv) == [Annotation(10.0, 4.0, "LRLR")]
    assert json.loads(rater_json.read_text(encoding="utf-8"))["Rater"] == "alice"
    assert not plain_tsv.exists()  # the single-rater/truth sidecar is untouched


def test_rater_load_resumes_from_the_rater_sidecar(
    make_window, recording_path, monkeypatch
):
    saved = [Annotation(5.0, 2.0, "REM period")]
    rater_tsv, _ = rater_sidecar_paths(recording_path, "alice")
    write_annotations_tsv(saved, rater_tsv)
    # A second rater must not see alice's marks: their fresh review imports the
    # embedded events instead, against their own (absent) sidecar.
    monkeypatch.setattr(
        window_mod.io,
        "embedded_annotations",
        lambda rec: [Annotation(1.0, 0.0, "Cue")],
    )
    alice = make_window("alice")
    alice._load(recording_path)
    assert alice._annotations == saved
    bob = make_window("bob")
    bob._load(recording_path)
    assert alice._annotations == saved  # alice's review is unaffected
    assert bob._annotations == [Annotation(1.0, 0.0, "Cue")]  # bob starts fresh


def test_rater_autosave_uses_the_rater_path(make_window, recording_path, monkeypatch):
    win = make_window("alice")
    win._load(recording_path)
    _answer_label(monkeypatch, ("LRLR", False))
    win._on_region_drawn(10.0, 14.0)  # marks dirty
    win._write_autosave()
    assert rater_autosave_path(recording_path, "alice").is_file()
    assert not autosave_path(recording_path).exists()  # not the plain autosave


def test_switching_rater_repoints_output_and_drops_the_old_autosave(
    make_window, recording_path, monkeypatch
):
    win = make_window()  # single-rater to start
    win._load(recording_path)
    _answer_label(monkeypatch, ("LRLR", False))
    win._on_region_drawn(10.0, 14.0)
    win._write_autosave()
    assert autosave_path(recording_path).is_file()  # the plain autosave exists
    win._apply_rater_id("alice")
    assert win._rater_id == "alice"
    assert win._dirty  # the marks now belong to alice, unsaved
    assert not autosave_path(recording_path).exists()  # misattributed autosave gone
    assert preferences.load_preferences(win._prefs_path)["eeg_rater_id"] == "alice"
    win._confirmed_raters.add("alice")
    win.save_annotations()
    rater_tsv, _ = rater_sidecar_paths(recording_path, "alice")
    assert read_annotations_tsv(rater_tsv) == [Annotation(10.0, 4.0, "LRLR")]


def test_save_confirm_fires_once_per_rater(make_window, recording_path, monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "question",
        lambda *a, **k: calls.append(1) or QtWidgets.QMessageBox.StandardButton.Save,
    )
    win = make_window("alice")
    win._load(recording_path)
    _answer_label(monkeypatch, ("LRLR", False))
    win._on_region_drawn(10.0, 14.0)
    win.save_annotations()  # first save under "alice" → confirms
    win._on_region_drawn(20.0, 21.0)
    win.save_annotations()  # already confirmed → silent
    assert len(calls) == 1
    assert "alice" in win._confirmed_raters


def test_save_confirm_cancel_blocks_the_save(make_window, recording_path, monkeypatch):
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "question",
        lambda *a, **k: QtWidgets.QMessageBox.StandardButton.Cancel,
    )
    win = make_window("alice")
    win._load(recording_path)
    _answer_label(monkeypatch, ("LRLR", False))
    win._on_region_drawn(10.0, 14.0)
    win.save_annotations()
    rater_tsv, _ = rater_sidecar_paths(recording_path, "alice")
    assert not rater_tsv.exists()  # cancelled before any write
    assert win._dirty
    win._dirty = False  # let teardown close cleanly under the Cancel patch


def test_single_rater_save_never_prompts_for_identity(
    make_window, recording_path, monkeypatch
):
    # The fixture answers QMessageBox.question with Discard; a single-rater save
    # must still succeed, proving it never reaches the identity prompt.
    win = make_window()  # no rater id
    win._load(recording_path)
    _answer_label(monkeypatch, ("LRLR", False))
    win._on_region_drawn(10.0, 14.0)
    win.save_annotations()
    plain_tsv, _ = sidecar_paths(recording_path)
    assert read_annotations_tsv(plain_tsv) == [Annotation(10.0, 4.0, "LRLR")]
    assert not win._dirty


# ----- quick-mark palette (#181) --------------------------------------------

DEFAULT_PALETTE = ["LRLR", "LRLRx2", "LRLRx3", "IEIE"]


def test_palette_seeds_buttons_from_the_pref(window):
    assert [b.text() for b in window._palette_buttons] == DEFAULT_PALETTE


def test_palette_buttons_disabled_until_a_recording_loads(window, recording_path):
    assert all(not b.isEnabled() for b in window._palette_buttons)
    window._load(recording_path)
    assert all(b.isEnabled() for b in window._palette_buttons)


def test_palette_button_drops_a_labeled_mark_at_the_cursor(window, recording_path):
    window._load(recording_path)
    window._on_cursor_moved(33.0)
    window._palette_buttons[0].click()  # "LRLR" — no dialog
    assert window._annotations == [Annotation(33.0, 0.0, "LRLR")]
    assert window._dirty
    # The palette label also lands in the recents that seed the label dialog.
    assert window._recent_labels()[0] == "LRLR"


def test_palette_button_falls_back_to_the_view_center(window, recording_path):
    window._load(recording_path)  # cursor never moved; 0–30 window → center 15
    window._palette_buttons[1].click()  # "LRLRx2"
    assert window._annotations == [Annotation(15.0, 0.0, "LRLRx2")]


def test_palette_number_key_inserts_the_nth_label(window, recording_path, monkeypatch):
    window._load(recording_path)
    window._on_cursor_moved(40.0)
    monkeypatch.setattr(
        QtWidgets.QApplication, "focusWidget", staticmethod(lambda: None)
    )
    event = QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyPress,
        QtCore.Qt.Key.Key_2,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    assert window._handle_palette_key(event)  # consumed
    assert window._annotations == [Annotation(40.0, 0.0, "LRLRx2")]  # 2nd label


def test_palette_number_key_yields_to_text_entry(window, recording_path, monkeypatch):
    window._load(recording_path)
    monkeypatch.setattr(
        QtWidgets.QApplication, "focusWidget", staticmethod(lambda: window.scaleSpin)
    )
    event = QtGui.QKeyEvent(
        QtCore.QEvent.Type.KeyPress,
        QtCore.Qt.Key.Key_1,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    assert not window._handle_palette_key(event)  # the spin box keeps the digit
    assert window._annotations == []


def test_palette_number_key_past_the_end_is_ignored(
    window, recording_path, monkeypatch
):
    window._load(recording_path)
    monkeypatch.setattr(
        QtWidgets.QApplication, "focusWidget", staticmethod(lambda: None)
    )
    event = QtGui.QKeyEvent(  # only four palette buttons; 9 has no target
        QtCore.QEvent.Type.KeyPress,
        QtCore.Qt.Key.Key_9,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    assert not window._handle_palette_key(event)
    assert window._annotations == []


def test_editing_the_palette_persists_and_rebuilds(window, monkeypatch):
    monkeypatch.setattr(
        window_mod.PaletteEditorDialog,
        "get_palette",
        staticmethod(lambda *a, **k: ["Sniff", "Frown"]),
    )
    window._edit_palette()
    assert [b.text() for b in window._palette_buttons] == ["Sniff", "Frown"]
    prefs = preferences.load_preferences(window._prefs_path)
    assert prefs["eeg_palette_labels"] == ["Sniff", "Frown"]


def test_cancelling_the_palette_editor_changes_nothing(window, monkeypatch):
    monkeypatch.setattr(
        window_mod.PaletteEditorDialog,
        "get_palette",
        staticmethod(lambda *a, **k: None),  # cancelled
    )
    window._edit_palette()
    assert [b.text() for b in window._palette_buttons] == DEFAULT_PALETTE


def test_palette_editor_reorders_and_normalizes_labels(qtbot):
    dialog = window_mod.PaletteEditorDialog(None, ["A", "B", "   "])
    qtbot.addWidget(dialog)
    dialog.listWidget.setCurrentRow(1)
    dialog._move(-1)  # B moves above A
    # Reordered, whitespace-normalized, and the blank entry dropped.
    assert dialog.result_labels() == ["B", "A"]


# ----- blind-rater mode (#181) ----------------------------------------------


def test_blind_without_a_rater_id_aborts_the_open(
    make_window, recording_path, silence_dialogs
):
    win = make_window()  # no rater id — blinding would clobber the truth file
    win._blind = blind.preset_config(blind.PRESET_NAIVE)
    win._load(recording_path)
    assert win._recording is None  # refused before opening
    assert not win.saveButton.isEnabled()


def test_naive_blind_hides_embedded_marks_before_render(
    make_window, recording_path, monkeypatch
):
    monkeypatch.setattr(
        window_mod.io,
        "embedded_annotations",
        lambda rec: [
            Annotation(5.0, 0.0, "SignalObserved"),
            Annotation(8.0, 0.0, "Cue"),
        ],
    )
    win = make_window("alice")
    win._blind = blind.preset_config(blind.PRESET_NAIVE)
    win._load(recording_path)
    assert win._annotations == []  # nothing hidden ever reaches window state
    assert win.annotationList.count() == 0


def test_classify_blind_seeds_from_truth_and_blanks_signals(
    make_window, recording_path
):
    # A fresh blind review seeds from the coordinator's truth (the plain sidecar).
    truth = [Annotation(5.0, 0.0, "SignalObserved"), Annotation(8.0, 0.0, "Arousal")]
    plain_tsv, _ = sidecar_paths(recording_path)
    write_annotations_tsv(truth, plain_tsv)
    win = make_window("alice")
    win._blind = blind.preset_config(blind.PRESET_CLASSIFY)
    win._load(recording_path)
    # Only the signal position survives, label blanked; the arousal is hidden.
    assert win._annotations == [Annotation(5.0, 0.0, "?")]


def test_blind_seeds_from_truth_not_embedded(make_window, recording_path, monkeypatch):
    truth = [Annotation(5.0, 0.0, "DreamReportStarted")]
    plain_tsv, _ = sidecar_paths(recording_path)
    write_annotations_tsv(truth, plain_tsv)
    monkeypatch.setattr(
        window_mod.io,
        "embedded_annotations",
        lambda rec: pytest.fail("blind seeds from the truth sidecar, not embedded"),
    )
    win = make_window("alice")
    win._blind = blind.preset_config(blind.PRESET_REPORTS)
    win._load(recording_path)
    assert win._annotations == truth  # the report is visible


def test_rater_resume_is_not_reblinded(make_window, recording_path):
    # Alice already saved her classifications; reopening blind shows them as-is —
    # naive would wipe them if resume were (wrongly) re-filtered.
    alice_marks = [Annotation(5.0, 0.0, "LRLR"), Annotation(8.0, 0.0, "?")]
    rater_tsv, _ = rater_sidecar_paths(recording_path, "alice")
    write_annotations_tsv(alice_marks, rater_tsv)
    win = make_window("alice")
    win._blind = blind.preset_config(blind.PRESET_NAIVE)
    win._load(recording_path)
    assert win._annotations == alice_marks  # her own marks survive, unfiltered


def test_blind_save_writes_rater_path_and_leaves_truth(make_window, recording_path):
    truth = [Annotation(5.0, 0.0, "SignalObserved")]
    plain_tsv, _ = sidecar_paths(recording_path)
    write_annotations_tsv(truth, plain_tsv)
    win = make_window("alice")
    win._confirmed_raters.add("alice")
    win._blind = blind.preset_config(blind.PRESET_CLASSIFY)
    win._load(recording_path)  # alice sees the blanked signal
    win.save_annotations()
    rater_tsv, _ = rater_sidecar_paths(recording_path, "alice")
    assert read_annotations_tsv(rater_tsv) == [Annotation(5.0, 0.0, "?")]
    assert read_annotations_tsv(plain_tsv) == truth  # truth untouched


def test_blind_button_reflects_the_mode(make_window):
    win = make_window("alice")
    assert win.blindButton.text() == "Blind: off"
    win._set_blind(blind.preset_config(blind.PRESET_CLASSIFY))
    assert win.blindButton.text() == "Blind: classify"


def test_set_blind_without_a_rater_is_refused(make_window, silence_dialogs):
    win = make_window()  # no rater id
    win._set_blind(blind.preset_config(blind.PRESET_NAIVE))
    assert win._blind is None  # refused


def test_blind_config_palette_overrides_the_buttons(make_window):
    win = make_window("alice")
    win._set_blind(
        blind.BlindConfig(
            preset="custom",
            signal_labels=("SignalObserved",),
            palette=("LRLR", "Sniff"),
        )
    )
    assert [b.text() for b in win._palette_buttons] == ["LRLR", "Sniff"]


def test_bad_blind_spec_opens_unblinded(make_window, silence_dialogs):
    # An unknown --blind value must not crash the launch; it records a (deferred)
    # error and the window opens with blinding off.
    win = make_window(blind_spec="not-a-preset")
    assert win._blind is None
    assert win._blind_error is not None


# ----- other-rater overlays (#181) ------------------------------------------


def _write_rater(recording_path, rater_id, marks):
    tsv, _ = rater_sidecar_paths(recording_path, rater_id)
    write_annotations_tsv(marks, tsv)


def test_overlays_load_peers_excluding_own(make_window, recording_path):
    _write_rater(recording_path, "alice", [Annotation(5.0, 0.0, "x")])
    _write_rater(recording_path, "bob", [Annotation(6.0, 0.0, "y")])
    _write_rater(recording_path, "carol", [Annotation(7.0, 0.0, "z")])
    win = make_window("alice")
    win._load(recording_path)
    assert [rid for rid, _, _ in win._rater_layers] == ["bob", "carol"]  # own excluded
    assert win.ratersGroup.isVisible()
    assert len(win._rater_checks) == 2


def test_single_rater_coordinator_sees_all_peers(make_window, recording_path):
    _write_rater(recording_path, "alice", [Annotation(5.0, 0.0, "x")])
    _write_rater(recording_path, "bob", [Annotation(6.0, 0.0, "y")])
    win = make_window()  # no rater id — editing the plain truth file
    win._load(recording_path)
    assert [rid for rid, _, _ in win._rater_layers] == ["alice", "bob"]


def test_overlays_are_hidden_in_blind_mode(make_window, recording_path):
    _write_rater(recording_path, "bob", [Annotation(6.0, 0.0, "y")])
    win = make_window("alice")
    win._blind = blind.preset_config(blind.PRESET_NAIVE)
    win._load(recording_path)
    assert win._rater_layers == []  # a blind rater must not see peers
    assert not win.ratersGroup.isVisible()


def test_toggling_a_rater_hides_its_overlay(make_window, recording_path):
    _write_rater(recording_path, "bob", [Annotation(6.0, 0.0, "y")])
    win = make_window("alice")
    win._load(recording_path)
    assert any(o.rater_id == "bob" and o.visible for o in win.view._overlays)
    win._toggle_rater("bob", False)
    assert "bob" in win._hidden_raters
    assert all(not o.visible for o in win.view._overlays if o.rater_id == "bob")


def test_corrupt_peer_sidecar_is_skipped(make_window, recording_path):
    _write_rater(recording_path, "bob", [Annotation(6.0, 0.0, "y")])
    carol_tsv, _ = rater_sidecar_paths(recording_path, "carol")
    carol_tsv.write_text("not\ta\tsidecar\n", encoding="utf-8")
    win = make_window("alice")
    win._load(recording_path)
    assert [rid for rid, _, _ in win._rater_layers] == ["bob"]  # carol skipped
