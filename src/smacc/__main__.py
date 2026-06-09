"""Run the app."""

import logging
import sys
import threading
import traceback
from pathlib import Path
from types import TracebackType

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMessageBox

from . import preferences
from .launcher import LauncherWindow, resolve_initial_settings
from .paths import (
    BUNDLED_CUES_DIR,
    BUNDLED_DEFAULT_SETTINGS,
    DEFAULT_DATA_DIR,
    DEFAULT_SETTINGS_PATH,
    LOGO_PATH,
    preferences_path,
)
from .utils import seed_default_settings, seed_demo_cues

# Study-file extensions SMACC will open when launched with a file (or double-click).
_STUDY_SUFFIXES = {".smacc"}


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
    """Capture uncaught exceptions in the log file (and a dialog on the GUI thread).

    The packaged app is built with PyInstaller ``--noconsole``, so without this an
    unhandled exception would be lost entirely (no terminal to print to). We log
    the full traceback to the smacc log file and still chain to the default hook
    so a dev terminal keeps printing tracebacks. Background-thread exceptions
    (e.g. the audio callback) are logged only — never touch widgets off the GUI
    thread.
    """
    logger = logging.getLogger("smacc")

    def log_file_hint() -> str:
        for handler in logger.handlers:
            if isinstance(handler, logging.FileHandler):
                return f"\n\nDetails were written to:\n{handler.baseFilename}"
        return ""

    def handle_main(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_tb: TracebackType | None,
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logger.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_tb))
        summary = "".join(traceback.format_exception_only(exc_type, exc_value)).strip()
        QMessageBox.critical(
            None,
            "SMACC error",
            f"An unexpected error occurred:\n\n{summary}{log_file_hint()}",
        )
        # Keep default behaviour too, so a dev terminal still shows the traceback.
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    def handle_thread(args: threading.ExceptHookArgs) -> None:
        if issubclass(args.exc_type, SystemExit):
            return
        name = args.thread.name if args.thread is not None else "?"
        exc_value = args.exc_value if args.exc_value is not None else args.exc_type()
        logger.critical(
            "Uncaught exception in thread %s",
            name,
            exc_info=(args.exc_type, exc_value, args.exc_traceback),
        )

    sys.excepthook = handle_main
    threading.excepthook = handle_thread


def main() -> None:
    """Open SMACC at its launcher (the FSL-style opening menu).

    The launcher is the persistent root window: it lets the operator pick a settings
    (.smacc) file and then start a session, create settings, or analyze a past run. A
    ``.smacc`` passed on the command line (or a double-clicked file) skips the menu
    and goes straight to a session for it; closing it returns to the launcher. Run
    folders and logs are created only when a session starts, not the instant the app
    launches.
    """
    app = QApplication(sys.argv)
    _install_excepthook()
    # Fusion honors the full QPalette consistently across platforms, which the
    # native Windows style does not — required for the lights-off dark theme.
    app.setStyle("Fusion")
    # Always open in light mode. Qt 6's Fusion follows the OS color scheme, so on
    # a dark-mode OS SMACC would otherwise open dark even with the lights "on";
    # the lightswitch flips to the dark scheme on demand (see SmaccWindow).
    style_hints = app.styleHints()
    assert style_hints is not None
    style_hints.setColorScheme(Qt.ColorScheme.Light)
    # The launcher owns app lifetime: tool windows come and go without quitting, so
    # closing the last tool returns to the launcher rather than exiting.
    app.setQuitOnLastWindowClosed(False)
    # Application-wide icon (taskbar + windows).
    if LOGO_PATH.is_file():
        app.setWindowIcon(QIcon(str(LOGO_PATH)))
    # First-run seeding (best-effort): a readable default.smacc and demo cues, so
    # there's always a working setup to open and something to play.
    seed_default_settings(DEFAULT_SETTINGS_PATH, BUNDLED_DEFAULT_SETTINGS)
    seed_demo_cues(DEFAULT_DATA_DIR / "cues", BUNDLED_CUES_DIR)
    file_arg = pick_settings_path(app.arguments())
    if file_arg:
        # A double-clicked / CLI .smacc opens straight into a session for it; the
        # launcher reappears when that session ends.
        launcher = LauncherWindow(file_arg)
        launcher.start_session()
    else:
        prefs = preferences.load_preferences(preferences_path)
        launcher = LauncherWindow(resolve_initial_settings(prefs))
        launcher.show()
    # `launcher` stays referenced for the life of main() (until app.exec returns),
    # so Qt won't garbage-collect the root window.
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
