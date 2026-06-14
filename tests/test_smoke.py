"""Lightweight import/smoke tests that need no GUI, audio, or parallel port."""

from __future__ import annotations

import smacc
from smacc import config, events


def test_package_exposes_version():
    assert isinstance(smacc.__version__, str)
    # X.Y.Z, with an optional pre-release suffix (e.g. "1.0.0-rc.1").
    core = smacc.__version__.split("-", 1)[0]
    assert core.count(".") == 2


def test_config_version_is_single_sourced():
    # config.VERSION must track the package __version__ (no drift).
    assert config.VERSION == smacc.__version__


def test_default_event_codes_are_unique_ints():
    codes = [e.code for e in events.default_events()]
    assert all(isinstance(code, int) for code in codes)
    triggered = [e.code for e in events.default_events() if e.triggered]
    assert len(triggered) == len(set(triggered))  # no triggered-code collisions
