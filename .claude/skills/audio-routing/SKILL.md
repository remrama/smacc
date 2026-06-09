---
name: audio-routing
description: SMACC's audio and device subsystem — sounddevice/PortAudio over Windows WASAPI, device enumeration and hot-plug, the roles-and-routing model, the Devices window, per-panel output/input streams (cues, noise, intercom, recorder, level meter), and the volume safety cap. Use when touching audio.py, devices.py, winvolume.py, gui.py, or any panels/*.py that opens a stream, or when debugging Windows audio device behavior.
---

# Audio & device routing

The user-facing model is documented in `docs/audio.md`; this skill is the
engineering view — the architecture and the Windows gotchas. Designing here means
designing for "juggling six audio streams across two rooms, on Windows, at 3 a.m."

## Roles and routing (not per-window pickers)

Devices are chosen **once** in the **Devices window**, by binding **roles** to
physical devices and routing **modalities** to roles:

- Roles (physical endpoints): **Bedroom speakers**, **Control-room speakers**,
  **Bedroom mic**, **Bedroom lights**.
- Modalities point at a role: **Present audio cue**, **Present audio noise**,
  intercom (**Speak through intercom**), **Capture dream report**; plus optional
  **Monitor audio cue** (fan-out) and **Listen through intercom**.
- `panels/base.describe_target()` renders the read-only "Role → device" indicator
  each panel shows; the binding/route live in `session.devices` and are saved in the
  `.smacc`.
- A bound-but-unplugged device is **flagged**, not silently swapped.

## One audio engine: sounddevice over WASAPI

- All real-time audio — cues, noise, intercom, recorder, and the input-level meter —
  runs on [`sounddevice`](https://python-sounddevice.readthedocs.io/) (PortAudio).
- SMACC enumerates **WASAPI only** (`sd.query_devices()` filtered to the WASAPI host
  API). On Windows, PortAudio lists each device once per host API
  (MME/DirectSound/WASAPI/WDM-KS) and truncates legacy MME names to 31 chars;
  WASAPI-only means **each device appears once, with its full name**, on the
  low-latency path.
- Because everything shares one engine, a device name means the same thing
  everywhere, and the cue **fan-out** (bedroom + control-room) is just two
  `sd.OutputStream`s from one source.

## Hot-plug: the QMediaDevices "doorbell"

- SMACC keeps `sounddevice` as the audio engine but uses Qt's **`QMediaDevices`**
  (`gui.py`) purely as a **change signal** — when Windows reports an audio device
  added/removed, `QMediaDevices` fires and SMACC rescans via `sounddevice`.
  QMediaDevices is the doorbell, not the audio path.
- Manual rescan: **File ▸ Refresh devices** / **F5**.
- **Gotcha:** re-initializing PortAudio invalidates any open stream, so a rescan
  must run only while **nothing is streaming**. Panels report this via
  `ModalityWindow.is_streaming()`; the refresh coordinator checks it first. Respect
  this guard when adding a stream-owning panel.

## Streams & sample rates

- Each modality panel owns its stream(s): `panels/audio.py`, `noise.py`,
  `intercom.py`, `recording.py` (and the meter). They open `sd.OutputStream` /
  input streams on the resolved device.
- Sample rate comes from the device:
  `int(sd.query_devices(device, "output"|"input")["default_samplerate"])`. Don't
  hardcode 44.1/48 kHz — match the device.
- Panels persist their selection via `gather_state`/`apply_state`, re-render their
  indicator via `refresh_device_indicator` when routing changes, and stop streams in
  `cleanup` on quit (see `panels/base.py`).

## Volume: a visible product, with a safety cap

The level reaching the participant is a **product** of several stages, most hidden
in the OS:

```text
per-cue volume × output safety cap × Windows app volume × Windows device volume × hardware knob
```

- **Output safety cap** — a single master ceiling applied **last** to every
  cue/noise output, so no individual cue (however loud, however looped) can blast a
  sleeping participant. It's a safety feature; treat it as load-bearing.
- `winvolume.py` reads the **Windows** mixer stages (system output volume, SMACC's
  app level) so the Volume window can *show* the otherwise-invisible OS stages.
  Calibration guidance: pin the Windows device/app volumes to 100% and control
  loudness entirely with per-cue volume + the cap.

## Windows-only, on purpose

WASAPI, the volume mixer, and Qt 6 (Windows 10+) make this subsystem
Windows-specific by design — the OS sleep labs actually run on. Don't add
cross-platform audio branches without a reason.

## Gotchas checklist

- Enumerate **WASAPI only**; identity is by **name** (hot-unplug → flag, don't fall
  back silently).
- **Never reinit PortAudio while a stream is open** — gate rescans on
  `is_streaming()`.
- Pull **sample rate per device**; don't assume a fixed rate.
- `QMediaDevices` is only the change **signal**; the audio path is `sounddevice`.
- Remember the **volume product**, and keep the safety cap last.
- Design mode has no marker outlet; audio still plays.

## Key files

`audio.py`, `devices.py`, `winvolume.py`, `panels/base.py`, `panels/audio.py`,
`panels/noise.py`, `panels/intercom.py`, `panels/recording.py`, `gui.py` (the
QMediaDevices doorbell). User-facing: `docs/audio.md`. Related: the
**dream-engineering** skill (why the cap and dark-room constraints exist) and the
**portcodes** skill (markers fired alongside audio events).
