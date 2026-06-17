# Markers & port codes

This page explains what EEG **triggers** and **port codes** are, the ways SMACC can
send them, and how to configure each one. If you just want the steps, jump to
[Configuring trigger output in SMACC](#configuring-trigger-output-in-smacc).

## What are port codes and triggers?

When you run a sleep or dream study you want to know *exactly when* things happened —
a cue played, REM was observed, a dream report began — and line those moments up with
the EEG recording. The standard way to do this is a **trigger**: at the instant of an
event, the stimulus computer sends a small number to the EEG amplifier, which records
it on a dedicated **trigger channel** alongside the brain signal. That number is the
**port code** (also called an event marker or trigger code). During analysis you find
events by their code — e.g. "every 41 is an observed REM onset."

A port code is an **8-bit value**, so it is always an integer from **1 to 255**. That
range follows from the hardware: a trigger is physically **eight on/off lines** (eight
bits), and the amplifier reads them as one byte. SMACC keeps every code inside 1–255
for this reason. See [Configuring codes](#configuring-codes) for how to view
and edit which event sends which code.

## Terminology

The words *event*, *marker*, *trigger*, and *port code* get used loosely in the
field; SMACC uses each one for exactly one thing, in the UI, the docs, and the
session log:

| Term          | Meaning in SMACC                                                                                                                                                                        |
| ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Event**     | A named thing that can happen during a session — a cue started, REM observed, lights off. Each is an entry in the study's event registry, with a label and a port code.                 |
| **Marker**    | The durable record produced when an event fires. A marker is always a [log line](reference/session-log.md); if the event is routed to a transport, it also carries the port code there. |
| **Port code** | The 8-bit number (**1–255**) identifying an event on the amplifier's trigger channel. Also called a *trigger code*.                                                                     |
| **Trigger**   | The act of *sending* a port code over a transport. An event can be logged without being triggered.                                                                                      |
| **Transport** | A path that carries the code to the recording: the **LSL** marker stream, or a hardware **TTL** line (serial trigger box / parallel port).                                              |
| **Log level** | The severity tag on a log line (`DEBUG`…`CRITICAL`). The log *file* records every level; levels only filter the live preview. See [log levels](reference/session-log.md#log-levels).    |

## Default event codes

These are SMACC's built-in event markers and their default port codes — the
out-of-the-box [`event_codes`](reference/settings-file.md#event_codes) registry. A
study can retune any code in the **Markers** window; the change travels in its
[`.smacc`](reference/settings-file.md) and is written into every session log.

<!-- BEGIN auto:event-codes (kept in lockstep with smacc.events.default_events by tests/test_docs_schema.py) -->

| Code | Event                   | Key                     | Notes                                                                                  |
| ---- | ----------------------- | ----------------------- | -------------------------------------------------------------------------------------- |
| 41   | REM detected            | `REMDetected`           | sleep-stage observation (keypad 4 in the Event logging window)                         |
| 42   | Tech in room            | `TechInRoom`            |                                                                                        |
| 43   | Training start          | `TrainingStart`         | start of a training/learning phase (TMR cue learning, TLR practice)                    |
| 44   | Training end            | `TrainingEnd`           |                                                                                        |
| 45   | Signal observed         | `SignalObserved`        | a lucidity/communication signal; the signal type + confidence are logged as the detail |
| 46   | Sleep onset             | `SleepOnset`            |                                                                                        |
| 47   | Lights off              | `LightsOff`             |                                                                                        |
| 48   | Lights on               | `LightsOn`              |                                                                                        |
| 49   | Clapper                 | `Clapper`               | sync marker                                                                            |
| 50   | Note                    | `Note`                  |                                                                                        |
| 51   | Start recording         | `RecordingStarted`      | sets the reference clock for dream-report timestamps                                   |
| 52   | Wake detected           | `WakeDetected`          | sleep-stage observation (keypad 0 in the Event logging window)                         |
| 53   | N1 detected             | `N1Detected`            | sleep-stage observation (keypad 1)                                                     |
| 54   | N2 detected             | `N2Detected`            | sleep-stage observation (keypad 2)                                                     |
| 55   | N3 detected             | `N3Detected`            | sleep-stage observation (keypad 3)                                                     |
| 56   | Arousal detected        | `ArousalDetected`       | a brief transient arousal (distinct from a sustained Wake)                             |
| 57   | Artifact detected       | `ArtifactDetected`      | EEG artifact (movement, electrode noise, etc.)                                         |
| 60   | Cue started             | `CueStarted`            |                                                                                        |
| 61   | Cue stopped             | `CueStopped`            |                                                                                        |
| 62   | Noise started           | `NoiseStarted`          |                                                                                        |
| 63   | Noise stopped           | `NoiseStopped`          |                                                                                        |
| 64   | Intercom started        | `IntercomStarted`       |                                                                                        |
| 65   | Intercom stopped        | `IntercomStopped`       |                                                                                        |
| 66   | Visual started          | `VisualStarted`         |                                                                                        |
| 67   | Survey opened           | `SurveyOpened`          |                                                                                        |
| 68   | Visual stopped          | `VisualStopped`         | the light is actually off (pairs with 66)                                              |
| 69   | Chat to participant     | `ChatMessageSent`       | typed intercom message; log-only by default                                            |
| 70   | Chat from participant   | `ChatMessageReceived`   | participant's typed reply; log-only by default                                         |
| 71   | Survey submitted        | `SurveySubmitted`       | in-app survey responses saved; log-only by default                                     |
| 100  | SMACC initialized       | `TriggerInitialization` | startup connection test; not a stimulus marker                                         |
| 105  | Biocal sequence started | `BiocalSequenceStarted` | brackets a played biocal sequence                                                      |
| 106  | Biocal sequence stopped | `BiocalSequenceStopped` | completed or aborted                                                                   |
| 107  | Biocal cancelled        | `BiocalCancelled`       | shared; the preceding start code identifies the biocal                                 |
| 108  | Biocal completed        | `BiocalCompleted`       | shared; the task window ran out                                                        |
| 110  | Biocal: Eyes Open       | `BiocalEyesOpen`        | biocal starts mark the task-window opening                                             |
| 111  | Biocal: Eyes Closed     | `BiocalEyesClosed`      |                                                                                        |
| 112  | Biocal: Look L/R        | `BiocalLookLR`          |                                                                                        |
| 113  | Biocal: Look U/D        | `BiocalLookUD`          |                                                                                        |
| 114  | Biocal: Blink           | `BiocalBlink`           |                                                                                        |
| 115  | Biocal: Clench Jaw      | `BiocalClenchJaw`       |                                                                                        |
| 116  | Biocal: Flex Feet       | `BiocalFlexFeet`        |                                                                                        |
| 117  | Biocal: Hold Breath     | `BiocalHoldBreath`      |                                                                                        |
| 118  | Biocal: Breathe         | `BiocalBreathe`         |                                                                                        |
| 119  | Biocal: Rest            | `BiocalRest`            |                                                                                        |
| 120  | Biocal: LRLR Open       | `BiocalLRLROpen`        |                                                                                        |
| 121  | Biocal: LRLR Closed     | `BiocalLRLRClosed`      |                                                                                        |
| 122  | Biocal: LRLR Slow       | `BiocalLRLRSlow`        |                                                                                        |
| 123  | Biocal: Fist Clench     | `BiocalFistClench`      |                                                                                        |
| 124  | Biocal: Fist Closed     | `BiocalFistClosed`      |                                                                                        |
| 125  | Biocal: Sniff Open      | `BiocalSniffOpen`       |                                                                                        |
| 126  | Biocal: Sniff Closed    | `BiocalSniffClosed`     |                                                                                        |
| 200  | Dream report stopped    | `DreamReportStopped`    |                                                                                        |
| 201  | Dream report started    | `DreamReportStarted`    | increments per report (201, 202, …)                                                    |

<!-- END auto:event-codes -->

Codes are integers in **1–255** and must be unique among events routed to a
transport (LSL or TTL).

## Configuring codes

Open the **Markers** window from the **Panels** column (in a Session or in the
Editor). It is the home for everything about event signaling: a **routing legend**
(what the log file, the live preview, LSL, and TTL each receive, and which switch
governs it), the full event registry grouped by category (including the events with
no grid button — lights, panel controls, biocals, chat, system), and the
[hardware TTL transport](#configuring-trigger-output-in-smacc). For each event you
can set:

- **Code** — the 8-bit port code (1–255) sent when the event triggers.
- **LSL** — whether a firing sends the code over the LSL marker stream.
- **TTL** — whether a firing sends the code over the hardware TTL trigger. The
    column is grayed out until a transport is enabled in the window's **Hardware TTL
    transport** section (the ticks are kept and re-arm with it). An event with neither
    LSL nor TTL ticked is log-only.
- **Preview** — whether the event shows in the live log preview. The session log
    *file* always records every event regardless; this only controls the on-screen
    preview.
- **Increment** — give an event a unique, increasing code on each firing (for
    example **dream reports**: 201, 202, 203, …) so individual occurrences are
    findable in the trigger channel. Off uses one fixed code each time.

**TTL safe max code** raises a soft warning for TTL-routed codes above it, handy when
your trigger hardware accepts only a limited range (some older systems do; LSL
carries any code). Codes must be unique among routed events and within 1–255; the
window blocks anything else.

**Custom events.** Use **Add event…** — in the **Event logging** panel itself, or in
the Markers window — to create your own button events (a label and a code). They
appear in the Event logging panel alongside the built-ins and can be removed again
with the Markers window's **Remove**. Built-in events can be retuned but not removed
or renamed.

Edits are staged until you press **Apply** (which validates them first); **Revert**
re-reads the session's current setup. The window stays available throughout a
session. If you change a code mid-session, the change is written to the log with a
timestamp, so the code-to-event mapping for that session is always recoverable.

Beyond port codes, SMACC logs the important interactions too — volume, colour,
device, and fade changes — as plain log lines (no port code), so the session record
is complete.

## Event logging panel

The manual event buttons (the sleep-stage family, Signal observed, Sleep onset,
Note, your custom events, and so on) live in the **Event logging** panel — open it
from the Session window's **Panels** column. The sleep-stage buttons take a fixed
keypad — **0** Wake, **1** N1, **2** N2, **3** N3, **4** REM — and the remaining
buttons take **5**–**9** in order; the shortcuts are active while the panel is
focused. The **Lights** toggle stays on the main window (it also flips the dark
theme).

**Signal observed.** One button covers every lucidity/communication signal a study
uses (LRLR, sniff, facial, …), so you do not need a separate button per signal. Pick
the **signal** type (the box is editable — type your own and it is remembered for the
rest of the session) and a **confidence** (certain / probable / possible) beside the
button. Pressing it fires the marker immediately and logs your selection as the
detail, so the marker's timing tracks the observation. Confidence is recorded as a
comment; it never changes whether the marker reaches the EEG.

## Where codes live

Your codes are saved in the SMACC file (so they travel with it) and written into
every session `.log` (both the initial and final settings blocks), so any session is
self-documenting: you can decode its markers later even if the codes changed
mid-session.

## How SMACC sends triggers

SMACC emits markers over **LSL** (Lab Streaming Layer), a network marker stream. On
top of that, you can *optionally* enable **one** hardware transport so a physical
trigger reaches an amplifier that doesn't read LSL. Both fire from the same place,
and each event routes to either path independently: its **LSL** and **TTL** flags in
the registry decide where its code goes (both by default; an event routed to
neither is log-only).

| Transport                    | What it is                                                                                                                                              | What you need                                                               |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| **LSL** (always on)          | A network marker stream recorded by an LSL-aware recorder (e.g. LabRecorder → XDF). Works on the same computer or across the network.                   | Nothing extra.                                                              |
| **Serial (USB trigger box)** | The modern replacement for the parallel port. The box appears as a COM port; SMACC writes the code as one byte and the box mirrors it onto 8 TTL lines. | A USB-serial trigger box and its COM port.                                  |
| **Parallel port (LPT)**      | The classic 25-pin port. Eight data pins carry the code byte, sampled by the amplifier.                                                                 | An LPT port (often an add-in card) and the **InpOut32** driver (see below). |

::: {.callout-note title="LSL stays on"}

Enabling a hardware transport does **not** turn LSL off — events routed to both
(the default) reach the LSL stream and the hardware line together. The hardware
path is purely additional. LSL support ships inside SMACC itself — there is
nothing separate to install on the *sending* side (the recorder, e.g.
LabRecorder, is its own program).

:::

::: {.callout-tip title="Why route per event?"}

Most studies leave every event on both transports. Per-event routing earns its
keep when the TTL hardware is restricted — an older amplifier that only accepts
a limited code range can keep its key events on TTL (inside the
[safe max](#configuring-codes)) while chattier or higher-coded events
still reach the LSL stream.

:::

### What is the baud rate?

For the **serial (USB trigger box)** transport you also set a **baud rate** — the
speed, in bits per second, at which SMACC talks to the box over its COM port. It is a
property of the *serial link*, not of the trigger codes: the same 8-bit code (1–255)
is sent either way; baud only controls how fast that byte goes out.

The one rule that matters is that **both ends must use the same baud rate.** Your box
is configured (by a switch, firmware, or its manual) to expect a specific rate, and
SMACC has to match it — a mismatch produces garbled or missed triggers, not an error.

- **Where to find it:** check your trigger box's manual or its configuration utility.
    Common rates are 9600, 19200, 38400, 57600, **115200**, and 230400.
- **SMACC's default is 115200**, which many modern USB trigger boxes (e.g. typical
    BrainProducts/Neurospec-style adapters) use out of the box. If yours specifies a
    different rate, pick it from the dropdown (or type any other value).
- **Higher isn't "better."** A faster rate shaves only microseconds off a one-byte
    write, which is negligible next to audio/event timing — so choose the rate your box
    expects rather than the largest one.

If triggers don't register, a wrong baud rate is one of the first things to check
(alongside the COM port and the [pulsed vs. set-and-hold](#pulsed-vs-set-and-hold)
mode).

## Pulsed vs. set-and-hold

Amplifiers and trigger boxes differ in how they expect the code to appear on the
lines, so SMACC offers two modes:

- **Pulsed** — SMACC raises the code on the lines, waits a configurable **pulse
    width** (e.g. 10 ms), then drops them back to 0. Each event is a brief, distinct
    pulse. Choose this when the amplifier expects a momentary trigger, or when you want
    SMACC to control the pulse length.
- **Set-and-hold** — SMACC writes the code once and leaves it on the lines until the
    next event. Choose this for amplifiers that sample a held level, **and** for boxes
    that generate their own fixed-width pulse when they receive a byte (SMACC just sets
    the value; the box shapes the pulse).

If you're not sure which your hardware wants, start with **pulsed at 10 ms** and
verify with the **Test** button (below); switch to set-and-hold if events don't
register cleanly.

## Configuring trigger output in SMACC

1. Open the **Markers** window from the Panels column (available both in a live
    Session and in the Editor) and find its **Hardware TTL transport** section.
1. Tick **Enable hardware trigger output**.
1. Choose a **Transport**:
    - **Serial** — pick your box's **Port** from the dropdown (click **Refresh** if
        you plugged it in after opening the window) and set the **Baud** rate to match
        your box (see [What is the baud rate?](#what-is-the-baud-rate); SMACC defaults to
        115200). If the rig isn't attached right now, you can type the port name (e.g.
        `COM3`) directly.
    - **Parallel port** — enter the **Address** as hex (see
        [Finding your parallel-port address](#finding-your-parallel-port-address)).
1. Choose a **Mode** (pulsed or set-and-hold) and, for pulsed, a **Pulse width**.
1. Click **Test** to send one pulse and confirm the amplifier sees it. The result
    appears next to the button; an error explains what went wrong.
1. Click **Apply**.

The whole configuration is saved in your
[SMACC file](smacc-files.md), so it travels with the rest of your
setup. Because a COM port name or LPT address is specific to one computer, SMACC
reports a clear error if the saved port can't be opened on the machine you load it on
— re-pick it in the Markers window and save again.

::: {.callout-warning title="Always validate on the real hardware"}

A successful **Test** confirms SMACC could open the port and write to it. It does
**not** prove the amplifier recorded the correct code on its trigger channel.
Before relying on triggers for a study, record a few test events and confirm they
appear, with the right codes, in the EEG.

:::

## Finding your parallel-port address

A parallel port is addressed by a base **I/O address**, written in hexadecimal. The
most common values are:

- `0x378` — the usual address for the first parallel port (LPT1).
- `0x278` — a common second port (LPT2).
- `0x3BC` — older onboard ports.

Add-in PCIe/PCI parallel cards are frequently mapped somewhere else entirely, so
**don't assume** — look it up:

1. Open **Device Manager** (press `Win+X`, then choose Device Manager).
1. Expand **Ports (COM & LPT)** and double-click your parallel port.
1. Go to the **Resources** tab and read the first **I/O Range** — the start of that
    range is your address. Enter it in SMACC with a `0x` prefix (e.g. `0x378`).

## Installing the InpOut32 driver (parallel port only)

Modern Windows blocks direct port access from ordinary programs, so the parallel-port
path needs a small kernel driver, **InpOut32 / inpoutx64**. SMACC does **not**
download or install it for you (an earlier version did, and it proved fragile and
required admin rights every launch). Install it once, manually:

1. Download **InpOutBinaries** from [highrez.co.uk](https://www.highrez.co.uk/downloads/inpout32/).
1. Run the included **`InstallDriver.exe`** once (as administrator) to install the
    kernel driver.
1. Make sure **`inpoutx64.dll`** is where SMACC can load it — on the system path, in
    `C:\Windows\System32`, or beside `SMACC.exe`.

If the driver isn't available, SMACC's parallel transport reports a clear error and
falls back to LSL only — it never crashes a session over a missing driver.

## Verifying

- Use the **Test** button in the Markers window's transport section for a quick
    "can SMACC drive the line?" check.
- Then confirm end-to-end on the amplifier: record a short block, fire a few events
    from the **Event logging** window, and check that the codes land on the EEG trigger
    channel. Only the real recording proves the path works.
