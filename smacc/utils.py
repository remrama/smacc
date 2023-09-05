from os import environ
from pathlib import Path

import numpy as np
from scipy.io.wavfile import write


def get_data_directory():
    """Returns default data directory if environment variable is not set."""
    data_directory = environ.get("SMACC_DATA_DIRECTORY", "~/SMACC")
    return Path(data_directory).expanduser()

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
