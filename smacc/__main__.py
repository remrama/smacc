"""Run the app."""
import sys

if len(sys.argv) == 1:
    # Run main window.
    from PyQt5.QtWidgets import QApplication
    from .gui import SubjectSessionRequest, SmaccWindow
    app = QApplication(sys.argv)
    inbox = SubjectSessionRequest()
    inbox.exec_()
    if inbox.result():  # 1 if they hit Ok, 0 if cancel
        subject_id, session_id = inbox.getInputs()
        win = SmaccWindow(subject_id, session_id)
        sys.exit(app.exec_())

else:
    from .utils import *
    mode = sys.argv[1]
    assert mode in ["generate_noise", "generate_cues", "download_inpout"]
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

    elif mode == "download_inpout":
        # Install parallel port driver (optional, only if triggers needed)        
        import os
        from pathlib import Path
        import shutil
        import urllib.request
        import zipfile
        download_path = data_directory / "InpOutBinaries.zip"
        # Download InpOut32 from https://www.highrez.co.uk/downloads/inpout32
        url = "https://www.highrez.co.uk/scripts/download.asp?package=InpOutBinaries"
        urllib.request.urlretrieve(url, download_path)
        # Extract all files from the zip.
        unzip_path = download_path.with_suffix("")
        with zipfile.ZipFile(download_path, "r") as f:
            f.extractall(unzip_path)
        # Install the driver.
        driver_path = unzip_path / "Win32" / "InstallDriver.exe"
        subprocess.check_call([driver_path], shell=True)
        # Move the .dll file to Windows/System32/ directory.
        dll_old_path = unzip_path / "x64" / "inpoutx64.dll"
        dll_new_path = Path("C:\\Windows\\System32\\")
        shutil.move(dll_old_path, dll_new_path)
        # Clean up by deleting unused inpout files.
        shutil.rmtree(unzip_path)
        os.remove(download_path)
