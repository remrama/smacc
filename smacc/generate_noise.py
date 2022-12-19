"""
Export short wav files that play different colored noise.
https://stackoverflow.com/a/67127726
"""
import numpy as np
from scipy.io.wavfile import write

from smacc import utils


def noise_psd(N, psd = lambda f: 1):
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


if __name__ == "__main__":

    data_directory = utils.get_data_directory()
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
