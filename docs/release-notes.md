# Release notes

::: {.callout-warning title="SMACC is pre-1.0"}

SMACC has not reached a stable release. Settings files, marker codes, the
interface, and behavior may change between releases, and there are no
compatibility shims. Pin one version for the duration of a study. See the
[versioning policy](contributing.md#versioning) for what the numbers mean.

:::

<!-- Newest release first. Set the date when a version is tagged. -->

## 0.1.1 — 2026-06-15

- Fixed the Analyzer vanishing on open — clicking **Analyzer** hid the
    launcher but never showed the Analyzer window.

## 0.1.0 — 2026-06-15

The first published release of SMACC — a Windows control surface for running
sleep and dream studies. It includes:

- **Audio cues**, designed in-app with the Audio Cue Designer, plus masking
    background noise.
- **Visual cues** on a BlinkStick or Philips Hue light.
- **Biocalibrations** as timed, marked tasks.
- **Dream reports and surveys** for structured night-time data collection.
- **Intercom** to talk, listen, and type with the participant.
- **EEG markers** (port codes) over an LSL marker stream or a hardware TTL trigger.
- The **EEG Annotator** for reviewing and scoring recordings (optional component).
- A detailed **session log**, a **volume safety cap**, and explicit **device
    routing** so a misclick can't blast or mislead a sleeping participant.
- A per-user **Windows installer** (no admin rights) and a portable `SMACC.exe`.

Earlier `0.0.x` builds predate this release and are not covered here.
