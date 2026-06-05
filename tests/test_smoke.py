"""Lightweight import/smoke tests that need no GUI, audio, or parallel port."""

from __future__ import annotations

import smacc
from smacc import config


def test_package_exposes_version():
    assert isinstance(smacc.__version__, str)
    assert smacc.__version__.count(".") == 2  # e.g. "0.0.7"


def test_config_version_is_single_sourced():
    # config.VERSION must track the package __version__ (no drift).
    assert config.VERSION == smacc.__version__


def test_portcodes_are_unique_ints():
    codes = list(config.PPORT_CODES.values())
    assert all(isinstance(code, int) for code in codes)
    assert len(codes) == len(set(codes))
