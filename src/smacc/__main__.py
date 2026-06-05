"""Run the app."""

import sys

from PyQt5.QtWidgets import QApplication

from .gui import SmaccWindow, SubjectSessionRequest


def main() -> None:
    """Show the session-setup dialog and, on confirmation, open the main window."""
    app = QApplication(sys.argv)
    inbox = SubjectSessionRequest()
    inbox.exec()
    if inbox.result():  # 1 if they hit Ok, 0 if cancel
        subject_id, session_id = inbox.get_inputs()
        # Keep a reference so Qt doesn't garbage-collect the window.
        win = SmaccWindow(subject_id, session_id)  # noqa: F841
        sys.exit(app.exec())


if __name__ == "__main__":
    main()
