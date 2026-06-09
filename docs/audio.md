# Audio & device routing

An overnight cueing study can run several audio streams at once: a cue in the
bedroom, white noise in the bedroom, your voice over an intercom, the participant's
voice coming back, a dream-report mic, and sometimes a light cue. These often span
more than one physical device and two rooms. On Windows, the same speaker can also
appear under several names, and the level that reaches the participant is the product
of several controls spread across the OS.

This page describes how SMACC handles devices, routing, and volume.

## Roles, not per-window device pickers

Instead of picking a device separately in every window, SMACC has one **Devices
window** (in the *Tools* column) where you do two things:

1. **Bind each _role_ to a device, once.** The roles are the physical endpoints of a
   rig: **Bedroom speakers**, **Control-room speakers**, **Bedroom mic**, and
   **Bedroom lights**.
2. **Route each modality to a role.** The cue, noise, intercom, and dream-report
   recorder each point at a role.

The cue, the noise, and your intercom voice can all share the **Bedroom speakers**
role, so swapping the bedroom speaker is one change rather than several. Every other
window shows a read-only indicator of where it resolves, for example
`Device: Bedroom speakers → Speakers (USB Audio)`.

```text
Bedroom speakers      Speakers (USB Audio)
Control-room speakers Headphones (Realtek)
Bedroom mic           Microphone (USB Audio)
──────────────────────────────────────────
Present audio cue    → Bedroom speakers    (monitor: Control-room speakers)
Present audio noise  → Bedroom speakers
Speak through intercom → Bedroom speakers
Capture dream report → Bedroom mic
```

The whole assignment is saved in your `.smacc` settings file, so a rig travels with
its study. If a bound device isn't connected when a study loads, SMACC keeps going
and reports which one is missing instead of silently falling back.

### Monitoring routes

Three optional routes cover the things you reach for mid-study:

* **Monitor audio cue (fan-out).** Route *Monitor audio cue* to the control-room
  speakers and the cue plays in the bedroom and the control room at once, so you hear
  what the participant heard.
* **Listen through intercom.** The intercom is two-way: **Speak through intercom**
  sends your voice to the participant (and is marked in the EEG record), while
  **Listen through intercom** brings the participant's mic to your control-room
  speakers.
* **Monitor the bedroom.** A microphone meter in the Audio cue window that confirms a
  cue is audible in the bedroom (see
  [below](#is-the-cue-reaching-the-bedroom)). It defaults to the **Bedroom mic**, or
  bind a dedicated, more sensitive **Monitor mic** and route *Room monitor* to it.

## One audio engine

All real-time audio (cues, noise, the intercom, the dream-report recorder, and the
input-level meter) runs on [`sounddevice`](https://python-sounddevice.readthedocs.io/)
(PortAudio), through the **Windows WASAPI** host API.

!!! info "Why WASAPI"
    On Windows, PortAudio lists every speaker once per host API (MME, DirectSound,
    WASAPI, WDM-KS), which is where the "same device, several names" confusion comes
    from, and the legacy MME names are truncated to 31 characters. SMACC enumerates
    only WASAPI, so each device appears once, with its full name, on the modern
    low-latency path.

!!! info "Device names in the Devices window"
    Because SMACC enumerates only WASAPI devices, it drops the redundant
    ", Windows WASAPI" suffix that PortAudio appends to each device name. With only
    one host API in the list, the suffix added nothing, so a device reads as
    `Speakers (USB Audio)` rather than `Speakers (USB Audio), Windows WASAPI`.

Because everything shares one engine, device names mean the same thing everywhere,
and sending one cue to two devices at once (the fan-out) is two streams from a single
source.

**Hot-plug:** plug a device in after SMACC is already open and it's picked up
automatically, with no restart needed. You can also force a rescan from
**File ▸ Refresh devices** (or press `F5`).

## Is the cue reaching the bedroom?

A cue you can hear in the control room isn't proof the *participant* heard it — the
bedroom speaker could be muted, unplugged, or turned down at the hardware. The
**Audio cue** window's **Monitoring** section shows two meters so you can tell:

* **Sending** — the level SMACC is emitting to the cue output, the moment it plays.
  It's exact, but it only confirms SMACC is *playing*; it's blind to everything
  downstream (Windows volume, the speaker's power switch, the cable). Treat it as a
  diagnostic: if *Sending* is dark, the problem is on SMACC's side (wrong cue, the
  per-cue volume or the safety cap at zero); if it's lit but the room is silent, the
  problem is the speaker.
* **Bedroom** — the level a microphone actually picks up in the room. This is the
  objective check: it only moves when sound really happens in the bedroom. Tick the
  box beside it to start monitoring. Because a faint cue can sit close to a cheap
  mic's noise floor, the meter also shows the **rise above the room's resting level**
  (the `+N` next to the reading), so even a small bump stands out.

!!! tip "A dedicated monitor mic"
    The *Bedroom* meter listens on the **Room monitor** route, which defaults to your
    bedroom mic. For the most reliable check — especially for the very quiet cues a
    study often starts at — bind a separate, sensitive **Monitor mic** in the Devices
    window and route *Room monitor* to it. That keeps verification independent of the
    (often cheaper, voice-activated) dream-report mic.

!!! warning "A quiet mic isn't proof of silence"
    A cheap or voice-activated mic may not register a very faint cue even when it is
    playing, so a dark *Bedroom* meter is a prompt to check — not proof the cue
    failed. Read it together with *Sending*.

## Volume you can see

On Windows, the level reaching the participant is a product of several controls:

```text
per-cue volume  ×  output safety cap  ×  Windows app volume  ×  Windows device volume  ×  hardware knob
```

Three of those live in the OS and are invisible from most apps. SMACC makes its own
gain explicit and adds a safety limit, in the **Volume** window:

* **Output safety cap.** A single master ceiling, applied as the last gain stage on
  every cue and noise output. However loud an individual cue is set, the cap is a
  hard limit, so a full-volume looped cue on a calibrated rig can't suddenly blast a
  sleeping participant.
* **A read-only view of the Windows stages.** The window shows the current **system
  output volume** and **SMACC's own level** in the Windows Volume Mixer, so the
  hidden OS stages are visible.

!!! tip "Calibrating cue level"
    For levels that reproduce across nights and participants, set the Windows device
    and app volumes to 100%, then calibrate with the per-cue volumes and the safety
    cap inside SMACC. That way one place, SMACC, determines how loud a cue is.

## Windows only

This device and volume handling is Windows-specific (WASAPI, the volume mixer), and
the GUI toolkit (Qt 6) requires Windows 10 or later.
