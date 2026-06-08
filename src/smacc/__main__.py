"""Run the app."""

import logging
import sys
import threading
import traceback
from types import TracebackType

from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication, QMessageBox

from .gui import SmaccWindow
from .paths import BUNDLED_CUES_DIR, LOGO_PATH, cues_directory
from .session import SmaccSession
from .utils import seed_demo_cues


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
    """Open the main window for a new timestamped session (no setup prompt)."""
    app = QApplication(sys.argv)
    _install_excepthook()
    # Make sure there's always something to play: seed demo cues on launch.
    seed_demo_cues(cues_directory, BUNDLED_CUES_DIR)
    # Fusion honors the full QPalette consistently across platforms, which the
    # native Windows style does not — required for the lights-off dark theme.
    app.setStyle("Fusion")
    # Application-wide icon (taskbar + windows).
    if LOGO_PATH.is_file():
        app.setWindowIcon(QIcon(str(LOGO_PATH)))
    # Subject/session are now optional metadata (set via File -> Session info…),
    # so a session starts straight away with a timestamped run folder.
    session = SmaccSession()
    # Keep a reference so Qt doesn't garbage-collect the window.
    win = SmaccWindow(session)  # noqa: F841
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
