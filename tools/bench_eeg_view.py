# Benchmark the EEG TraceView against the #136 performance target:
# an 8 h x 32 ch x 512 Hz overnight recording must scroll smoothly.
#
#   > uv run --extra eeg python tools/bench_eeg_view.py
#
# A synthetic provider generates EEG-shaped data on demand (so the bench needs
# no gigabyte fixture file); each "refresh" is what one scroll step costs:
# slice fetch -> zero-phase filter -> per-curve setData -> a forced offscreen
# render. Real-file I/O (MNE's memory-mapped read) is NOT measured here — this
# isolates the render path, the part the view design controls.

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PyQt6 import QtWidgets

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from smacc.eeg import dsp  # noqa: E402
from smacc.eeg.view import TraceView  # noqa: E402

SFREQ = 512.0
N_CHANNELS = 32
DURATION_S = 8 * 3600.0
REFRESHES = 20


class SyntheticProvider:
    """EEG-shaped noise, generated per slice (deterministic per start sample)."""

    ch_names = [f"CH{i:02d}" for i in range(N_CHANNELS)]
    ch_types = ["eeg"] * (N_CHANNELS - 2) + ["eog", "emg"]
    sfreq = SFREQ
    duration = DURATION_S

    def get_slice(self, start_s: float, stop_s: float):
        start = max(0, int(round(max(0.0, start_s) * SFREQ)))
        stop = min(int(DURATION_S * SFREQ), int(round(min(DURATION_S, stop_s) * SFREQ)))
        n = max(0, stop - start)
        times = (start + np.arange(n)) / SFREQ
        rng = np.random.default_rng(start)  # deterministic, cheap
        data = rng.standard_normal((N_CHANNELS, n)) * 20e-6
        data += 50e-6 * np.sin(2 * np.pi * 1.0 * times)  # slow-wave-ish
        return times, data


def bench(view: TraceView, window_seconds: float) -> tuple[float, float]:
    view.set_window_seconds(window_seconds)
    view.set_window_start(0.0)
    view.grab()  # warm-up render outside the timed loop
    laps = []
    for _ in range(REFRESHES):
        t0 = time.perf_counter()
        view.scroll_by(0.5)
        view.grab()  # force a full offscreen paint
        laps.append((time.perf_counter() - t0) * 1000)
    return float(np.mean(laps)), float(np.max(laps))


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)  # noqa: F841 — Qt needs a live app
    view = TraceView()
    view.resize(1400, 900)
    view.set_provider(SyntheticProvider())
    view.set_spec(dsp.FilterSpec(highpass=0.3, lowpass=35.0, notch=60.0))
    print(
        f"{N_CHANNELS} ch x {SFREQ:.0f} Hz x {DURATION_S / 3600:.0f} h, "
        f"{REFRESHES} scrolled refreshes per row (filter HP 0.3 / LP 35 / notch 60)"
    )
    failed = False
    # 100 ms keeps scrolling comfortably interactive; 120 s windows may be
    # slower but must stay under a quarter second to feel responsive.
    for window_seconds, budget_ms in ((10.0, 100.0), (30.0, 100.0), (120.0, 250.0)):
        mean_ms, max_ms = bench(view, window_seconds)
        verdict = "ok" if mean_ms <= budget_ms else "TOO SLOW"
        failed |= mean_ms > budget_ms
        print(
            f"  {window_seconds:5.0f} s window: mean {mean_ms:7.1f} ms  "
            f"max {max_ms:7.1f} ms  (budget {budget_ms:.0f} ms)  {verdict}"
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
