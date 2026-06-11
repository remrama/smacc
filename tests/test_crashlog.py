"""Tests for the persistent crash log (~/SMACC/logs/crash.log)."""

import faulthandler
import logging
import subprocess
import sys
import threading

import pytest
from PyQt6 import QtCore, QtGui, QtWidgets

from smacc import crashlog
from smacc.__main__ import (
    _crash_details_path,
    _crash_dialog,
    _install_excepthook,
    _show_crash_dialog,
    pick_crash_test,
)
from smacc.paths import CRASH_LOG_PATH


@pytest.fixture
def crash_log(tmp_path):
    """Install the crash log at a temp path; restore process state after."""
    path = tmp_path / "logs" / "crash.log"
    crashlog.install("9.9-test", path)
    yield path
    crashlog.uninstall()
    if sys.stderr is not None:
        # Give pytest back its default hang-dump handler on the real stderr.
        faulthandler.enable()


@pytest.fixture
def smacc_records():
    """Capture records reaching the shared 'smacc' logger."""
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    logger = logging.getLogger("smacc")
    handler = _Capture(level=logging.DEBUG)
    old_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    yield records
    logger.removeHandler(handler)
    logger.setLevel(old_level)


# ----- install / banner / breadcrumbs ----------------------------------------


def test_install_writes_launch_banner_and_enables_faulthandler(crash_log):
    content = crash_log.read_text(encoding="utf-8")
    assert "SMACC v9.9-test" in content
    assert "launched" in content
    assert faulthandler.is_enabled()


def test_note_appends_timestamped_line(crash_log):
    crashlog.note("Session started: somewhere")
    last = crash_log.read_text(encoding="utf-8").splitlines()[-1]
    assert last.endswith("Session started: somewhere")
    assert last[:4].isdigit()  # leads with the ISO date


def test_install_on_unwritable_path_is_silent(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    crashlog.install("9.9-test", blocker / "logs" / "crash.log")  # must not raise
    crashlog.note("dropped")  # and later writes stay no-ops


def test_record_exception_writes_full_traceback(crash_log):
    try:
        raise RuntimeError("boom at 3am")
    except RuntimeError as exc:
        crashlog.record_exception(
            "Uncaught exception", type(exc), exc, exc.__traceback__
        )
    content = crash_log.read_text(encoding="utf-8")
    assert "Uncaught exception" in content
    assert "Traceback (most recent call last)" in content
    assert "RuntimeError: boom at 3am" in content


# ----- rotation ---------------------------------------------------------------


def test_rotate_replaces_one_older_generation(tmp_path):
    path = tmp_path / "crash.log"
    backup = tmp_path / "crash.log.1"
    path.write_text("x" * 200)
    backup.write_text("old generation")
    crashlog.rotate_if_large(path, max_bytes=100)
    assert not path.exists()
    assert backup.read_text() == "x" * 200


def test_rotate_leaves_small_file_alone(tmp_path):
    path = tmp_path / "crash.log"
    path.write_text("tiny")
    crashlog.rotate_if_large(path, max_bytes=100)
    assert path.read_text() == "tiny"
    assert not (tmp_path / "crash.log.1").exists()


def test_install_rotates_an_oversized_log(tmp_path):
    path = tmp_path / "crash.log"
    path.write_text("x" * (crashlog._MAX_BYTES + 1))
    crashlog.install("9.9-test", path)
    try:
        assert (tmp_path / "crash.log.1").exists()
        assert "launched" in path.read_text(encoding="utf-8")
    finally:
        crashlog.uninstall()
        if sys.stderr is not None:
            faulthandler.enable()


# ----- excepthook integration (__main__) --------------------------------------


def test_excepthook_lands_in_crash_log_without_any_session(
    crash_log, monkeypatch, silence_dialogs, capsys
):
    # The launcher-phase gap (#149): no run log exists, the 'smacc' logger has
    # no file handler, yet the traceback must still be captured somewhere.
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    _install_excepthook()
    try:
        raise RuntimeError("launcher-phase crash")
    except RuntimeError as exc:
        sys.excepthook(type(exc), exc, exc.__traceback__)
    content = crash_log.read_text(encoding="utf-8")
    assert "Uncaught exception" in content
    assert "RuntimeError: launcher-phase crash" in content


def test_thread_excepthook_lands_in_crash_log(crash_log, monkeypatch):
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    _install_excepthook()
    exc = RuntimeError("audio thread crash")
    threading.excepthook(threading.ExceptHookArgs([RuntimeError, exc, None, None]))
    content = crash_log.read_text(encoding="utf-8")
    assert "Uncaught exception in thread ?" in content
    assert "RuntimeError: audio thread crash" in content


# ----- Qt message routing ------------------------------------------------------


def test_qt_fatal_and_critical_reach_crash_log(crash_log, smacc_records):
    crashlog.qt_message_handler(QtCore.QtMsgType.QtFatalMsg, None, "qFatal last words")
    crashlog.qt_message_handler(QtCore.QtMsgType.QtCriticalMsg, None, "qCritical line")
    content = crash_log.read_text(encoding="utf-8")
    assert "Qt fatal: qFatal last words" in content
    assert "Qt critical: qCritical line" in content
    levels = [(r.levelno, r.getMessage()) for r in smacc_records]
    assert (logging.CRITICAL, "Qt fatal: qFatal last words") in levels
    assert (logging.ERROR, "Qt critical: qCritical line") in levels


def test_qt_warnings_stay_out_of_crash_log(crash_log, smacc_records):
    before = crash_log.read_text(encoding="utf-8")
    crashlog.qt_message_handler(QtCore.QtMsgType.QtWarningMsg, None, "connect spam")
    assert crash_log.read_text(encoding="utf-8") == before
    levels = [(r.levelno, r.getMessage()) for r in smacc_records]
    assert (logging.DEBUG, "Qt: connect spam") in levels


# ----- the crash dialog (#154) --------------------------------------------------


def test_crash_details_path_prefers_run_log_then_crash_log(tmp_path):
    logger = logging.getLogger("smacc")
    # Recreate the launcher phase: the shared logger holds no run-log handler
    # (other suite tests may have left one; strip them for this check).
    file_handlers = [h for h in logger.handlers if isinstance(h, logging.FileHandler)]
    for handler in file_handlers:
        logger.removeHandler(handler)
    try:
        assert _crash_details_path() == CRASH_LOG_PATH
        run_handler = logging.FileHandler(tmp_path / "run.log", encoding="utf-8")
        logger.addHandler(run_handler)
        try:
            assert _crash_details_path() == tmp_path / "run.log"
        finally:
            logger.removeHandler(run_handler)
            run_handler.close()
    finally:
        for handler in file_handlers:
            logger.addHandler(handler)


def test_crash_dialog_names_the_log_and_offers_open_button(qapp, tmp_path):
    details = tmp_path / "logs" / "crash.log"
    box, open_button = _crash_dialog("RuntimeError: boom", details)
    assert str(details) in box.text()
    assert "RuntimeError: boom" in box.text()
    assert open_button.text() == "Open logs folder"
    assert box.buttonRole(open_button) == box.ButtonRole.ActionRole


def test_show_crash_dialog_opens_the_logs_folder(qapp, monkeypatch):
    opened = []
    monkeypatch.setattr(
        QtGui.QDesktopServices, "openUrl", lambda url: opened.append(url) or True
    )
    # Simulate the operator clicking "Open logs folder" (the ActionRole button).
    monkeypatch.setattr(QtWidgets.QMessageBox, "exec", lambda self: 0)
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "clickedButton",
        lambda self: next(
            b
            for b in self.buttons()
            if self.buttonRole(b) == self.ButtonRole.ActionRole
        ),
    )
    _show_crash_dialog("RuntimeError: boom")
    assert [url.toLocalFile() for url in opened] == [CRASH_LOG_PATH.parent.as_posix()]


def test_show_crash_dialog_close_does_not_open_anything(qapp, monkeypatch):
    opened = []
    monkeypatch.setattr(
        QtGui.QDesktopServices, "openUrl", lambda url: opened.append(url) or True
    )
    monkeypatch.setattr(QtWidgets.QMessageBox, "exec", lambda self: 0)
    monkeypatch.setattr(QtWidgets.QMessageBox, "clickedButton", lambda self: None)
    _show_crash_dialog("RuntimeError: boom")
    assert opened == []


# ----- the hidden --crash-test flag --------------------------------------------


def test_pick_crash_test_modes():
    assert pick_crash_test([]) is None
    assert pick_crash_test(["study.smacc"]) is None
    assert pick_crash_test(["--crash-test"]) == "python"
    assert pick_crash_test(["--crash-test=python"]) == "python"
    assert pick_crash_test(["--crash-test=native"]) == "native"


# ----- the real thing: a native crash ------------------------------------------


def test_faulthandler_dump_survives_a_real_segfault(tmp_path):
    """Segfault a child process and confirm the thread dump lands in crash.log.

    This is the crash class #149 is about: the process dies below Python, no
    excepthook runs, and only the pre-armed faulthandler fd gets a word in.
    """
    path = tmp_path / "crash.log"
    code = (
        "import ctypes\n"
        "import faulthandler\n"
        "from pathlib import Path\n"
        "from smacc import crashlog\n"
        # Keep Windows from raising its error-report popup for this deliberate
        # crash — it would surface on the developer's desktop on every local
        # test run (0x8007 = SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX |
        # SEM_NOALIGNMENTFAULTEXCEPT | SEM_NOOPENFILEERRORBOX).
        "ctypes.windll.kernel32.SetErrorMode(0x8007)\n"
        f"crashlog.install('0.0-test', Path({str(path)!r}))\n"
        "faulthandler._sigsegv()\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120
    )
    assert proc.returncode != 0  # the child really died
    content = path.read_text(encoding="utf-8", errors="replace")
    assert "SMACC v0.0-test" in content  # the launch banner dates the dump
    assert "Windows fatal exception" in content or "Fatal Python error" in content
    assert "File " in content  # the Python stack made it out
