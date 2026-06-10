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


def test_recording_started_is_a_default_manual_marker():
    # #60: the "Start recording" button comes from a manual registry event so it
    # auto-appears in the grid, sends a portcode, and persists in a study.
    rec = {e.key: e for e in events.default_events()}["RecordingStarted"]
    assert rec.label == "Start recording"
    assert rec.code == 51
    assert rec.category == "manual"
    assert rec.trigger is True
    assert rec.increment is False


def test_chat_events_are_log_only_by_default():
    # #92: a typed exchange is rapid and conversational, so neither chat direction
    # triggers (or previews) unless a study flips it on; the codes extend the
    # control band right after the intercom pair.
    defs = {e.key: e for e in events.default_events()}
    sent, received = defs["ChatMessageSent"], defs["ChatMessageReceived"]
    assert (sent.code, received.code) == (69, 70)
    for event in (sent, received):
        assert event.category == "control"  # no event-grid button
        assert event.trigger is False
        assert event.preview is False
        assert event.increment is False


def test_survey_submitted_is_log_only_by_default():
    """Submission (#114) is recorded but not triggered unless a study opts in."""
    by_key = {e.key: e for e in events.default_events()}
    submitted = by_key["SurveySubmitted"]
    assert submitted.code == 71
    assert submitted.trigger is False
    assert submitted.preview is True
    assert by_key["SurveyOpened"].trigger is True  # the open still marks the EEG


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
        set(d) == {"key", "code", "trigger", "preview", "increment"} for d in compact
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


def test_validate_events_requires_label():
    errors, _ = events.validate_events([events.EventDef("k", "", 50)])
    assert any("label" in e.lower() for e in errors)


# ----- custom events --------------------------------------------------------


def test_default_events_are_all_builtin():
    assert all(e.builtin for e in events.default_events())


def test_make_custom_event_is_manual_and_unique():
    existing = {e.key for e in events.default_events()}
    e1 = events.make_custom_event("My Event", 70, existing)
    assert e1.builtin is False
    assert e1.category == "manual"
    assert e1.key.startswith("customMyEvent")
    e2 = events.make_custom_event("My Event", 71, existing | {e1.key})
    assert e2.key != e1.key  # a uniqueness suffix is appended on collision


def test_custom_event_round_trips_through_persistence():
    custom = events.make_custom_event(
        "Spont arousal", 70, set(), tooltip="hi", increment=True
    )
    registry = events.default_events() + [custom]
    compact = events.events_to_list(registry)
    # The custom entry persists its full definition (incl. builtin=False)...
    custom_dict = next(d for d in compact if d["key"] == custom.key)
    assert custom_dict["builtin"] is False
    assert custom_dict["label"] == "Spont arousal"
    assert custom_dict["category"] == "manual"
    # ...while built-ins stay compact (no label key).
    builtin_dict = next(d for d in compact if d["key"] == "REMDetected")
    assert "label" not in builtin_dict
    # Round-trip reconstructs the custom event.
    merged = {e.key: e for e in events.merge_event_codes(compact)}
    assert merged[custom.key].label == "Spont arousal"
    assert merged[custom.key].increment is True
    assert merged[custom.key].builtin is False


def test_merge_ignores_unknown_key_without_custom_flag():
    # An unknown key not marked builtin:false is dropped (e.g. a removed built-in),
    # so stale entries don't resurrect as phantom buttons.
    merged = {
        e.key: e for e in events.merge_event_codes([{"key": "Ghost", "code": 90}])
    }
    assert "Ghost" not in merged


# ----- biocal events (#78) ----------------------------------------------------


def test_biocal_events_registered_with_table_codes():
    from smacc import biocals

    registry = {e.key: e for e in events.default_events()}
    for b in biocals.default_biocals():
        event = registry[b.event]
        assert event.code == b.code
        assert event.category == "biocal"
        assert event.builtin
        assert event.trigger and event.preview and not event.increment
    for key, code in [
        (biocals.SEQUENCE_STARTED_EVENT, 105),
        (biocals.SEQUENCE_STOPPED_EVENT, 106),
        (biocals.CANCELLED_EVENT, 107),
        (biocals.COMPLETED_EVENT, 108),
    ]:
        assert registry[key].code == code
        assert registry[key].category == "biocal"


def test_biocal_events_stay_out_of_the_manual_grid():
    # The Event-logging grid auto-builds from category == "manual"; biocals have
    # their own window, so none may leak into the grid.
    manual = [e for e in events.default_events() if e.category == "manual"]
    assert not any(e.key.startswith("Biocal") for e in manual)


def test_biocal_events_merge_into_older_studies():
    # A pre-v7 .smacc persisted no biocal entries; merging its (older) compact
    # list over the defaults must still yield the full biocal registry.
    older = [{"key": "REMDetected", "code": 41}]
    merged = {e.key: e for e in events.merge_event_codes(older)}
    assert "BiocalEyesOpen" in merged
    assert merged["BiocalEyesOpen"].code == 110


def test_visual_pair_brackets_the_stimulus():
    # Looping/long visual cues need an offset marker for EEG alignment, so the
    # registry pairs VisualStarted with a VisualStopped at the next free code
    # (68: SurveyOpened took 67 before the pair existed).
    registry = {e.key: e for e in events.default_events()}
    assert registry["VisualStarted"].label == "Visual started"
    assert registry["VisualStarted"].code == 66
    stop = registry["VisualStopped"]
    assert stop.code == 68
    assert stop.category == "control"
    assert stop.trigger and stop.preview and not stop.increment


def test_visual_stopped_merges_into_older_studies():
    # A study saved before the pair existed gains the stop event on load.
    older = [{"key": "VisualStarted", "code": 66}]
    merged = {e.key: e for e in events.merge_event_codes(older)}
    assert merged["VisualStopped"].code == 68
