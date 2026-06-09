"""Render the bundled biocal voice recordings (developer tool; output checked in).

Synthesizes each phrase in :mod:`smacc.biocals` with a Windows SAPI
text-to-speech voice (COM via pywin32), trims the silence SAPI pads around the
speech (a long tail would delay the task-window start marker, which fires when
the voice ends), peak-normalizes to -3 dBFS, and writes 22.05 kHz mono PCM-16
WAVs into ``src/smacc/assets/biocals/``. Re-run whenever a phrase changes:

    uv run --with pywin32 python tools/make_biocal_voices.py

The bundled set is seeded into ``SMACC_DIRECTORY/biocals`` on first launch; a
lab preferring another voice (or language) replaces the files there — same
names — and SMACC never overwrites them.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf
import win32com.client

from smacc import biocals

OUT_DIR = Path(__file__).resolve().parents[1] / "src" / "smacc" / "assets" / "biocals"

PREFERRED_VOICE = "Zira"  # any installed voice whose description matches
SPEAKING_RATE = -1  # SAPI rate (-10..10); slightly slower than default
SAFT_22KHZ_16BIT_MONO = 22  # SpAudioFormat.Type
SSFM_CREATE_FOR_WRITE = 3  # SpFileStream.Open mode

PEAK_DBFS = -3.0  # normalization target
TRIM_THRESHOLD = 1e-3  # |sample| below this counts as silence
TRIM_PAD_S = 0.12  # silence kept on each side of the speech


def synthesize(phrase: str, path: Path) -> None:
    """Render ``phrase`` to ``path`` as a WAV via the SAPI voice."""
    voice = win32com.client.Dispatch("SAPI.SpVoice")
    for token in voice.GetVoices():
        if PREFERRED_VOICE.lower() in token.GetDescription().lower():
            voice.Voice = token
            break
    voice.Rate = SPEAKING_RATE
    stream = win32com.client.Dispatch("SAPI.SpFileStream")
    stream.Format.Type = SAFT_22KHZ_16BIT_MONO
    stream.Open(str(path), SSFM_CREATE_FOR_WRITE, False)
    try:
        voice.AudioOutputStream = stream
        voice.Speak(phrase)
    finally:
        stream.Close()


def tidy(path: Path) -> float:
    """Trim padding silence and peak-normalize ``path`` in place; return seconds."""
    data, rate = sf.read(path, dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)
    loud = np.flatnonzero(np.abs(data) > TRIM_THRESHOLD)
    if loud.size == 0:
        raise RuntimeError(f"{path.name}: synthesized audio is silent")
    pad = int(TRIM_PAD_S * rate)
    data = data[max(0, loud[0] - pad) : min(data.shape[0], loud[-1] + pad)]
    peak = float(np.max(np.abs(data)))
    data = data * (10 ** (PEAK_DBFS / 20) / peak)
    sf.write(path, data, rate, subtype="PCM_16")
    return data.shape[0] / rate


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for b in biocals.default_biocals():
        path = OUT_DIR / b.filename
        synthesize(b.phrase, path)
        seconds = tidy(path)
        print(f"{b.filename:18s} {seconds:5.2f} s  {b.phrase}")


if __name__ == "__main__":
    main()
