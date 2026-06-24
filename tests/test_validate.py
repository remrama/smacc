"""Tests for the headless `SMACC validate` command (#302)."""

from __future__ import annotations

from smacc import events, settings, validate
from smacc.paths import BUNDLED_DEFAULT_SETTINGS


def test_the_bundled_default_is_valid():
    errors, _warnings = validate.validate_file(BUNDLED_DEFAULT_SETTINGS)
    assert errors == []


def test_main_returns_zero_and_reports_valid(capsys):
    assert validate.main([str(BUNDLED_DEFAULT_SETTINGS)]) == 0
    assert "valid" in capsys.readouterr().out


def test_malformed_values_and_unknown_keys_are_errors(tmp_path):
    path = tmp_path / "bad.smacc"
    settings.save_settings(
        str(path), {"noise_volume": 9.0, "noise_color": "blue", "oops": 1}, {}
    )
    errors, _warnings = validate.validate_file(path)
    joined = " ".join(errors)
    assert "noise_volume" in joined
    assert "noise_color" in joined
    assert "oops" in joined


def test_main_returns_one_for_an_invalid_file(tmp_path, capsys):
    path = tmp_path / "bad.smacc"
    settings.save_settings(str(path), {"noise_volume": 9.0}, {})
    assert validate.main([str(path)]) == 1
    assert "error" in capsys.readouterr().out


def test_a_non_smacc_file_is_a_structural_error(tmp_path):
    path = tmp_path / "x.smacc"
    path.write_text("just: some\nrandom: yaml\n", encoding="utf-8")
    errors, _warnings = validate.validate_file(path)
    assert errors  # missing kind/schema_version/settings → fatal structural error


def test_a_duplicate_event_code_is_a_registry_error(tmp_path):
    # Uniqueness is the registry validator's job, not the per-item schema's: two
    # routed events sharing a code collide on the marker channel.
    rows = events.events_to_list(events.default_events())
    rows[1]["code"] = rows[0]["code"]  # force a duplicate among routed events
    path = tmp_path / "dup.smacc"
    settings.save_settings(str(path), {"event_codes": rows}, {})
    errors, _warnings = validate.validate_file(path)
    assert any("duplicate" in e.lower() for e in errors)


def test_a_ttl_code_above_the_safe_max_is_a_warning(tmp_path):
    rows = events.events_to_list(events.default_events())
    path = tmp_path / "warn.smacc"
    # A low safe max turns the routed default codes into soft TTL warnings, with no
    # hard error — the file is valid but flagged.
    settings.save_settings(
        str(path), {"event_codes": rows, "event_code_safe_max": 1}, {}
    )
    errors, warnings = validate.validate_file(path)
    assert errors == []
    assert warnings
