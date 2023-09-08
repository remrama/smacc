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
    from .utils import *
    mode = sys.argv[1]
    assert mode in ["generate_noise", "generate_cues"]
    data_directory = get_data_directory()

    if mode == "generate_noise":
        # Generate some noise wav files to mask cues.
        noise_directory = data_directory / "noise"
        noise_directory.mkdir(exist_ok=True)
        rate = 44100
        noise_functions = {
            "pink": pink_noise,
            "blue": blue_noise,
            "white": white_noise,
            "brown": brownian_noise,
            "violet": violet_noise,
        }
        for color, func in noise_functions.items():
            # Generate a 1-second sample.
            noise = func(rate)
            # Scale it for exporting.
            scaled = np.int16(noise / np.max(np.abs(noise)) * 32767)
            # Export.
            export_path = noise_directory / f"{color}.wav"
            write(export_path, rate, scaled)

    elif mode == "generate_cues":
        # Generate some wav files for cueing.
        cues_directory = data_directory / "cues"
        cues_directory.mkdir(exist_ok=True)
        duration = 1
        amp = 1E4
        rate = 44100
        tone0 = note(0, duration, amp, rate)  #silence
        tone1 = note(261.63, duration, amp, rate)  # C4
        tone2 = note(329.63, duration, amp, rate)  # E4
        tone3 = note(392.00, duration, amp, rate)  # G4
        seq1 = np.concatenate((tone1, tone0, tone0, tone0, tone1), axis=0)
        seq2 = np.concatenate((tone0, tone2, tone0, tone0, tone2), axis=0)
        seq3 = np.concatenate((tone0, tone0, tone3, tone0, tone3), axis=0)
        song = seq1 + seq2 + seq3
        export_path = cues_directory / "song.wav"
        write(export_path, 44100, song)
