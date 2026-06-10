"""Measure SMACC's audio output latency on this machine (issue #10).

Two questions, two modes:

* ``--report`` (default): what latency does the WASAPI output negotiate at SMACC's
  High vs Low setting? Opens a brief stream each way and prints the latency PortAudio
  reports — the same number SMACC adds to a cue/noise marker (its ``onset_offset``).
  Needs no special hardware: it only queries the device and opens a silent stream.

* ``--loopback``: how long from "play" to the sound actually arriving? Plays a short
  tone burst on the output while recording the input, and cross-correlates each burst
  to estimate the round-trip delay. This needs the output coupled to the input — a
  loopback cable, or a microphone in front of the speaker (then the number also
  includes the room). It is the *spread* across bursts, not the mean, that bounds
  marker jitter; a constant offset is correctable, jitter is not.

Run from the project so the deps (sounddevice/numpy) resolve::

    uv run tools/measure_latency.py
    uv run tools/measure_latency.py --loopback --repeats 30

Numbers are specific to THIS machine + device + load; don't quote them for another
rig. The authoritative per-rig figure comes from a recorded onset channel — see
docs/latency.md and issue #104.
"""

from __future__ import annotations

import argparse
import statistics

import numpy as np
import sounddevice as sd

WASAPI = "Windows WASAPI"


def wasapi_default_output() -> int | None:
    """The default WASAPI output device index (the host API SMACC uses), or None."""
    for api in sd.query_hostapis():
        if api["name"] == WASAPI:
            dev = api["default_output_device"]
            return dev if dev is not None and dev >= 0 else None
    return None


def report(device: int | None) -> None:
    """Print the device's reported and negotiated output latency at low vs high."""
    dev = device if device is not None else wasapi_default_output()
    if dev is None:
        print("No WASAPI output device found (SMACC enumerates WASAPI only).")
        return
    info = sd.query_devices(dev, "output")
    rate = int(info["default_samplerate"])
    print(f"Device:       {info['name']}")
    print(f"Sample rate:  {rate} Hz")
    print(
        f"Reported:     low {info['default_low_output_latency'] * 1000:5.1f} ms"
        f"   high {info['default_high_output_latency'] * 1000:5.1f} ms"
    )
    for mode in ("low", "high"):
        try:
            stream = sd.OutputStream(
                device=dev, channels=1, samplerate=rate, latency=mode
            )
            stream.start()
            negotiated = float(stream.latency) * 1000
            stream.stop()
            stream.close()
            print(
                f"Negotiated [{mode:>4}]: {negotiated:5.1f} ms"
                "   (SMACC stamps the marker this far ahead of the stream start)"
            )
        except Exception as exc:  # noqa: BLE001 - report and continue to the other mode
            print(f"Negotiated [{mode:>4}]: could not open a stream: {exc}")


def loopback(device: int | None, repeats: int, mode: str, gap_s: float = 0.4) -> None:
    """Estimate round-trip latency by playing tone bursts and hearing them back."""
    out_dev = device if device is not None else wasapi_default_output()
    if out_dev is None:
        print("No WASAPI output device found.")
        return
    rate = int(sd.query_devices(out_dev, "output")["default_samplerate"])
    click_n = int(rate * 0.005)  # 5 ms burst
    t = np.arange(click_n) / rate
    burst = (0.5 * np.sin(2 * np.pi * 2000 * t) * np.hanning(click_n)).astype(
        np.float32
    )
    trial = np.concatenate([burst, np.zeros(int(rate * gap_s), dtype=np.float32)])
    signal = np.tile(trial, repeats).reshape(-1, 1)
    print(
        f"Playing {repeats} bursts (couple output->input first: loopback cable or a "
        f"mic at the speaker)..."
    )
    rec = sd.playrec(signal, samplerate=rate, channels=1, latency=mode)
    sd.wait()
    rec = rec[:, 0]
    trial_n = len(trial)
    delays_ms = []
    for k in range(repeats):
        seg = rec[k * trial_n : (k + 1) * trial_n]
        if len(seg) < click_n:
            break
        corr = np.correlate(seg, burst, mode="valid")
        lag = int(np.argmax(np.abs(corr)))
        delays_ms.append(lag / rate * 1000)
    if not delays_ms:
        print("No bursts recovered — is the output actually reaching the input?")
        return
    mean = statistics.mean(delays_ms)
    jitter = statistics.pstdev(delays_ms)
    print(f"Round-trip over {len(delays_ms)} bursts [{mode}]:")
    print(f"  mean {mean:.1f} ms   jitter (sd) {jitter:.1f} ms")
    print(f"  min  {min(delays_ms):.1f} ms   max {max(delays_ms):.1f} ms")
    print("Round-trip includes output + input latency (+ the room, if via a mic).")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--loopback",
        action="store_true",
        help="measure round-trip latency (needs output coupled to input)",
    )
    parser.add_argument(
        "--device", type=int, default=None, help="output device index (default: WASAPI)"
    )
    parser.add_argument("--repeats", type=int, default=20, help="loopback burst count")
    parser.add_argument(
        "--latency",
        choices=("low", "high"),
        default="high",
        help="latency mode for the loopback run (default: high, SMACC's default)",
    )
    args = parser.parse_args()
    if args.loopback:
        loopback(args.device, args.repeats, args.latency)
    else:
        report(args.device)


if __name__ == "__main__":
    main()
