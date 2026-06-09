"""Render the bundled biocal voice recordings (developer tool; output checked in).

Synthesizes each phrase in :mod:`smacc.biocals` with the chosen engine, trims
the silence padded around the speech (a long tail would delay the task-window
start marker, which fires when the voice ends), peak-normalizes to -3 dBFS, and
writes 22.05 kHz mono PCM-16 WAVs into ``src/smacc/assets/biocals/``.

Engines:

* ``sapi`` — the offline Windows voice (robotic but dependency-light)::

      uv run --with pywin32 python tools/make_biocal_voices.py

* ``elevenlabs`` — a neural ElevenLabs voice. Needs an API key in the
  ``ELEVENLABS_API_KEY`` environment variable (read at run time, never stored;
  note the free tier is non-commercial and requires crediting elevenlabs.io,
  which the usage docs do)::

      uv run python tools/make_biocal_voices.py --engine elevenlabs --voice Rachel

``--voice`` takes an ElevenLabs voice name (resolved via your account's voice
list) or a raw voice id; ``--only KEY`` re-renders a subset (repeatable). Re-run
whenever a phrase changes. The bundled set is seeded into
``SMACC_DIRECTORY/biocals`` on first launch; a lab preferring another voice (or
language) replaces the files there — same names — and SMACC never overwrites
them.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import soundfile as sf

from smacc import biocals

OUT_DIR = Path(__file__).resolve().parents[1] / "src" / "smacc" / "assets" / "biocals"

# Both engines land on the same format so the bundled set stays uniform.
TARGET_RATE = 22050
PEAK_DBFS = -3.0  # normalization target
TRIM_THRESHOLD = 1e-3  # |sample| below this counts as silence
TRIM_PAD_S = 0.12  # silence kept on each side of the speech

# --- Windows SAPI -----------------------------------------------------------

SAPI_PREFERRED_VOICE = "Zira"  # any installed voice whose description matches
SAPI_SPEAKING_RATE = -1  # SAPI rate (-10..10); slightly slower than default
SAFT_22KHZ_16BIT_MONO = 22  # SpAudioFormat.Type
SSFM_CREATE_FOR_WRITE = 3  # SpFileStream.Open mode

# --- ElevenLabs ---------------------------------------------------------------

ELEVENLABS_API = "https://api.elevenlabs.io/v1"
ELEVENLABS_MODEL = "eleven_multilingual_v2"
# mp3_44100_128 is available on every tier (PCM output is gated); decoded and
# downsampled to TARGET_RATE locally.
ELEVENLABS_FORMAT = "mp3_44100_128"
DEFAULT_ELEVENLABS_VOICE = "Rachel"


def synthesize_sapi(phrase: str, path: Path) -> None:
    """Render ``phrase`` to ``path`` as a WAV via the local SAPI voice."""
    import win32com.client  # lazy: only the sapi engine needs pywin32

    voice = win32com.client.Dispatch("SAPI.SpVoice")
    for token in voice.GetVoices():
        if SAPI_PREFERRED_VOICE.lower() in token.GetDescription().lower():
            voice.Voice = token
            break
    voice.Rate = SAPI_SPEAKING_RATE
    stream = win32com.client.Dispatch("SAPI.SpFileStream")
    stream.Format.Type = SAFT_22KHZ_16BIT_MONO
    stream.Open(str(path), SSFM_CREATE_FOR_WRITE, False)
    try:
        voice.AudioOutputStream = stream
        voice.Speak(phrase)
    finally:
        stream.Close()


def _elevenlabs_request(url: str, api_key: str, payload: dict | None = None):
    """One authenticated ElevenLabs call (GET, or POST when ``payload`` given)."""
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={"xi-api-key": api_key, "Content-Type": "application/json"},
    )
    try:
        return urllib.request.urlopen(request, timeout=120)
    except urllib.error.HTTPError as err:  # surface the API's own message
        detail = err.read().decode("utf-8", errors="replace")
        raise SystemExit(f"ElevenLabs request failed ({err.code}): {detail}") from err


def resolve_elevenlabs_voice(api_key: str, voice: str) -> str:
    """Map a voice *name* to its id via the account's voice list (ids pass through)."""
    with _elevenlabs_request(f"{ELEVENLABS_API}/voices", api_key) as response:
        voices = json.loads(response.read())["voices"]
    for entry in voices:
        if entry["name"].lower() == voice.lower():
            return entry["voice_id"]
    if any(entry["voice_id"] == voice for entry in voices) or " " not in voice:
        return voice  # already an id (or one not in the listing)
    names = ", ".join(sorted(entry["name"] for entry in voices))
    raise SystemExit(f"No ElevenLabs voice named {voice!r}. Available: {names}")


def synthesize_elevenlabs(phrase: str, path: Path, api_key: str, voice_id: str) -> None:
    """Render ``phrase`` to ``path`` as a WAV via the ElevenLabs API."""
    url = (
        f"{ELEVENLABS_API}/text-to-speech/{voice_id}?output_format={ELEVENLABS_FORMAT}"
    )
    payload = {"text": phrase, "model_id": ELEVENLABS_MODEL}
    with _elevenlabs_request(url, api_key, payload) as response:
        audio = response.read()
    # libsndfile decodes mp3 from a real file; round-trip through a temp one.
    handle = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    try:
        handle.write(audio)
        handle.close()
        data, rate = sf.read(handle.name, dtype="float32")
    finally:
        os.unlink(handle.name)
    sf.write(path, data, rate, subtype="PCM_16")


def tidy(path: Path) -> float:
    """Resample/trim/normalize ``path`` in place to the bundled format; return seconds."""
    data, rate = sf.read(path, dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)
    if rate != TARGET_RATE:
        from scipy.signal import resample_poly

        g = math.gcd(TARGET_RATE, rate)
        data = resample_poly(data, TARGET_RATE // g, rate // g).astype(np.float32)
        rate = TARGET_RATE
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
    parser = argparse.ArgumentParser(
        description="Render the bundled biocal voice WAVs."
    )
    parser.add_argument(
        "--engine",
        choices=("sapi", "elevenlabs"),
        default="sapi",
        help="speech engine (default: the offline Windows sapi voice)",
    )
    parser.add_argument(
        "--voice",
        default=DEFAULT_ELEVENLABS_VOICE,
        help="ElevenLabs voice name or id (elevenlabs engine only)",
    )
    parser.add_argument(
        "--only",
        action="append",
        metavar="KEY",
        help="re-render only this biocal key (repeatable, e.g. --only rest)",
    )
    args = parser.parse_args()

    table = biocals.default_biocals()
    if args.only:
        unknown = set(args.only) - {b.key for b in table}
        if unknown:
            keys = ", ".join(sorted(b.key for b in table))
            raise SystemExit(f"Unknown biocal(s) {sorted(unknown)}. Keys: {keys}")
        table = [b for b in table if b.key in set(args.only)]

    if args.engine == "elevenlabs":
        api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
        if not api_key:
            raise SystemExit(
                "Set the ELEVENLABS_API_KEY environment variable (the key is "
                "read at run time and never stored)."
            )
        voice_id = resolve_elevenlabs_voice(api_key, args.voice)
        print(f"engine: elevenlabs (voice {args.voice} -> {voice_id})")
    else:
        print("engine: sapi")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for b in table:
        path = OUT_DIR / b.filename
        if args.engine == "elevenlabs":
            synthesize_elevenlabs(b.phrase, path, api_key, voice_id)
        else:
            synthesize_sapi(b.phrase, path)
        seconds = tidy(path)
        print(f"{b.filename:18s} {seconds:5.2f} s  {b.phrase}")


if __name__ == "__main__":
    main()
