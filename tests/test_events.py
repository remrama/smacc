"""Tests for the configurable event-marker registry (no GUI/LSL needed)."""

from smacc import events


def test_default_events_codes_unique_and_8bit():
    defs = events.default_events()
    for e in defs:
        assert isinstance(e.code, int) and not isinstance(e.code, bool)
        assert events.CODE_MIN <= e.code <= events.CODE_MAX
    keys = [e.key for e in defs]
    assert len(keys) == len(set(keys))  # unique keys
    triggered = [e.code for e in defs if e.trigger]
    assert len(triggered) == len(set(triggered))  # no triggered-code collisions


def test_default_events_validate_clean():
    errors, warnings = events.validate_events(events.default_events())
    assert errors == []
    assert warnings == []


def test_dream_start_increments_and_others_dont():
    defs = {e.key: e for e in events.default_events()}
    start = defs["DreamReportStarted"]
    assert start.increment is True
    assert events.runtime_code(start, 1) == start.code
    assert events.runtime_code(start, 2) == start.code + 1
    assert events.runtime_code(start, 3) == start.code + 2
    # A non-incrementing event ignores the ordinal.
    stopped = defs["DreamReportStopped"]
    assert events.runtime_code(stopped, 5) == stopped.code


def test_runtime_code_clamps_at_255():
    e = events.EventDef("X", "X", 254, increment=True)
    assert events.runtime_code(e, 1) == 254
    assert events.runtime_code(e, 2) == 255
    assert events.runtime_code(e, 3) == 255  # clamped; never exceeds the 8-bit max


def test_merge_event_codes_none_yields_defaults():
    merged = events.merge_event_codes(None)
    assert [e.key for e in merged] == [e.key for e in events.default_events()]
    assert [e.code for e in merged] == [e.code for e in events.default_events()]


def test_merge_event_codes_overlays_overrides():
    merged = {
        e.key: e
        for e in events.merge_event_codes(
            [{"key": "REMDetected", "code": 99, "trigger": False}]
        )
    }
    assert merged["REMDetected"].code == 99
    assert merged["REMDetected"].trigger is False
    assert merged["Clapper"].code == 49  # untouched events keep their defaults


def test_merge_event_codes_ignores_unknown_keys():
    merged = {
        e.key: e
        for e in events.merge_event_codes([{"key": "NotARealEvent", "code": 123}])
    }
    assert "NotARealEvent" not in merged
    assert len(merged) == len(events.default_events())  # still the full default set


def test_merge_event_codes_coerces_types():
    # YAML / hand edits may yield stringy/inty values; merge should coerce them.
    merged = {
        e.key: e
        for e in events.merge_event_codes(
            [{"key": "Clapper", "code": "49", "trigger": 1}]
        )
    }
    assert merged["Clapper"].code == 49
    assert merged["Clapper"].trigger is True


def test_events_to_list_is_compact_and_round_trips():
    compact = events.events_to_list(events.default_events())
    assert all(
        set(d) == {"key", "code", "trigger", "log", "increment"} for d in compact
    )
    merged = {e.key: e for e in events.merge_event_codes(compact)}
    for e in events.default_events():
        assert merged[e.key].code == e.code
        assert merged[e.key].trigger == e.trigger


def test_validate_events_rejects_out_of_range_and_dupes():
    errors, _ = events.validate_events([events.EventDef("A", "A", 0)])
    assert errors  # 0 is below CODE_MIN

    dupes = [
        events.EventDef("A", "A", 50, trigger=True),
        events.EventDef("B", "B", 50, trigger=True),
    ]
    errors, _ = events.validate_events(dupes)
    assert errors  # two triggered events share code 50


def test_validate_events_allows_dupe_when_not_triggered():
    pair = [
        events.EventDef("A", "A", 50, trigger=True),
        events.EventDef("B", "B", 50, trigger=False),
    ]
    errors, _ = events.validate_events(pair)
    assert errors == []  # only one can ever be sent, so no real collision


def test_validate_events_warns_above_safe_max():
    errors, warnings = events.validate_events(
        [events.EventDef("A", "A", 200, trigger=True)], safe_max=127
    )
    assert errors == []
    assert warnings  # 200 > safe_max 127 is a soft warning, not an error


def test_validate_events_warns_on_increment_band_overlap():
    defs = [
        events.EventDef("Start", "Start", 60, trigger=True, increment=True),
        events.EventDef("Other", "Other", 62, trigger=True),
    ]
    _, warnings = events.validate_events(defs)
    assert warnings  # the 60..255 band overlaps Other's code 62
