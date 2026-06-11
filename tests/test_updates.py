"""Tests for the manual update check: version logic, checker thread, dialogs."""

from __future__ import annotations

import io
import json
import urllib.error

import pytest
from PyQt6 import QtGui, QtWidgets

from smacc import launcher as launcher_mod
from smacc import updates
from smacc.config import VERSION
from smacc.launcher import LauncherWindow


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("v0.1.2", (0, 1, 2)),
        ("0.1.2", (0, 1, 2)),
        ("V2.0", (2, 0)),
        (" v1.2.3 ", (1, 2, 3)),
        ("v0.1.0rc1", None),  # pre-release suffixes are never used on smacc tags
        ("nightly", None),
        ("", None),
    ],
)
def test_parse_version(tag, expected):
    assert updates.parse_version(tag) == expected


@pytest.mark.parametrize(
    ("latest", "current", "newer"),
    [
        ("v0.2.0", "0.1.0", True),
        ("v0.1.0", "0.1.0", False),
        ("v0.0.9", "0.1.0", False),
        ("v0.1.1", "0.1", True),  # longer tuple wins when the prefix matches
        ("not-a-version", "0.1.0", False),  # malformed tag must never nag
        ("v1.0.0", "garbage", False),
    ],
)
def test_is_newer(latest, current, newer):
    assert updates.is_newer(latest, current) is newer


def _fake_urlopen(payload: dict):
    """A stand-in for urllib.request.urlopen returning ``payload`` as JSON."""

    def fake(request, timeout=None):
        return io.BytesIO(json.dumps(payload).encode())  # context manager + .read()

    return fake


def test_fetch_latest_release_parses_tag_and_url(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        _fake_urlopen({"tag_name": "v9.9.9", "html_url": "https://example.test/rel"}),
    )
    assert updates.fetch_latest_release() == ("v9.9.9", "https://example.test/rel")


def test_fetch_latest_release_falls_back_to_releases_page(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen({"tag_name": "v9.9.9"}))
    assert updates.fetch_latest_release() == ("v9.9.9", updates.RELEASES_URL)


def test_checker_emits_newer_result(qtbot, monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        _fake_urlopen({"tag_name": "v999.0.0", "html_url": "https://example.test/rel"}),
    )
    checker = updates.UpdateChecker()
    with qtbot.waitSignal(checker.finished, timeout=5000) as blocker:
        checker.check()
    assert blocker.args[0] == updates.UpdateResult(
        latest="v999.0.0", newer=True, url="https://example.test/rel"
    )


def test_checker_reports_failure_without_raising(qtbot, monkeypatch):
    def offline(request, timeout=None):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("urllib.request.urlopen", offline)
    checker = updates.UpdateChecker()
    with qtbot.waitSignal(checker.finished, timeout=5000) as blocker:
        checker.check()
    assert blocker.args[0] == updates.UpdateResult(
        latest=None, newer=False, url=updates.RELEASES_URL
    )


@pytest.fixture
def launcher_win(qtbot, tmp_path, monkeypatch):
    # Point preferences at a temp file so building the launcher can't touch real prefs.
    monkeypatch.setattr(launcher_mod, "preferences_path", tmp_path / "preferences.yaml")
    win = LauncherWindow(settings_path=None)
    qtbot.addWidget(win)
    return win


def test_update_dialog_offers_download_when_newer(launcher_win, monkeypatch):
    opened = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "question",
        lambda *args, **kwargs: QtWidgets.QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(
        QtGui.QDesktopServices, "openUrl", lambda url: opened.append(url.toString())
    )
    launcher_win._on_update_result(
        updates.UpdateResult(
            latest="v999.0.0", newer=True, url="https://example.test/rel"
        )
    )
    assert opened == ["https://example.test/rel"]


def test_update_dialog_respects_a_declined_download(launcher_win, monkeypatch):
    opened = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "question",
        lambda *args, **kwargs: QtWidgets.QMessageBox.StandardButton.No,
    )
    monkeypatch.setattr(
        QtGui.QDesktopServices, "openUrl", lambda url: opened.append(url.toString())
    )
    launcher_win._on_update_result(
        updates.UpdateResult(
            latest="v999.0.0", newer=True, url="https://example.test/rel"
        )
    )
    assert opened == []


def test_update_dialog_up_to_date(launcher_win, monkeypatch):
    seen = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "information",
        lambda parent, title, text: seen.append(text),
    )
    launcher_win._on_update_result(
        updates.UpdateResult(
            latest=f"v{VERSION}", newer=False, url=updates.RELEASES_URL
        )
    )
    assert seen and VERSION in seen[0] and "latest version" in seen[0]


def test_update_dialog_points_at_releases_page_when_check_fails(
    launcher_win, monkeypatch
):
    seen = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "information",
        lambda parent, title, text: seen.append(text),
    )
    launcher_win._on_update_result(
        updates.UpdateResult(latest=None, newer=False, url=updates.RELEASES_URL)
    )
    assert seen and updates.RELEASES_URL in seen[0]


def test_check_for_updates_disables_action_until_the_result_lands(
    launcher_win, qtbot, monkeypatch
):
    def offline(request, timeout=None):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("urllib.request.urlopen", offline)
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "information", lambda *args, **kwargs: None
    )
    launcher_win.check_for_updates()
    assert not launcher_win._updateAction.isEnabled()  # no stacked double-checks
    qtbot.waitUntil(lambda: launcher_win._updateAction.isEnabled(), timeout=5000)
