"""Run the app."""
import sys

if len(sys.argv) == 1:
    from PyQt5.QtWidgets import QApplication, QMessageBox
    from .gui import SubjectSessionRequest, SmaccWindow
    app = QApplication(sys.argv)
    inbox = SubjectSessionRequest()
    inbox.exec_()
    if inbox.result():  # 1 if they hit Ok, 0 if cancel
        subject_id, session_id = inbox.getInputs()
        win = SmaccWindow(subject_id, session_id)
        sys.exit(app.exec_())
else:
    from .utils import generate_noise_files, generate_test_cue_file
    assert (mode := sys.argv[1]) in ["generate_noise", "generate_cues"]
    if mode == "generate_noise":
        generate_noise_files()  # Generate some noise wav files to mask cues.
    elif mode == "generate_cues":
        generate_test_cue_file()  # Generate some wav files for cueing.
