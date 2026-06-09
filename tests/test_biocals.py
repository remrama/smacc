"""The biocal table, stack (de)serialization, and the BiocalRun engine.

Everything here is Qt-free: the engine takes an injected clock, so the whole
voice/window/sequence timing-and-marker matrix runs against fake time.
"""

from __future__ import annotations

from smacc import biocals
from smacc.biocals import BiocalRun, EmitMarker, PlayVoice, RunItem, StopVoice

# ----- the table and the default stack ----------------------------------------


def test_table_is_consistent():
    table = biocals.default_biocals()
    assert len(table) == 17
    assert len({b.key for b in table}) == 17
    assert len({b.event for b in table}) == 17
    assert len({b.code for b in table}) == 17
    for b in table:
        assert 110 <= b.code <= 126  # the reserved start-code band
        assert b.duration_s > 0
        assert b.phrase
        assert b.filename == b.key + ".wav"
    # 10 standard sleep-study biocals; 7 lucid-dreaming signal practices.
    assert sum(b.standard for b in table) == 10


def test_default_stack_repeats_eyes_closed_and_checks_standards():
    rows = biocals.default_rows()
    assert len(rows) == 18
    assert [r.key for r in rows].count("eyes_closed") == 2
    for row in rows:
        b = biocals.BIOCALS_BY_KEY[row.key]
        assert row.sequence is b.standard
        assert row.voice is True
        assert row.duration_s == b.duration_s


# ----- stack (de)serialization --------------------------------------------------


def test_rows_round_trip():
    rows = biocals.default_rows()
    rows[0].sequence = False
    rows[1].voice = False
    rows[2].duration_s = 45
    assert biocals.rows_from_list(biocals.rows_to_list(rows)) == rows


def test_rows_from_list_is_tolerant():
    assert biocals.rows_from_list(None) is None
    assert biocals.rows_from_list({"biocal": "rest"}) is None
    assert biocals.rows_from_list([]) == []  # a deliberately cleared stack
    rows = biocals.rows_from_list(
        [
            {"biocal": "no_such_biocal", "sequence": True},  # unknown: dropped
            "not a mapping",  # malformed: dropped
            {"biocal": "rest"},  # fields default to the biocal's own
            {"biocal": "blink", "duration": True},  # bool duration: default
            {"biocal": "blink", "duration": 99999},  # clamped
        ]
    )
    assert rows is not None
    assert [r.key for r in rows] == ["rest", "blink", "blink"]
    assert rows[0].sequence is True  # rest is standard
    assert rows[0].voice is True
    assert rows[0].duration_s == 60
    assert rows[1].duration_s == 10
    assert rows[2].duration_s == biocals.MAX_DURATION_S


def test_missing_voice_files(tmp_path):
    assert len(biocals.missing_voice_files(tmp_path)) == 17
    (tmp_path / "rest.wav").write_bytes(b"")
    (tmp_path / "blink.wav").write_bytes(b"")
    missing = biocals.missing_voice_files(tmp_path)
    assert len(missing) == 15
    assert "rest.wav" not in missing
    assert missing == sorted(missing)
    for b in biocals.default_biocals():
        (tmp_path / b.filename).write_bytes(b"")
    assert biocals.missing_voice_files(tmp_path) == []


def test_bundled_voice_assets_ship_complete():
    # The repo carries a recording for every biocal in the table (seeded to the
    # SMACC directory on first launch); a phrase change must re-render them.
    from smacc.paths import BUNDLED_BIOCALS_DIR

    assert biocals.missing_voice_files(BUNDLED_BIOCALS_DIR) == []


# ----- the run engine ------------------------------------------------------------


class FakeClock:
    def __init__(self, t: float = 100.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def make_item(
    key: str = "eyes_open", *, voice: bool = False, duration: float = 30.0
) -> RunItem:
    b = biocals.BIOCALS_BY_KEY[key]
    return RunItem(
        token=object(),
        key=b.key,
        event=b.event,
        label=b.label,
        voice=voice,
        duration_s=duration,
    )


def test_single_without_voice_opens_window_immediately():
    clock = FakeClock()
    run = BiocalRun(clock)
    item = make_item(duration=30)
    assert run.start_single(item) == [EmitMarker("BiocalEyesOpen")]
    assert run.phase == biocals.WINDOW
    assert run.remaining() == 30
    clock.t += 12
    assert run.tick() == []  # still inside the window
    assert run.remaining() == 18
    clock.t += 18
    assert run.tick() == [EmitMarker(biocals.COMPLETED_EVENT, "Eyes Open")]
    assert not run.active
    assert run.tick() == []  # idle ticks are no-ops


def test_voice_delays_window_until_announcement_ends():
    clock = FakeClock()
    run = BiocalRun(clock)
    assert run.start_single(make_item(voice=True, duration=10)) == [
        PlayVoice("eyes_open", "Eyes Open")
    ]
    assert run.phase == biocals.VOICE
    assert run.remaining() is None  # no window yet
    assert run.tick() == []  # time passing can't end an announcement
    clock.t += 5  # the announcement's length never eats the window
    assert run.voice_finished() == [EmitMarker("BiocalEyesOpen")]
    assert run.remaining() == 10
    assert run.voice_finished() == []  # only meaningful while announcing


def test_cancel_during_voice_stops_audio_and_never_starts_window():
    run = BiocalRun(FakeClock())
    run.start_single(make_item(voice=True))
    assert run.cancel_item() == [
        StopVoice(),
        EmitMarker(biocals.CANCELLED_EVENT, "Eyes Open"),
    ]
    assert not run.active


def test_cancel_during_window():
    clock = FakeClock()
    run = BiocalRun(clock)
    run.start_single(make_item(duration=30))
    clock.t += 5
    assert run.cancel_item() == [EmitMarker(biocals.CANCELLED_EVENT, "Eyes Open")]
    assert not run.active
    assert run.cancel_item() == []  # idle cancels are no-ops
    assert run.cancel_all() == []


def test_starting_another_biocal_replaces_the_running_one():
    run = BiocalRun(FakeClock())
    run.start_single(make_item("eyes_open"))
    actions = run.start_single(make_item("blink"))
    assert actions == [
        EmitMarker(biocals.CANCELLED_EVENT, "Eyes Open"),
        EmitMarker("BiocalBlink"),
    ]
    assert run.item is not None and run.item.key == "blink"


def test_sequence_runs_items_in_order_and_completes():
    clock = FakeClock()
    run = BiocalRun(clock)
    first, second = make_item("eyes_open", duration=30), make_item("blink", duration=10)
    actions = run.start_sequence([first, second])
    assert actions == [
        EmitMarker(biocals.SEQUENCE_STARTED_EVENT, "2 biocals"),
        EmitMarker("BiocalEyesOpen"),
    ]
    assert run.in_sequence and run.sequence_progress() == (1, 2)
    clock.t += 30
    assert run.tick() == [
        EmitMarker(biocals.COMPLETED_EVENT, "Eyes Open"),
        EmitMarker("BiocalBlink"),
    ]
    assert run.sequence_progress() == (2, 2)
    clock.t += 10
    assert run.tick() == [
        EmitMarker(biocals.COMPLETED_EVENT, "Blink"),
        EmitMarker(biocals.SEQUENCE_STOPPED_EVENT, "completed"),
    ]
    assert not run.active and run.sequence_progress() is None


def test_sequence_announcements_run_through_the_same_path():
    run = BiocalRun(FakeClock())
    actions = run.start_sequence([make_item("rest", voice=True, duration=60)])
    assert actions == [
        EmitMarker(biocals.SEQUENCE_STARTED_EVENT, "1 biocal"),
        PlayVoice("rest", "Rest"),
    ]
    assert run.voice_finished() == [EmitMarker("BiocalRest")]


def test_cancel_item_mid_sequence_skips_to_the_next():
    run = BiocalRun(FakeClock())
    run.start_sequence([make_item("eyes_open"), make_item("blink")])
    assert run.cancel_item() == [
        EmitMarker(biocals.CANCELLED_EVENT, "Eyes Open"),
        EmitMarker("BiocalBlink"),
    ]
    assert run.in_sequence and run.sequence_progress() == (2, 2)


def test_cancel_all_aborts_the_sequence():
    run = BiocalRun(FakeClock())
    run.start_sequence([make_item("eyes_open", voice=True), make_item("blink")])
    assert run.cancel_all() == [
        StopVoice(),
        EmitMarker(biocals.CANCELLED_EVENT, "Eyes Open"),
        EmitMarker(biocals.SEQUENCE_STOPPED_EVENT, "cancelled"),
    ]
    assert not run.active
    assert run.tick() == []  # nothing left queued


def test_skipping_the_last_item_closes_the_sequence_as_completed():
    # The *items* report their own fate (cancelled); the sequence bracket closes
    # normally — "cancelled" there is reserved for aborting via the sequence
    # button, so the two reasons stay distinguishable in the log.
    run = BiocalRun(FakeClock())
    run.start_sequence([make_item("eyes_open")])
    assert run.cancel_item() == [
        EmitMarker(biocals.CANCELLED_EVENT, "Eyes Open"),
        EmitMarker(biocals.SEQUENCE_STOPPED_EVENT, "completed"),
    ]
    assert not run.active


def test_empty_sequence_is_a_no_op():
    run = BiocalRun(FakeClock())
    assert run.start_sequence([]) == []
    assert not run.active
