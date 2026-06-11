"""Manual check for a newer SMACC release on GitHub (#116).

The Launcher's **File › Check for updates…** action is the only caller, and the
check is deliberately manual-only: lab machines are often offline, and a study
typically pins one SMACC version for its whole run, so the app never phones home
or nags on its own. The check asks the GitHub API for the latest (non-pre-release)
release and hands the user to the browser for the download — SMACC does not
download or install anything itself.
"""

from __future__ import annotations

import json
import threading
import urllib.request
from dataclasses import dataclass

from PyQt6 import QtCore

from .config import VERSION

# Human-facing fallback when the API can't be reached or gives no usable URL.
RELEASES_URL = "https://github.com/remrama/smacc/releases"
# The newest release not marked Pre-release (404 until one exists).
_LATEST_API_URL = "https://api.github.com/repos/remrama/smacc/releases/latest"
_TIMEOUT_S = 10.0


@dataclass(frozen=True)
class UpdateResult:
    """Outcome of one update check, delivered to the GUI thread."""

    latest: str | None  # the latest release tag (e.g. "v0.1.2"); None if check failed
    newer: bool  # that tag parses as strictly newer than the running version
    url: str  # where to get it (the release's page, else RELEASES_URL)


def parse_version(tag: str) -> tuple[int, ...] | None:
    """``"v0.1.2"`` → ``(0, 1, 2)``; ``None`` for anything not dotted numbers."""
    parts = tag.strip().lstrip("vV").split(".")
    try:
        return tuple(int(part) for part in parts)
    except ValueError:
        return None


def is_newer(latest_tag: str, current: str = VERSION) -> bool:
    """True if ``latest_tag`` is strictly newer than the running version.

    An unparseable tag reads as "not newer" — a malformed release tag must never
    produce an update nag. Tuple ordering handles unequal lengths the obvious way
    (``0.1 < 0.1.1``).
    """
    latest = parse_version(latest_tag)
    running = parse_version(current)
    return latest is not None and running is not None and latest > running


def fetch_latest_release() -> tuple[str, str]:
    """Return ``(tag, html_url)`` of the latest stable release.

    Blocking (network) — call it off the GUI thread; see :class:`UpdateChecker`.

    Raises:
        OSError: the request failed (offline, timeout, HTTP error — including the
            404 GitHub returns while every release is marked Pre-release).
        ValueError, KeyError: the response wasn't the expected JSON.
    """
    request = urllib.request.Request(
        _LATEST_API_URL, headers={"Accept": "application/vnd.github+json"}
    )
    with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
        payload = json.load(response)
    return payload["tag_name"], payload.get("html_url") or RELEASES_URL


class UpdateChecker(QtCore.QObject):
    """Runs the blocking GitHub query off the GUI thread and signals the result.

    The worker emits :attr:`finished` from its own thread; Qt delivers a
    cross-thread signal as a queued call on the receiver's (GUI) thread, so the
    slot may touch widgets. The thread is a daemon so a hung network call can
    never keep SMACC from exiting.
    """

    finished = QtCore.pyqtSignal(object)  # UpdateResult

    def check(self) -> None:
        """Start one check; ``finished`` fires exactly once with the result."""
        threading.Thread(target=self._run, name="update-check", daemon=True).start()

    def _run(self) -> None:
        try:
            tag, url = fetch_latest_release()
        except (OSError, ValueError, KeyError):
            # Offline, blocked, timed out, or unexpected payload: report "couldn't
            # check" (latest=None) rather than guessing — never a false update nag.
            self.finished.emit(UpdateResult(latest=None, newer=False, url=RELEASES_URL))
            return
        self.finished.emit(UpdateResult(latest=tag, newer=is_newer(tag), url=url))
