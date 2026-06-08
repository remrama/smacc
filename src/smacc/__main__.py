"""Run the app."""

import logging
import sys
import threading
import traceback
from pathlib import Path
from types import TracebackType

from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication, QMessageBox

from .gui import SmaccWindow
from .paths import LOGO_PATH, studies_directory
from .session import SmaccSession
from .study import Study, default_study

# Study-file extensions SMACC will open when launched with a file (or double-click).
_STUDY_SUFFIXES = {".smacc", ".yaml", ".yml"}


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
    """Open SMACC: resolve the active study, then start a session within it.

    A ``.smacc`` passed on the command line (or a double-clicked study) opens its
    folder as the study and loads that file as the initial setup; otherwise the
    auto-managed ``default`` study is used (scaffolded with demo cues on first
    run), loading its own ``study.smacc`` when present. The run folder and log are
    created under the study only now — not the instant the app launches.
    """
    app = QApplication(sys.argv)
    _install_excepthook()
    # Fusion honors the full QPalette consistently across platforms, which the
    # native Windows style does not — required for the lights-off dark theme.
    app.setStyle("Fusion")
    # Application-wide icon (taskbar + windows).
    if LOGO_PATH.is_file():
        app.setWindowIcon(QIcon(str(LOGO_PATH)))
    # Resolve which study this launch belongs to and the config to load as the
    # initial setup. A study folder owns its cues and its session runs.
    file_arg = pick_settings_path(app.arguments())
    if file_arg:
        study = Study.open(Path(file_arg).parent)
        settings_path: str | None = file_arg
    else:
        study = default_study(studies_directory)
        settings_path = str(study.config_path) if study.has_config() else None
    # Subject/session are optional metadata (set via File -> Session info…), so a
    # session starts straight away with a timestamped run folder under the study.
    session = SmaccSession(study)
    # Keep a reference so Qt doesn't garbage-collect the window.
    win = SmaccWindow(session, settings_path=settings_path)  # noqa: F841
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
