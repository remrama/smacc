"""Run the app."""

import ctypes
import faulthandler
import logging
import os
import sys
import threading
import traceback
from pathlib import Path
from types import TracebackType

from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QIcon
from PyQt6.QtWidgets import QApplication, QMessageBox, QPushButton

from . import crashlog
from .config import display_version, set_taskbar_app_id
from .fonts import apply_app_font
from .launcher import LauncherWindow
from .paths import (
    BUNDLED_CUES_DIR,
    BUNDLED_DEFAULT_SETTINGS,
    CRASH_LOG_PATH,
    DEFAULT_DATA_DIR,
    DEFAULT_SETTINGS_PATH,
    LOGO_PATH,
)
from .utils import seed_default_settings, seed_demo_cues

# Study-file extensions SMACC will open when launched with a file (or double-click).
_STUDY_SUFFIXES = {".smacc"}

# Qt logging-category rule that mutes one harmless line QMediaDevices prints on
# startup ("qt.multimedia.ffmpeg: Using Qt multimedia with FFmpeg version ...").
_FFMPEG_QUIET_RULE = "qt.multimedia.ffmpeg=false"


def _quiet_qt_multimedia_logging() -> None:
    """Mute the noisy Qt-multimedia FFmpeg banner via QT_LOGGING_RULES.

    Must run before QApplication is created (Qt reads the env var at startup). An
    existing QT_LOGGING_RULES is preserved — the rule is appended, not clobbered —
    so a developer's own rules still apply.
    """
    existing = os.environ.get("QT_LOGGING_RULES", "")
    if _FFMPEG_QUIET_RULE in existing:
        return
    os.environ["QT_LOGGING_RULES"] = (
        f"{existing};{_FFMPEG_QUIET_RULE}" if existing else _FFMPEG_QUIET_RULE
    )


def pick_settings_path(args: list[str]) -> str | None:
    """Return the study file to open from CLI args, or ``None``.

    Picks the last argument with a recognized study extension, ignoring the
    program name and any flags. Existence is left to the window so the user sees
    a clear error if the path is bad.
    """
    candidates = [
        arg
        for arg in args[1:]
        if not arg.startswith("-") and Path(arg).suffix.lower() in _STUDY_SUFFIXES
    ]
    return candidates[-1] if candidates else None


def _install_excepthook() -> None:
    """Capture uncaught exceptions in the crash log, the run log, and a dialog.

    The packaged app is built with PyInstaller ``--noconsole``, so without this an
    unhandled exception would be lost entirely (no terminal to print to). The
    traceback goes to the persistent crash log first (a direct file write that
    depends on nothing), then to the smacc logger (the run log, when a session
    is live), then a dialog — shown only once a QApplication exists, so the
    hook can be installed before Qt starts and still cover the whole launch.
    Background-thread exceptions (e.g. the audio callback) are logged only —
    never touch widgets off the GUI thread.
    """
    logger = logging.getLogger("smacc")

    def handle_main(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_tb: TracebackType | None,
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        crashlog.record_exception("Uncaught exception", exc_type, exc_value, exc_tb)
        logger.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_tb))
        summary = "".join(traceback.format_exception_only(exc_type, exc_value)).strip()
        if QApplication.instance() is not None:
            _show_crash_dialog(summary)
        # Keep default behaviour too, so a dev terminal still shows the traceback.
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    def handle_thread(args: threading.ExceptHookArgs) -> None:
        if issubclass(args.exc_type, SystemExit):
            return
        name = args.thread.name if args.thread is not None else "?"
        exc_value = args.exc_value if args.exc_value is not None else args.exc_type()
        crashlog.record_exception(
            f"Uncaught exception in thread {name}",
            args.exc_type,
            exc_value,
            args.exc_traceback,
        )
        logger.critical(
            "Uncaught exception in thread %s",
            name,
            exc_info=(args.exc_type, exc_value, args.exc_traceback),
        )

    sys.excepthook = handle_main
    threading.excepthook = handle_thread


def _crash_details_path() -> Path:
    """The file that captured the crash for the dialog to point at.

    Prefers the run log (the crash in context) when a session is live; outside
    a live session the persistent crash log is the only file, and it always
    has the traceback.
    """
    for handler in logging.getLogger("smacc").handlers:
        if isinstance(handler, logging.FileHandler):
            return Path(handler.baseFilename)
    return CRASH_LOG_PATH


def _crash_dialog(summary: str, details_path: Path) -> tuple[QMessageBox, QPushButton]:
    """Build the uncaught-exception dialog; returns it unshown with its extra button.

    Besides Close, the dialog offers **Open logs folder** so a (likely groggy)
    operator can jump straight to the log named in the message instead of
    retyping a path off a dialog at 3 a.m. (#154). Close stays the default
    button so a reflexive Enter doesn't launch Explorer.
    """
    box = QMessageBox(
        QMessageBox.Icon.Critical,
        "SMACC error",
        f"An unexpected error occurred:\n\n{summary}"
        f"\n\nDetails were written to:\n{details_path}",
    )
    open_button = box.addButton("Open logs folder", QMessageBox.ButtonRole.ActionRole)
    assert open_button is not None  # a valid role always yields a button
    box.addButton(QMessageBox.StandardButton.Close)
    box.setDefaultButton(QMessageBox.StandardButton.Close)
    return box, open_button


def _show_crash_dialog(summary: str) -> None:
    """Show the crash dialog; open the log's folder if that button was chosen.

    The folder open is fire-and-forget: Explorer is its own process, so it
    survives the abort PyQt performs once the excepthook returns.
    """
    details_path = _crash_details_path()
    box, open_button = _crash_dialog(summary, details_path)
    box.exec()
    if box.clickedButton() is open_button:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(details_path.parent)))


def pick_crash_test(args: list[str]) -> str | None:
    """Return the hidden ``--crash-test`` mode from CLI args, or ``None``.

    ``--crash-test`` (or ``=python``) raises a RuntimeError once the event loop
    runs, exercising the excepthook → crash log → dialog path; ``=native``
    segfaults the process, exercising the faulthandler dump. This is the only
    way to verify the crash pipeline on the frozen ``--noconsole`` exe, where
    no console or debugger is attached. Deliberately undocumented in the UI.
    """
    for arg in args:
        if arg == "--crash-test" or arg.startswith("--crash-test="):
            mode = arg.partition("=")[2]
            return mode or "python"
    return None


def _schedule_crash_test(mode: str | None) -> None:
    """Arm the deliberate ``--crash-test`` crash to fire once the loop starts."""
    if mode is None:
        return
    if mode == "native":

        def _segv() -> None:
            # Keep Windows from raising its error-report popup: this crash is
            # deliberate, and a modal popup would hang an unattended run (the
            # release smoke test) waiting for a click. 0x8007 =
            # SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX |
            # SEM_NOALIGNMENTFAULTEXCEPT | SEM_NOOPENFILEERRORBOX.
            # type-ignores: CI's mypy runs on Linux, whose stubs lack windll;
            # _sigsegv is faulthandler's private (unstubbed) test helper.
            ctypes.windll.kernel32.SetErrorMode(0x8007)  # type: ignore[attr-defined]
            faulthandler._sigsegv()  # type: ignore[attr-defined]

        QTimer.singleShot(0, _segv)
        return

    def _boom() -> None:
        raise RuntimeError("SMACC crash test (--crash-test)")

    QTimer.singleShot(0, _boom)


def main() -> None:
    """Open SMACC at its launcher (the FSL-style opening menu).

    The launcher is the persistent root window: it lets the operator pick a SMACC
    (.smacc) file and then start a session, create a SMACC file, or analyze a past
    run. A ``.smacc`` passed on the command line (or a double-clicked file) skips
    the menu and goes straight to a session for it. Ending a session quits SMACC
    (the other tools return to the launcher). Run folders and logs are created only
    when a session starts, not the instant the app launches.

    ``--version`` exits immediately (code 0) without opening any window. The
    release workflow smoke-tests the frozen exe with it — reaching this point
    proves the bundle unpacks and every import resolves. The exe is built
    ``--noconsole`` (no stdout), so the check is the exit code, not the output.

    ``--eeg`` routes to the EEG Annotator: it is a mode of this single binary,
    run in its own process (see ``smacc.eeg.launch``), not a separate program.
    """
    if "--eeg" in sys.argv[1:]:
        # Hand off to the Annotator's entry point, which parses the rest
        # (--selftest, --version, --log, --rater, --blind, the recording path).
        # Imported here, not at module top, so the launcher path never pulls in
        # the MNE/pyqtgraph tree. Strip the routing flag so the Annotator sees
        # only its own arguments.
        from smacc.eeg.__main__ import main as eeg_main

        sys.argv = [sys.argv[0], *(a for a in sys.argv[1:] if a != "--eeg")]
        eeg_main()  # always sys.exit()s; the return guards a future change
        return
    if "--version" in sys.argv[1:]:
        if sys.stdout is not None:  # absent in a --noconsole build
            print(f"SMACC {display_version()}")
        return
    # Crash capture first, before any Qt: a native crash during Qt startup is
    # exactly what the persistent crash log exists to record (#149). The
    # excepthook's dialog arms itself once the QApplication below exists.
    crashlog.install(display_version())
    crashlog.install_qt_message_handler()
    _install_excepthook()
    _quiet_qt_multimedia_logging()  # before QApplication: Qt reads the rule at startup
    set_taskbar_app_id()  # group with the EEG Annotator under one taskbar app
    app = QApplication(sys.argv)
    # Fusion honors the full QPalette consistently across platforms, which the
    # native Windows style does not — required for the lights-off dark theme.
    app.setStyle("Fusion")
    # Always open in light mode. Qt 6's Fusion follows the OS color scheme, so on
    # a dark-mode OS SMACC would otherwise open dark even with the lights "on";
    # the lightswitch flips to the dark scheme on demand (see SmaccWindow).
    style_hints = app.styleHints()
    assert style_hints is not None
    style_hints.setColorScheme(Qt.ColorScheme.Light)
    # Register the bundled B612 cockpit font and set it as the base UI font (#279),
    # so SMACC looks identical on every rig rather than inheriting a system font.
    apply_app_font(app)
    # The launcher owns app lifetime: tool windows come and go without quitting, so
    # closing the last tool returns to the launcher rather than exiting.
    app.setQuitOnLastWindowClosed(False)
    # Application-wide icon (taskbar + windows).
    if LOGO_PATH.is_file():
        app.setWindowIcon(QIcon(str(LOGO_PATH)))
    # Seed/refresh on every launch (best-effort): a readable default.smacc and
    # the demo cues, so there's always a working setup to open and something to
    # play — and so upgrade improvements reach existing installs (#122). Biocal
    # voices are read straight from the bundle (with an optional per-lab override
    # dir), so they need no seeding.
    seed_default_settings(DEFAULT_SETTINGS_PATH, BUNDLED_DEFAULT_SETTINGS)
    seed_demo_cues(DEFAULT_DATA_DIR / "cues", BUNDLED_CUES_DIR)
    file_arg = pick_settings_path(app.arguments())
    if file_arg:
        # A double-clicked / CLI .smacc opens straight into the Session dialog with
        # that file preselected. The dialog validates it (#186); on Cancel or an
        # incompatible file it falls back to showing the launcher, so we never leave
        # no window. Ending the started session quits SMACC (see _on_tool_closed).
        launcher = LauncherWindow(file_arg)
        launcher._open_session()
    else:
        launcher = LauncherWindow()
        launcher.show()
    # Hidden QA hook: crash on purpose right after startup (see pick_crash_test).
    _schedule_crash_test(pick_crash_test(sys.argv[1:]))
    # `launcher` stays referenced for the life of main() (until app.exec returns),
    # so Qt won't garbage-collect the root window.
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
