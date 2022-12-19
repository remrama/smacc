"""Run the app."""
import sys

from PyQt5.QtWidgets import QApplication

from .gui import SubjectSessionRequest, SmaccWindow

app = QApplication(sys.argv)

inbox = SubjectSessionRequest()
inbox.exec_()

if inbox.result():  # 1 if they hit Ok, 0 if cancel
    subject_id, session_id = inbox.getInputs()
    win = SmaccWindow(subject_id, session_id)
    sys.exit(app.exec_())
