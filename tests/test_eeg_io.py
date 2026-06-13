"""Tests for the MNE-backed recording access in :mod:`smacc.eeg.io` (#136).

These need MNE (the ``eeg`` extra), so the module skips without it — the rest
of the eeg tests (model, dsp) stay runnable in a base dev environment.
Recordings are synthesized as FIF (the one format MNE writes natively, so no
extra dependency); the suffix dispatch for EDF/BrainVision is asserted against
the reader table since their writers aren't available to round-trip.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

mne = pytest.importorskip("mne")

from smacc.eeg import io  # noqa: E402

SFREQ = 100.0
MEAS_DATE = datetime(2026, 6, 5, 22, 0, 0, tzinfo=UTC)


def _make_raw(seconds: float = 30.0) -> mne.io.RawArray:
    """A small in-memory recording: 2 EEG + EOG + EMG at 100 Hz."""
    rng = np.random.default_rng(0)
    data = rng.standard_normal((4, int(seconds * SFREQ))) * 1e-5
    info = mne.create_info(
        ch_names=["C3", "C4", "EOG", "EMG"],
        sfreq=SFREQ,
        ch_types=["eeg", "eeg", "eog", "emg"],
        verbose="error",
    )
    raw = mne.io.RawArray(data, info, verbose="error")
    raw.set_meas_date(MEAS_DATE)
    return raw


@pytest.fixture
def fif_path(tmp_path):
    """A 30 s FIF on disk with one embedded annotation at 1.5 s."""
    raw = _make_raw()
    raw.set_annotations(
        mne.Annotations(onset=[1.5], duration=[0.5], description=["Arousal"])
    )
    path = tmp_path / "night1_raw.fif"
    raw.save(path, verbose="error")
    return path


# ----- opening ----------------------------------------------------------------


def test_open_recording_exposes_the_metadata(fif_path):
    rec = io.open_recording(fif_path)
    assert rec.ch_names == ["C3", "C4", "EOG", "EMG"]
    assert rec.ch_types == ["eeg", "eeg", "eog", "emg"]
    assert rec.sfreq == SFREQ
    assert rec.duration == pytest.approx(30.0)
    assert rec.meas_date == MEAS_DATE
    assert rec.path == fif_path


def test_open_recording_rejects_unknown_suffixes(tmp_path):
    bogus = tmp_path / "night1.xyz"
    bogus.write_text("not eeg")
    with pytest.raises(ValueError, match="Unsupported"):
        io.open_recording(bogus)


def test_reader_table_matches_real_mne_readers():
    # The non-FIF branches can't be round-tripped without their writers; at
    # minimum every name in the dispatch table must be a real mne.io reader.
    assert set(io._READERS) == {".edf", ".vhdr", ".fif", ".cnt", ".set"}
    for reader_name in io._READERS.values():
        assert callable(getattr(mne.io, reader_name))


def test_file_filter_lists_every_supported_extension():
    # FILE_FILTER is derived from _READERS, so a new format never needs a second
    # edit here; guard that the derivation actually covers the whole table.
    for ext in io._READERS:
        assert f"*{ext}" in io.FILE_FILTER


# ----- slicing ------------------------------------------------------------------


def test_get_slice_returns_data_relative_times(fif_path):
    rec = io.open_recording(fif_path)
    times, data = rec.get_slice(5.0, 10.0)
    assert data.shape == (4, 500)
    assert times[0] == pytest.approx(5.0)
    assert times[-1] == pytest.approx(10.0 - 1 / SFREQ)


def test_get_slice_clamps_to_the_recording(fif_path):
    rec = io.open_recording(fif_path)
    times, data = rec.get_slice(-3.0, 9_999.0)
    assert data.shape == (4, 3000)
    assert times[0] == pytest.approx(0.0)


def test_get_slice_past_the_end_is_empty_not_an_error(fif_path):
    rec = io.open_recording(fif_path)
    times, data = rec.get_slice(100.0, 200.0)
    assert times.size == 0
    assert data.shape == (4, 0)


# ----- embedded annotations ------------------------------------------------------


def test_embedded_annotations_convert_to_the_model(fif_path):
    rec = io.open_recording(fif_path)
    found = io.embedded_annotations(rec)
    assert len(found) == 1
    assert found[0].onset == pytest.approx(1.5)
    assert found[0].duration == pytest.approx(0.5)
    assert found[0].description == "Arousal"


def test_embedded_annotations_correct_for_first_time(tmp_path):
    # A cropped-then-saved FIF starts mid-stream (first_time > 0) while its
    # annotation onsets stay absolute; the conversion must shift them back to
    # the data-relative timebase annotations are displayed and saved in.
    raw = _make_raw()
    raw.set_annotations(
        mne.Annotations(onset=[3.0], duration=[0.0], description=["mark"])
    )
    cropped = raw.copy().crop(tmin=2.0)
    path = tmp_path / "cropped_raw.fif"
    cropped.save(path, verbose="error")
    rec = io.open_recording(path)
    assert rec._raw.first_time > 0  # the premise of this test
    found = io.embedded_annotations(rec)
    assert len(found) == 1
    assert found[0].onset == pytest.approx(1.0)  # 3.0 absolute - 2.0 crop


def test_embedded_annotations_name_blank_labels_instead_of_crashing(tmp_path):
    # EDF+ allows label-less events, and whitespace-only labels survive an MNE
    # round-trip verbatim; both must fall back to "unlabeled" — one odd label
    # must never abort the whole conversion (the valid ones would be lost too).
    raw = _make_raw()
    raw.set_annotations(
        mne.Annotations(
            onset=[1.0, 2.0, 3.0],
            duration=[0.0, 0.0, 0.0],
            description=["", "   ", "real"],
        )
    )
    rec = io.Recording(raw, tmp_path / "in-memory.fif")
    found = io.embedded_annotations(rec)
    assert [a.description for a in found] == ["unlabeled", "unlabeled", "real"]


def test_embedded_annotations_never_surface_out_of_range_events(tmp_path):
    # Crop away the start: the annotation before the new start must vanish
    # (whether MNE drops it on crop or our range check does), never appear
    # clamped at 0 as a lie.
    raw = _make_raw()
    raw.set_annotations(
        mne.Annotations(
            onset=[1.0, 5.0], duration=[0.0, 0.0], description=["gone", "kept"]
        )
    )
    cropped = raw.copy().crop(tmin=2.0)
    path = tmp_path / "cropped2_raw.fif"
    cropped.save(path, verbose="error")
    found = io.embedded_annotations(io.open_recording(path))
    assert [a.description for a in found] == ["kept"]


# ----- recorded trigger events (#125 auto-alignment) ------------------------


def test_recorded_trigger_events_parses_codes_from_annotations(tmp_path):
    # Codes surface in annotations as a bare "47" (Neuroscan/EEGLAB/EDF TAL) or
    # inside a label "Stimulus/S 60" (BrainVision); both yield the integer.
    raw = _make_raw()
    raw.set_annotations(
        mne.Annotations(
            onset=[1.0, 2.0, 3.0],
            duration=[0.0, 0.0, 0.0],
            description=["47", "Stimulus/S 60", "New Segment"],
        )
    )
    path = tmp_path / "trig_raw.fif"
    raw.save(path, verbose="error")
    events = io.recorded_trigger_events(io.open_recording(path))
    # The two numeric codes are extracted; "New Segment" (no digits) is dropped.
    assert events == [(1.0, 47), (2.0, 60)]


def test_recorded_trigger_events_reads_a_stim_channel(tmp_path):
    # A FIF with a STIM channel carrying codes 5 (at 1 s) and 7 (at 2 s).
    info = mne.create_info(["C3", "STI 014"], sfreq=SFREQ, ch_types=["eeg", "stim"])
    data = np.zeros((2, int(3 * SFREQ)))
    data[1, int(1.0 * SFREQ)] = 5
    data[1, int(2.0 * SFREQ)] = 7
    raw = mne.io.RawArray(data, info, verbose="error")
    path = tmp_path / "stim_raw.fif"
    raw.save(path, verbose="error")
    events = io.recorded_trigger_events(io.open_recording(path))
    assert (1.0, 5) in events
    assert (2.0, 7) in events


def test_recorded_trigger_events_empty_when_no_triggers(fif_path):
    # The fixture's only annotation is "Arousal" (no digits) and it has no stim
    # channel — an LSL-only-style file with nothing to match.
    assert io.recorded_trigger_events(io.open_recording(fif_path)) == []


def test_trigger_events_data_relative_when_anonymized_with_first_samp(tmp_path):
    # An anonymized recording drops meas_date but keeps a non-zero first_samp;
    # MNE bakes first_time into the stored onsets, so the data-relative time must
    # still come off (matching the stim-channel timebase), not be left too large.
    info = mne.create_info(["C3", "STI 014"], sfreq=SFREQ, ch_types=["eeg", "stim"])
    data = np.zeros((2, int(5 * SFREQ)))
    data[1, int(1.0 * SFREQ)] = 9  # a stim code at data-second 1.0
    raw = mne.io.RawArray(data, info, first_samp=int(2.0 * SFREQ), verbose="error")
    raw.set_annotations(
        mne.Annotations(onset=[1.0], duration=[0.0], description=["9"])
    )  # an annotation code at data-second 1.0 (orig_time None, meas_date None)
    path = tmp_path / "anon_raw.fif"
    raw.save(path, verbose="error")
    events = io.recorded_trigger_events(io.open_recording(path))
    # Both the annotation code and the stim code land at 1.0 s — consistent, not
    # offset by first_time (2.0 s).
    assert events.count((1.0, 9)) == 2
