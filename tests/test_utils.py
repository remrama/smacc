"""Tests for the pure helpers in :mod:`smacc.utils`."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from scipy.io.wavfile import read, write

from smacc import utils

# ----- index_of_device (restoring a saved device selection) -----------------


def test_index_of_device_finds_exact_match():
    devices = ["Speakers, Windows WASAPI", "Headphones, Windows WASAPI"]
    assert utils.index_of_device(devices, "Headphones, Windows WASAPI") == 1


def test_index_of_device_returns_none_when_absent():
    # An unplugged saved device isn't in the current list -> caller flags it.
    assert utils.index_of_device(["Speakers, Windows WASAPI"], "Old mic") is None


def test_index_of_device_blank_or_missing_saved_is_none():
    # No prior selection (blank/None) means "leave the default selected".
    assert utils.index_of_device(["A", "B"], "") is None
    assert utils.index_of_device(["A", "B"], None) is None


def test_index_of_device_matches_first_of_duplicate_names():
    # Two of the same model report identical names; resolve to the first row.
    assert utils.index_of_device(["Mic", "Mic"], "Mic") == 0


def test_index_of_device_empty_candidates_is_none():
    assert utils.index_of_device([], "Anything") is None


def test_index_of_device_new_bare_name_matches_bare_candidate():
    # The current world: enumeration advertises bare names and a fresh binding
    # stored the same bare name, so it resolves directly.
    candidates = ["Speakers (USB Audio)", "Headphones"]
    assert utils.index_of_device(candidates, "Headphones") == 1


def test_index_of_device_old_suffixed_binding_matches_bare_candidate():
    # Backward-compat: a binding saved by an older SMACC carries the ", Windows
    # WASAPI" suffix, but enumeration now lists the bare name. The suffix is
    # normalized away on both sides, so the old .smacc still resolves.
    candidates = ["Speakers (USB Audio)", "Headphones"]
    assert utils.index_of_device(candidates, "Headphones, Windows WASAPI") == 1


def test_index_of_device_bare_binding_matches_legacy_suffixed_candidate():
    # The symmetric case (defensive): even if a candidate still carried the suffix,
    # a bare saved value would match it.
    candidates = ["Speakers (USB Audio), Windows WASAPI"]
    assert utils.index_of_device(candidates, "Speakers (USB Audio)") == 0


def test_note_returns_int16_of_expected_length():
    rate = 8000
    duration = 1
    data = utils.note(freq=440, duration=duration, amp=1e4, rate=rate)
    assert data.dtype == np.int16
    assert data.shape == (duration * rate,)
    assert np.all(np.isfinite(data))


@pytest.mark.parametrize(
    "noise_func",
    [
        utils.white_noise,
        utils.pink_noise,
        utils.brownian_noise,
        utils.blue_noise,
        utils.violet_noise,
    ],
)
def test_noise_generators_produce_finite_samples(noise_func):
    n = 4096
    samples = noise_func(n)
    assert isinstance(samples, np.ndarray)
    # irfft of an (n // 2 + 1) spectrum yields n real samples.
    assert samples.shape == (n,)
    assert np.all(np.isfinite(samples))


def test_get_smacc_directory_uses_env_var(tmp_path, monkeypatch):
    target = tmp_path / "smacc_root"
    monkeypatch.delenv("SMACC_DATA_DIRECTORY", raising=False)
    monkeypatch.setenv("SMACC_DIRECTORY", str(target))
    result = utils.get_smacc_directory()
    assert result == target
    assert result.is_dir()


def test_get_smacc_directory_falls_back_to_legacy_env_var(tmp_path, monkeypatch):
    target = tmp_path / "legacy_root"
    monkeypatch.delenv("SMACC_DIRECTORY", raising=False)
    monkeypatch.setenv("SMACC_DATA_DIRECTORY", str(target))
    result = utils.get_smacc_directory()
    assert result == target
    assert result.is_dir()


def test_get_smacc_directory_prefers_new_env_var(tmp_path, monkeypatch):
    new = tmp_path / "new_root"
    monkeypatch.setenv("SMACC_DIRECTORY", str(new))
    monkeypatch.setenv("SMACC_DATA_DIRECTORY", str(tmp_path / "legacy_root"))
    assert utils.get_smacc_directory() == new


def test_wav_round_trip(tmp_path):
    rate = 8000
    tone = utils.note(freq=261.63, duration=1, amp=1e4, rate=rate)
    wav_path = tmp_path / "tone.wav"
    write(wav_path, rate, tone)
    read_rate, read_data = read(wav_path)
    assert read_rate == rate
    np.testing.assert_array_equal(read_data, tone)


def test_ensure_wav_converts_non_wav(tmp_path):
    # FLAC is lossless, so the decoded WAV should match the source samples exactly.
    rate = 8000
    tone = utils.note(freq=261.63, duration=1, amp=1e4, rate=rate)
    flac_path = tmp_path / "tone.flac"
    sf.write(flac_path, tone, rate)
    wav_path = utils.ensure_wav(flac_path, tmp_path)
    assert wav_path != flac_path
    assert wav_path.suffix == ".wav"
    read_rate, read_data = read(wav_path)
    assert read_rate == rate
    np.testing.assert_array_equal(read_data, tone)


def test_ensure_wav_passes_through_wav(tmp_path):
    rate = 8000
    tone = utils.note(freq=440, duration=1, amp=1e4, rate=rate)
    wav_path = tmp_path / "tone.wav"
    write(wav_path, rate, tone)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    result = utils.ensure_wav(wav_path, cache_dir)
    assert result == wav_path  # returned unchanged
    assert list(cache_dir.iterdir()) == []  # nothing written to the cache


def test_ensure_wav_reuses_cached_conversion(tmp_path):
    rate = 8000
    tone = utils.note(freq=329.63, duration=1, amp=1e4, rate=rate)
    flac_path = tmp_path / "tone.flac"
    sf.write(flac_path, tone, rate)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    first = utils.ensure_wav(flac_path, cache_dir)
    mtime = first.stat().st_mtime_ns
    second = utils.ensure_wav(flac_path, cache_dir)
    assert second == first
    assert second.stat().st_mtime_ns == mtime  # cache hit, not re-decoded


def test_generate_demo_cues_writes_playable_wavs(tmp_path):
    paths = utils.generate_demo_cues(tmp_path)
    assert len(paths) == len(utils.DEMO_CUES)
    for path in paths:
        assert path.parent == tmp_path
        assert path.name.startswith("demo-")
        assert path.suffix == ".wav"
        rate, data = read(path)
        assert rate == utils.DEMO_RATE
        assert data.dtype == np.int16
        assert data.shape[0] > 0
        assert np.all(np.isfinite(data))


def test_seed_demo_cues_copies_bundled_and_fills_gaps(tmp_path):
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    rate = 8000
    tone = utils.note(freq=440, duration=1, amp=1e4, rate=rate)
    write(bundled / "demo-chord.wav", rate, tone)  # a shipped synth demo
    write(bundled / "demo-birdsong.wav", rate, tone)  # a user-supplied clip
    cues = tmp_path / "cues"
    utils.seed_demo_cues(cues, bundled)
    assert (cues / "demo-chord.wav").exists()  # bundled copied
    assert (cues / "demo-birdsong.wav").exists()  # bundled (non-synth) copied
    for name in utils.DEMO_CUES:  # synth demos absent from the bundle are generated
        assert (cues / name).exists()


def test_seed_demo_cues_generates_without_a_bundle(tmp_path):
    cues = tmp_path / "cues"
    utils.seed_demo_cues(cues, tmp_path / "missing")  # bundled dir does not exist
    for name in utils.DEMO_CUES:
        assert (cues / name).exists()


def test_seed_demo_cues_coexists_with_user_files_and_restores(tmp_path):
    cues = tmp_path / "cues"
    cues.mkdir()
    rate = 8000
    write(cues / "mysong.wav", rate, utils.note(440, 1, 1e4, rate))
    user_bytes = (cues / "mysong.wav").read_bytes()
    utils.generate_demo_cues(cues)  # all demos present
    kept = cues / "demo-chord.wav"
    kept_bytes = kept.read_bytes()
    (cues / "demo-chime.wav").unlink()  # user deleted one demo
    utils.seed_demo_cues(cues, tmp_path / "missing")
    assert (cues / "mysong.wav").read_bytes() == user_bytes  # user file untouched
    assert (cues / "demo-chime.wav").exists()  # deleted demo restored
    assert kept.read_bytes() == kept_bytes  # existing demo not overwritten


def test_committed_demo_assets_match_generator():
    """The committed demo WAVs must not drift from the generator that made them."""
    assets_dir = (
        Path(__file__).resolve().parents[1] / "src" / "smacc" / "assets" / "cues"
    )
    for name, synth in utils.DEMO_CUES.items():
        committed = assets_dir / name
        assert committed.is_file(), f"missing committed demo asset: {name}"
        rate, data = read(committed)
        expected = synth(utils.DEMO_RATE)
        assert rate == utils.DEMO_RATE
        assert data.shape == expected.shape
        # Tolerance: np.sin/np.exp rounding can differ by ~1 LSB across platforms,
        # but a real edit to a synth function diverges by far more than this.
        diff = np.abs(data.astype(np.int64) - expected.astype(np.int64))
        assert diff.max() <= 16


def test_read_loop_within_bounds_returns_slice():
    buf = np.arange(10, dtype=np.float32)
    chunk, pos = utils.read_loop(buf, 2, 4)
    np.testing.assert_array_equal(chunk, [2, 3, 4, 5])
    assert pos == 6


def test_read_loop_exact_fit_wraps_position_to_zero():
    buf = np.arange(10, dtype=np.float32)
    chunk, pos = utils.read_loop(buf, 6, 4)
    np.testing.assert_array_equal(chunk, [6, 7, 8, 9])
    assert pos == 0


def test_read_loop_wraps_past_end():
    buf = np.arange(10, dtype=np.float32)
    chunk, pos = utils.read_loop(buf, 8, 4)
    np.testing.assert_array_equal(chunk, [8, 9, 0, 1])
    assert pos == 2


def test_read_loop_handles_frames_longer_than_buffer():
    buf = np.arange(4, dtype=np.float32)
    chunk, pos = utils.read_loop(buf, 2, 10)
    np.testing.assert_array_equal(chunk, [2, 3, 0, 1, 2, 3, 0, 1, 2, 3])
    assert pos == 0


def test_normalize_audio_scales_to_peak():
    out = utils.normalize_audio(np.array([0, -2, 1], dtype=np.float64), peak=0.5)
    assert out.dtype == np.float32
    assert np.isclose(np.max(np.abs(out)), 0.5)


def test_normalize_audio_handles_silence():
    out = utils.normalize_audio(np.zeros(5, dtype=np.float32))
    assert out.dtype == np.float32
    assert np.all(out == 0)


def test_resample_to_noop_when_rates_match():
    sig = np.arange(100, dtype=np.float32)
    out = utils.resample_to(sig, 44100, 44100)
    assert out.dtype == np.float32
    np.testing.assert_array_equal(out, sig)


def test_resample_to_changes_length_by_ratio():
    sig = np.zeros(1000, dtype=np.float32)
    out = utils.resample_to(sig, 8000, 16000)
    assert out.dtype == np.float32
    assert abs(out.shape[0] - 2000) <= 2  # ~2x as many samples at 2x the rate


@pytest.mark.parametrize("text", ["", "   ", "\t\n"])
def test_normalize_survey_url_blank_returns_empty(text):
    assert utils.normalize_survey_url(text) == ""


def test_normalize_survey_url_adds_https_when_scheme_missing():
    assert (
        utils.normalize_survey_url("example.com/survey") == "https://example.com/survey"
    )


@pytest.mark.parametrize(
    "url", ["https://example.com", "http://example.com", "ftp://host/x"]
)
def test_normalize_survey_url_keeps_existing_scheme(url):
    assert utils.normalize_survey_url(url) == url


def test_normalize_survey_url_strips_surrounding_whitespace():
    assert (
        utils.normalize_survey_url("  https://example.com  ") == "https://example.com"
    )


# ----- elapsed-time formatting (#60) ----------------------------------------


@pytest.mark.parametrize(
    "seconds, expected",
    [
        (0, "00:00:00"),
        (5, "00:00:05"),
        (65, "00:01:05"),
        (3661, "01:01:01"),
        (90061, "25:01:01"),  # past 24h keeps counting hours, never wraps
    ],
)
def test_format_elapsed_renders_hms(seconds, expected):
    assert utils.format_elapsed(timedelta(seconds=seconds)) == expected


def test_format_elapsed_truncates_subseconds_and_clamps_negative():
    assert utils.format_elapsed(timedelta(seconds=5, milliseconds=999)) == "00:00:05"
    assert utils.format_elapsed(timedelta(seconds=-5)) == "00:00:00"


# ----- random demo-cue prefill (#65) ----------------------------------------


def test_pick_random_demo_cue_returns_a_seeded_demo(tmp_path):
    cues = tmp_path / "cues"
    utils.seed_demo_cues(cues, tmp_path / "missing")  # writes the synth demo-*.wav
    picked = utils.pick_random_demo_cue(cues)
    assert picked is not None
    assert picked.parent == cues
    assert picked.name.startswith("demo-")
    assert picked.suffix.lower() in utils.AUDIO_SUFFIXES


def test_pick_random_demo_cue_ignores_non_demo_user_files(tmp_path):
    cues = tmp_path / "cues"
    cues.mkdir()
    write(cues / "mysong.wav", 8000, utils.note(440, 1, 1e4, 8000))  # not a demo-
    assert utils.pick_random_demo_cue(cues) is None


def test_pick_random_demo_cue_none_when_dir_missing(tmp_path):
    assert utils.pick_random_demo_cue(tmp_path / "does-not-exist") is None
