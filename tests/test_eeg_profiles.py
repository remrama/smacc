"""Tests for the EEG view-profile model and its JSON file (#177).

Pure model + I/O, no Qt and no MNE — like the annotations tests.
"""

from __future__ import annotations

import json

import pytest

from smacc.eeg.dsp import FilterSpec
from smacc.eeg.profiles import (
    KIND,
    SCHEMA_VERSION,
    ViewProfile,
    read_view_profile,
    write_view_profile,
)


def test_profile_round_trips_through_json(tmp_path):
    profile = ViewProfile(
        channels=("C3", "C4", "EMG"),
        base_scale_uv=120.0,
        type_scales={"emg": 250.0},
        base_filter=FilterSpec(highpass=0.3, lowpass=35.0),
        type_filters={"emg": FilterSpec(highpass=10.0, notch=60.0)},
        window_seconds=60.0,
        epoch_seconds=20.0,
    )
    path = tmp_path / "montage.smacc-view.json"
    write_view_profile(profile, path)
    assert read_view_profile(path) == profile


def test_defaults_round_trip(tmp_path):
    path = tmp_path / "empty.smacc-view.json"
    write_view_profile(ViewProfile(), path)
    assert read_view_profile(path) == ViewProfile()


def test_written_file_records_kind_and_version(tmp_path):
    path = tmp_path / "m.smacc-view.json"
    write_view_profile(ViewProfile(), path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["kind"] == KIND
    assert payload["schema_version"] == SCHEMA_VERSION


def test_reading_a_foreign_json_is_rejected(tmp_path):
    path = tmp_path / "not-a-profile.json"
    path.write_text(json.dumps({"kind": "something-else"}), encoding="utf-8")
    with pytest.raises(ValueError, match="view profile"):
        read_view_profile(path)


def test_reading_non_json_is_rejected(tmp_path):
    path = tmp_path / "junk.json"
    path.write_text("not json at all", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON"):
        read_view_profile(path)


def test_a_bom_from_notepad_is_tolerated(tmp_path):
    # A profile re-saved in Notepad comes back with a UTF-8 BOM; reading must
    # still recognize it rather than choke on the first byte.
    path = tmp_path / "m.smacc-view.json"
    write_view_profile(ViewProfile(epoch_seconds=20.0), path)
    raw = path.read_bytes()
    path.write_bytes(b"\xef\xbb\xbf" + raw)
    assert read_view_profile(path).epoch_seconds == 20.0
