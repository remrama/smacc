"""Run the app."""
import sys

if len(sys.argv) == 1:
    # Run main window.
    from PyQt5.QtWidgets import QApplication, QMessageBox
    from .gui import SubjectSessionRequest, SmaccWindow
    app = QApplication(sys.argv)

    # Check for the presence of inpout and ask to download if not present.
    from .utils import inpout_exists, download_inpout
    if not inpout_exists():
        inpout_box = QMessageBox()
        inpout_box.setWindowTitle("Inpout Check")
        inpout_box.setText("Inpout was not found. This is required to send port codes/triggers.\n\nWould you like to download inpout?")
        inpout_box.setIcon(QMessageBox.Question)
        inpout_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        # Show the message box and get the response.
        response = inpout_box.exec_()
        if response == QMessageBox.Yes:
            download_inpout()

        msg_box = QMessageBox()
        msg_box.setWindowTitle("Information")
        msg_box.setText("Restart SMACC to utilize port codes/triggers.")
        msg_box.setIcon(QMessageBox.Information)
        msg_box.setStandardButtons(QMessageBox.Ok)
        # Show the message box.
        msg_box.exec_()
        sys.exit()


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
