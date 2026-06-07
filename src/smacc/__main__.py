"""Run the app."""

import sys

from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication

from .dialogs import SubjectSessionRequest
from .gui import SmaccWindow
from .paths import LOGO_PATH


def main() -> None:
    """Show the session-setup dialog and, on confirmation, open the main window."""
    app = QApplication(sys.argv)
    # Fusion honors the full QPalette consistently across platforms, which the
    # native Windows style does not — required for the lights-off dark theme.
    app.setStyle("Fusion")
    # Application-wide icon (taskbar + the subject/session dialog).
    if LOGO_PATH.is_file():
        app.setWindowIcon(QIcon(str(LOGO_PATH)))
    inbox = SubjectSessionRequest()
    inbox.exec()
    if inbox.result():  # 1 if they hit Ok, 0 if cancel
        subject_id, session_id = inbox.get_inputs()
        # Keep a reference so Qt doesn't garbage-collect the window.
        win = SmaccWindow(subject_id, session_id)  # noqa: F841
        sys.exit(app.exec())


if __name__ == "__main__":
    main()
