# Audio & device routing

Running an overnight cueing study means juggling a *lot* of audio at once — a cue in
the bedroom, white noise in the bedroom, your own voice over an intercom, the
participant's voice coming back, a dream-report mic, sometimes a light cue — often
across several physical devices and two rooms. On Windows, audio is also famously
fiddly: the same speaker shows up under several names, and the level that actually
reaches the participant is the product of several controls scattered across the OS.

SMACC is built around that reality. This page explains how it handles devices,
routing, and volume — the parts that are easy to get wrong at 3 a.m.

## Roles, not per-window device pickers

Instead of picking a device separately in every window, SMACC has **one Devices
window** (in the *Open tools* column) where you do two things:

1. **Bind each _role_ to a device, once.** The roles are the physical endpoints of a
   rig: **Bedroom output**, **Control-room output**, **Bedroom mic**, and
   **BlinkStick**.
2. **Route each modality to a role.** The audio cue, noise, intercom, and
   dream-report recorder each point at a role.

Because the cue, the noise, and your intercom voice can all share the **Bedroom
output** role, swapping the bedroom speaker is a *single* change — not five. Every
other window just shows a read-only indicator of where it resolves, for example
`Device: Bedroom output → Speakers (USB Audio)`.

```text
Bedroom output       Speakers (USB Audio)
Control-room output  Headphones (Realtek)
Bedroom mic          Microphone (USB Audio)
──────────────────────────────────────────
Audio cue    → Bedroom output    (monitor: Control-room output)
Noise        → Bedroom output
Intercom     → Bedroom output
Dream mic    → Bedroom mic
```

The whole assignment is saved in your `.smacc` settings file, so a rig travels with
its study. If a bound device isn't connected when a study loads, SMACC keeps going
and tells you which one is missing rather than silently falling back.

### Monitoring routes

Two optional routes cover the things you reach for mid-study:

* **Cue monitor (fan-out).** Route *Cue monitor* to the control-room output and the
  cue plays in the bedroom **and** the control room at once, so you hear exactly what
  the participant heard.
* **Intercom Listen.** The intercom is two-way: **Talk** sends your voice to the
  participant (and is marked in the EEG record), while **Listen** brings the
  participant's mic to your control-room output.

## One audio engine

All real-time audio — cues, noise, the intercom, the dream-report recorder, and the
input-level meter — runs on [`sounddevice`](https://python-sounddevice.readthedocs.io/)
(PortAudio), through the **Windows WASAPI** host API.

!!! info "Why WASAPI"
    On Windows, PortAudio lists every speaker once per host API (MME, DirectSound,
    WASAPI, WDM-KS) — which is where the "same device, several names" confusion comes
    from — and the legacy MME names are truncated to 31 characters. SMACC enumerates
    **only WASAPI**, so each device appears once, with its full name, on the modern
    low-latency path.

Because everything shares one engine, device names mean the same thing everywhere,
and sending one cue to two devices at once (the fan-out) is just two streams from a
single source.

**Hot-plug:** plug a device in after SMACC is already open and it's picked up
automatically — no restart needed. You can also force a rescan from
**File ▸ Refresh devices** (or press `F5`).

## Volume you can see

The most common "why is it quiet?" trap on Windows is that the level reaching the
participant is a *product* of several controls:

```text
per-cue volume  ×  output safety cap  ×  Windows app volume  ×  Windows device volume  ×  hardware knob
```

Three of those live in the OS and are invisible from most apps. SMACC makes its own
gain explicit and adds a safety limit, in the **Volume** window:

* **Output safety cap.** A single master ceiling that is the *last* gain stage applied
  to every cue and noise output. However loud an individual cue is set, the cap is a
  hard limit — so a full-volume looped cue on a calibrated rig can't suddenly blast a
  sleeping participant.
* **A read-only view of the Windows stages.** The window shows the current **system
  output volume** and **SMACC's own level** in the Windows Volume Mixer, so the hidden
  OS stages are right in front of you.

!!! tip "Calibrating cue level"
    For levels that reproduce across nights and participants, pin the Windows device
    and app volumes to 100%, then calibrate entirely with the per-cue volumes and the
    safety cap inside SMACC. That way one place — SMACC — determines how loud a cue is.

## Windows only, on purpose

This device and volume handling is Windows-specific (WASAPI, the volume mixer), and
the GUI toolkit (Qt 6) needs Windows 10 or later. Supporting one operating system
well — the one sleep labs actually run on — is a deliberate trade for getting these
subtleties right.
