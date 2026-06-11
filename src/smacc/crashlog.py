"""The persistent crash log: the one file that survives any kind of crash.

A live run already writes a detailed per-run log (see :mod:`smacc.session`),
and ``__main__`` hooks uncaught Python exceptions into it. That still loses the
crashes this module exists for:

* **Native crashes** — an access violation inside Qt, PortAudio, or liblsl
  kills the process below Python, so no excepthook ever runs. ``faulthandler``
  is enabled on this file, so the Python stack of every thread is dumped at
  that moment.
* **Crashes outside a live session** — the launcher, editor, and analyzer have
  no run log, and the frozen exe is built ``--noconsole`` (``sys.stderr`` is
  ``None``), so a traceback printed by the default hook goes nowhere.
* **Qt's own diagnostics** — the qCritical/qFatal lines that precede many
  aborts are printed to the (absent) stderr unless a message handler captures
  them.

Everything lands in one append-only file, ``~/SMACC/logs/crash.log``, rotated
at launch once it grows large (one older ``crash.log.1`` generation is kept) —
so "send in crash.log plus the night's run folder" is the complete debug kit.
A faulthandler dump carries no timestamps, which is why every launch and every
session start is stamped here: those breadcrumbs are what tie a dump to its
night. Writes here never raise — this module must not be able to take down a
live night.
"""

from __future__ import annotations

import faulthandler
import logging
import os
import traceback
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import TextIO

from PyQt6 import QtCore

from .paths import CRASH_LOG_PATH

# Rotate past this size at launch (before faulthandler pins the file open).
_MAX_BYTES = 512_000

# The append handle everything writes to, opened by install() and kept for the
# life of the process: faulthandler holds its fd, so it must never be closed
# while enabled (on Windows it also keeps the file locked against deletion).
_crash_file: TextIO | None = None


def _timestamp() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def _write(text: str) -> None:
    """Append ``text`` to the crash log; a failed write is silently dropped."""
    if _crash_file is None:
        return
    try:
        _crash_file.write(text)
        _crash_file.flush()
    except Exception:
        pass


def rotate_if_large(path: Path, max_bytes: int = _MAX_BYTES) -> None:
    """Rename ``path`` to ``<name>.1`` when it exceeds ``max_bytes``.

    One older generation is kept (an existing ``.1`` is replaced). Failures are
    ignored: another SMACC instance may hold the file open (faulthandler pins
    it), and appending to an oversized log beats failing the launch.
    """
    try:
        if not path.exists() or path.stat().st_size <= max_bytes:
            return
        backup = path.with_name(path.name + ".1")
        backup.unlink(missing_ok=True)
        path.rename(backup)
    except OSError:
        pass


def install(version: str, path: Path = CRASH_LOG_PATH) -> None:
    """Open the crash log and enable faulthandler on it. Call first in main().

    Must run before ``QApplication`` exists: a native crash during Qt startup
    is exactly the kind of death this file is for. Never raises — an unwritable
    disk must not stop SMACC from launching (that run simply has no crash log).
    """
    global _crash_file
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        rotate_if_large(path)
        handle = open(path, "a", encoding="utf-8")
    except Exception:
        return
    previous = _crash_file
    _crash_file = handle
    # One banner per launch: with it (and the session breadcrumbs) an undated
    # faulthandler dump can be matched to its night.
    _write(f"\n=== SMACC v{version} (pid {os.getpid()}) launched {_timestamp()} ===\n")
    try:
        faulthandler.enable(file=handle, all_threads=True)
    except Exception:
        pass
    if previous is not None:
        # Reinstalled (tests): release the old handle only after faulthandler
        # has been pointed at the new one.
        try:
            previous.close()
        except Exception:
            pass


def uninstall() -> None:
    """Disable faulthandler and close the crash-log handle (for tests)."""
    global _crash_file
    faulthandler.disable()
    if _crash_file is not None:
        try:
            _crash_file.close()
        except Exception:
            pass
        _crash_file = None


def note(message: str) -> None:
    """Append a timestamped one-liner (e.g. the session-start breadcrumb)."""
    _write(f"{_timestamp()} {message}\n")


def record_exception(
    prefix: str,
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: TracebackType | None,
) -> None:
    """Append an uncaught exception's full traceback under a timestamped header.

    A direct file write with no dependency on the logging tree, so it works in
    every phase: at the launcher (no run log yet), in the editor (NullHandler),
    and mid-session alike.
    """
    try:
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    except Exception:
        text = f"{exc_type.__name__}: {exc_value!r} (traceback unavailable)\n"
    _write(f"{_timestamp()} {prefix}\n{text}")


def qt_message_handler(
    mode: QtCore.QtMsgType, context: QtCore.QMessageLogContext, message: str | None
) -> None:
    """Route one Qt diagnostic message (installed by install_qt_message_handler).

    Fatal/critical messages go to the crash log *and* the smacc logger — a
    qFatal line ("QThread: Destroyed while thread is still running", …) is
    often the only clue to a native abort. Plain warnings and chatter go only
    to the smacc logger at DEBUG: the run log file records every level, while
    the live preview's gate starts at INFO, so they never bother the operator.
    Never raises — a logging failure must not break Qt's message delivery.
    """
    try:
        logger = logging.getLogger("smacc")
        if mode == QtCore.QtMsgType.QtFatalMsg:
            note(f"Qt fatal: {message}")
            logger.critical(f"Qt fatal: {message}")
        elif mode == QtCore.QtMsgType.QtCriticalMsg:
            note(f"Qt critical: {message}")
            logger.error(f"Qt critical: {message}")
        else:
            logger.debug(f"Qt: {message}")
    except Exception:
        pass


def install_qt_message_handler() -> None:
    """Capture Qt's own diagnostics instead of losing them to a missing stderr.

    The frozen exe is windowed (``--noconsole``), so without this the
    qWarning/qCritical/qFatal lines Qt prints right before many aborts vanish.
    The ``QT_LOGGING_RULES`` category filters (see ``__main__``) still apply
    upstream of the handler.
    """
    QtCore.qInstallMessageHandler(qt_message_handler)
