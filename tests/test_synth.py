"""Tests for the pure tone-synthesis core in :mod:`smacc.synth` (#77)."""

from __future__ import annotations

import json

import numpy as np
import pytest
from scipy.io.wavfile import read

from smacc import synth


def test_tone_segment_has_expected_length_and_range():
    rate = 8000
    samples = synth.render_segment(synth.ToneSegment(freq=440, duration=1.0), rate)
    assert samples.dtype == np.float32
    assert samples.shape == (rate,)
    assert np.all(np.isfinite(samples))
    assert np.max(np.abs(samples)) <= 1.0


def test_tone_dominant_frequency_matches_request():
    rate = 8000
    freq = 500.0
    samples = synth.render_segment(synth.ToneSegment(freq=freq, duration=1.0), rate)
    spectrum = np.abs(np.fft.rfft(samples))
    peak_hz = np.fft.rfftfreq(samples.shape[0], 1.0 / rate)[int(np.argmax(spectrum))]
    assert peak_hz == pytest.approx(freq, abs=2.0)


def test_tone_level_scales_amplitude():
    rate = 8000
    quiet = synth.render_segment(synth.ToneSegment(440, 0.5, level=0.25), rate)
    loud = synth.render_segment(synth.ToneSegment(440, 0.5, level=1.0), rate)
    assert np.max(np.abs(loud)) > np.max(np.abs(quiet))
    assert np.max(np.abs(quiet)) == pytest.approx(0.25, abs=0.02)


def test_tone_edges_fade_to_avoid_clicks():
    rate = 44100
    samples = synth.render_segment(synth.ToneSegment(440, 0.5), rate)
    assert abs(samples[0]) < 1e-3  # ramps up from ~0
    assert abs(samples[-1]) < 1e-3  # and back down to ~0


def test_decay_makes_the_tail_quieter_than_the_onset():
    rate = 8000
    plain = synth.render_segment(synth.ToneSegment(440, 1.0), rate)
    decayed = synth.render_segment(synth.ToneSegment(440, 1.0, decay=True), rate)
    head = slice(rate // 10, rate // 5)  # past the onset fade
    tail = slice(-rate // 5, -rate // 10)
    assert np.max(np.abs(decayed[tail])) < np.max(np.abs(decayed[head]))
    # A plain tone holds its level across the same window.
    assert np.max(np.abs(plain[tail])) == pytest.approx(
        np.max(np.abs(plain[head])), abs=0.02
    )


def test_silence_segment_is_zeros_of_expected_length():
    rate = 8000
    samples = synth.render_segment(synth.SilenceSegment(duration=0.5), rate)
    assert samples.shape == (rate // 2,)
    assert np.all(samples == 0)


def test_zero_or_negative_duration_renders_empty():
    assert synth.render_segment(synth.ToneSegment(440, 0.0), 8000).shape == (0,)
    assert synth.render_segment(synth.SilenceSegment(-1.0), 8000).shape == (0,)


def test_sequence_concatenates_in_order():
    rate = 8000
    segments = [
        synth.ToneSegment(440, 0.25),
        synth.SilenceSegment(0.25),
        synth.ToneSegment(880, 0.25),
    ]
    out = synth.render_sequence(segments, rate=rate)
    assert out.dtype == np.float32
    assert out.shape == (rate * 3 // 4,)
    mid = slice(rate // 4, rate // 2)  # the silence segment in the middle
    assert np.all(out[mid] == 0)


def test_empty_sequence_is_empty_buffer():
    out = synth.render_sequence([], rate=8000)
    assert out.shape == (0,)
    assert out.dtype == np.float32


def test_normalize_scales_peak_with_headroom():
    rate = 8000
    out = synth.render_sequence(
        [synth.ToneSegment(440, 0.5, level=0.1)], rate=rate, normalize=True
    )
    assert np.max(np.abs(out)) == pytest.approx(synth.NORMALIZE_PEAK, abs=0.02)


def test_master_fades_ramp_the_whole_cue():
    rate = 8000
    out = synth.render_sequence(
        [synth.ToneSegment(440, 1.0)], rate=rate, fade_in=0.2, fade_out=0.2
    )
    assert abs(out[0]) < 1e-3
    assert abs(out[-1]) < 1e-3
    # The quarter-second mark is mid-fade-in, so quieter than the sustained middle.
    assert np.max(np.abs(out[: rate // 5])) < np.max(np.abs(out[rate // 2 :]))


def test_output_is_clipped_into_range():
    rate = 8000
    # Two stacked-level tones can't exceed 1.0 individually, but force a clip check
    # by requesting an over-unity level and confirming the result still bounds.
    out = synth.render_sequence([synth.ToneSegment(440, 0.5, level=4.0)], rate=rate)
    assert np.max(np.abs(out)) <= 1.0


def test_total_duration_sums_segments_and_ignores_negatives():
    segments = [
        synth.ToneSegment(440, 1.0),
        synth.SilenceSegment(0.5),
        synth.SilenceSegment(-2.0),  # clamped to 0
    ]
    assert synth.total_duration(segments) == pytest.approx(1.5)


def test_export_wav_writes_a_readable_pcm16_file(tmp_path):
    rate = 8000
    out = synth.render_sequence([synth.ToneSegment(440, 0.5)], rate=rate)
    path = tmp_path / "cue.wav"
    synth.export_wav(path, out, rate)
    assert path.is_file()
    read_rate, data = read(path)
    assert read_rate == rate
    assert data.dtype == np.int16
    assert data.shape[0] == out.shape[0]


def test_render_sequence_rejects_bad_rate():
    with pytest.raises(ValueError):
        synth.render_sequence([synth.ToneSegment(440, 0.5)], rate=0)


# ----- repeat_segments (#137) -------------------------------------------------


def test_repeat_segments_expands_with_gaps():
    pattern = [synth.ToneSegment(440, 0.1)]
    out = synth.repeat_segments(pattern, 3, gap=0.05)
    assert len(out) == 5  # tone, gap, tone, gap, tone
    assert isinstance(out[0], synth.ToneSegment)
    assert isinstance(out[1], synth.SilenceSegment)
    assert out[1].duration == 0.05
    assert synth.total_duration(out) == pytest.approx(0.4)


def test_repeat_segments_count_one_is_the_pattern_itself():
    pattern = [synth.ToneSegment(440, 0.1), synth.SilenceSegment(0.2)]
    assert synth.repeat_segments(pattern, 1, gap=0.5) == pattern


def test_repeat_segments_zero_gap_inserts_no_silence():
    out = synth.repeat_segments([synth.ToneSegment(440, 0.1)], 3, gap=0.0)
    assert len(out) == 3
    assert all(isinstance(seg, synth.ToneSegment) for seg in out)


def test_repeat_segments_rejects_bad_count():
    with pytest.raises(ValueError):
        synth.repeat_segments([synth.ToneSegment(440, 0.1)], 0)


# ----- CueDesign (#137) ---------------------------------------------------------


def _example_design() -> synth.CueDesign:
    return synth.CueDesign(
        segments=[
            synth.ToneSegment(freq=600, duration=0.1, level=0.4, decay=True),
            synth.SilenceSegment(duration=0.05),
        ],
        name="pips",
        fade_in=0.01,
        fade_out=0.02,
        normalize=True,
        repeat_count=3,
        repeat_gap=0.2,
    )


def test_cue_design_render_matches_manual_sequence():
    design = _example_design()
    rate = 8000
    manual = synth.render_sequence(
        synth.repeat_segments(design.segments, 3, gap=0.2),
        rate=rate,
        fade_in=design.fade_in,
        fade_out=design.fade_out,
        normalize=True,
    )
    assert np.array_equal(design.render(rate), manual)


def test_cue_design_total_duration_includes_repeats():
    design = _example_design()
    # 3 × (0.1 + 0.05) pattern + 2 × 0.2 gaps
    assert design.total_duration() == pytest.approx(0.85)


def test_cue_design_round_trips_through_dict():
    design = _example_design()
    data = design.to_dict()
    json.dumps(data)  # must be JSON-serializable as-is
    assert synth.CueDesign.from_dict(data) == design


def test_cue_design_from_dict_rejects_bad_input():
    good = _example_design().to_dict()
    for bad in (
        "not a dict",
        {**good, "version": 99},
        {**good, "segments": []},
        {**good, "segments": [{"type": "noise", "duration": 1.0}]},
        {**good, "segments": [{"type": "tone"}]},  # missing freq/duration
        {**good, "repeat_count": 0},
        {**good, "fade_in": "loud"},
    ):
        with pytest.raises(ValueError):
            synth.CueDesign.from_dict(bad)
