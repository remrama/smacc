"""Tests for tools/make_versionfile.py (the PyInstaller VSVersionInfo generator).

``tools/`` is not an importable package, so the module is loaded by path.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "tools" / "make_versionfile.py"
_spec = importlib.util.spec_from_file_location("make_versionfile", _PATH)
assert _spec is not None and _spec.loader is not None
make_versionfile = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(make_versionfile)


def test_version_tuple_pads_to_four():
    assert make_versionfile.version_tuple("0.1.0") == (0, 1, 0, 0)


def test_version_tuple_drops_prerelease_suffix():
    # VS_FIXEDFILEINFO is numeric-only: "1.0.0-rc.1" -> (1, 0, 0, 0).
    assert make_versionfile.version_tuple("1.0.0-rc.1") == (1, 0, 0, 0)


def test_render_keeps_the_full_version_string():
    out = make_versionfile.render("1.0.0-rc.1")
    # The numeric resource drops the suffix; the string fields keep it.
    assert "filevers=(1, 0, 0, 0)" in out
    assert '"1.0.0-rc.1"' in out
