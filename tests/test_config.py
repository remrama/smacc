"""Tests for the human-facing version string (the rolling dev build stamp, #251)."""

from smacc import config


def test_display_version_is_plain_without_a_stamp(monkeypatch):
    # A tagged release, a PR build, or a source checkout has no smacc._build, so
    # BUILD is None and the displayed version is exactly __version__.
    monkeypatch.setattr(config, "BUILD", None)
    assert config.display_version() == config.VERSION


def test_display_version_appends_the_dev_stamp(monkeypatch):
    # A rolling dev build is stamped with the commit it was built from, so a bug
    # report can be traced back to a specific main commit.
    monkeypatch.setattr(config, "BUILD", "a1b2c3d")
    assert config.display_version() == f"{config.VERSION} (dev build a1b2c3d)"
