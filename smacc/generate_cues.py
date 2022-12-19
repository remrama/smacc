"""Generat some simple cue wave files.
https://stackoverflow.com/q/11570942
"""
import numpy as np
from scipy.io.wavfile import write

import utils


def note(freq, duration, amp, rate):
    t = np.linspace(0, duration, duration * rate)
    data = np.sin(2 * np.pi * freq * t) * amp
    return data.astype(np.int16)  # two byte integers


if __name__ == "__main__":

    data_directory = utils.get_data_directory()
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

    export_path = cues_directory / f"chord.wav"
    write(export_path, 44100, song)
