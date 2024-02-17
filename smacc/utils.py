from os import environ
from pathlib import Path

import numpy as np
from scipy.io.wavfile import write


def get_data_directory():
    """Returns default data directory if environment variable is not set."""
    data_directory = environ.get("SMACC_DATA_DIRECTORY", "~/SMACC")
    data_directory = Path(data_directory).expanduser()
    data_directory.mkdir(exist_ok=True)
    return data_directory

def note(freq, duration, amp, rate):
    """https://stackoverflow.com/q/11570942"""
    t = np.linspace(0, duration, duration * rate)
    data = np.sin(2 * np.pi * freq * t) * amp
    return data.astype(np.int16)  # two byte integers

def noise_psd(N, psd = lambda f: 1):
    """https://stackoverflow.com/a/67127726"""
    X_white = np.fft.rfft(np.random.randn(N))
    S = psd(np.fft.rfftfreq(N))
    # Normalize S
    S = S / np.sqrt(np.mean(S**2))
    X_shaped = X_white * S
    return np.fft.irfft(X_shaped)

def PSDGenerator(f):
    return lambda N: noise_psd(N, f)

@PSDGenerator
def white_noise(f):
    return 1

@PSDGenerator
def blue_noise(f):
    return np.sqrt(f)

@PSDGenerator
def violet_noise(f):
    return f

@PSDGenerator
def brownian_noise(f):
    return 1/np.where(f == 0, float("inf"), f)

@PSDGenerator
def pink_noise(f):
    return 1/np.where(f == 0, float("inf"), np.sqrt(f))

def generate_noise_files():
    """Generates temporary noise files"""
    data_directory = get_data_directory()
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

def generate_test_cue_file():
    """Generates a test cue file"""
    data_directory = get_data_directory()
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


def inpout_exists():
    dll_path = Path("C:\\Windows\\System32\\inpoutx64.dll")
    return dll_path.exists()

def download_inpout():
    # Install parallel port driver (optional, only if triggers needed)
    data_directory = get_data_directory()
    import os
    import shutil
    import subprocess
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
    subprocess.check_call(driver_path)
    # Move the .dll file to Windows/System32/ directory.
    dll_old_path = unzip_path / "x64" / "inpoutx64.dll"
    dll_new_path = Path("C:\\Windows\\System32\\")
    shutil.move(dll_old_path.as_posix(), dll_new_path.as_posix())
    # Clean up by deleting unused inpout files.
    shutil.rmtree(unzip_path.as_posix())
    os.remove(download_path.as_posix())
