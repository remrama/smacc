"""Tests for the best-effort Windows volume readout (no value assertions).

These pass everywhere: on non-Windows / without pycaw the readers return ``None``;
on Windows they return a 0-1 scalar. Either way they must never raise.
"""

from smacc import winvolume


def test_available_returns_bool():
    assert isinstance(winvolume.available(), bool)


def test_endpoint_volume_is_none_or_unit_scalar():
    value = winvolume.endpoint_volume()
    assert value is None or (isinstance(value, float) and 0.0 <= value <= 1.0)


def test_app_volume_is_none_or_unit_scalar():
    value = winvolume.app_volume()
    assert value is None or (isinstance(value, float) and 0.0 <= value <= 1.0)
