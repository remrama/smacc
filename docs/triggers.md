# Triggers & port codes

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
for this reason. See [Configuring codes](usage.md#configuring-codes) for how to view
and edit which event sends which code.

## Default event codes

These are SMACC's built-in event markers and their default port codes — the
out-of-the-box [`event_codes`](reference/settings-file.md#event_codes) registry. A
study can retune any code in the **Event codes** editor; the change travels in its
[`.smacc`](reference/settings-file.md) and is written into every session log.

<!-- BEGIN auto:event-codes (kept in lockstep with smacc.events.default_events by tests/test_docs_schema.py) -->
| Code | Event | Key | Notes |
|------|-------|-----|-------|
| 41 | REM detected | `REMDetected` | |
| 42 | Tech in room | `TechInRoom` | |
| 43 | TLR training start | `TLRTrainingStart` | |
| 44 | TLR training end | `TLRTrainingEnd` | |
| 45 | LRLR detected | `LRLRDetected` | lucid left-right-left-right signal |
| 46 | Sleep onset | `SleepOnset` | |
| 47 | Lights off | `LightsOff` | |
| 48 | Lights on | `LightsOn` | |
| 49 | Clapper | `Clapper` | sync marker |
| 50 | Note | `Note` | |
| 51 | Start recording | `RecordingStarted` | sets the reference clock for dream-report timestamps |
| 60 | Cue started | `CueStarted` | |
| 61 | Cue stopped | `CueStopped` | |
| 62 | Noise started | `NoiseStarted` | |
| 63 | Noise stopped | `NoiseStopped` | |
| 64 | Intercom started | `IntercomStarted` | |
| 65 | Intercom stopped | `IntercomStopped` | |
| 66 | Visual stimulation | `VisualStarted` | |
| 67 | Survey opened | `SurveyOpened` | |
| 100 | SMACC initialized | `TriggerInitialization` | startup connection test; not a stimulus marker |
| 200 | Dream report stopped | `DreamReportStopped` | |
| 201 | Dream report started | `DreamReportStarted` | increments per report (201, 202, …) |
<!-- END auto:event-codes -->

Codes are integers in **1–255** and must be unique among triggered events.

## How SMACC sends triggers

SMACC always emits markers over **LSL** (Lab Streaming Layer), a network marker
stream. On top of that, you can *optionally* enable **one** hardware transport so a
physical trigger reaches an amplifier that doesn't read LSL. Both fire from the same
place, so every event you log is sent the same way over every enabled path.

| Transport | What it is | What you need |
|---|---|---|
| **LSL** (always on) | A network marker stream recorded by an LSL-aware recorder (e.g. LabRecorder → XDF). Works on the same computer or across the network. | Nothing extra. |
| **Serial (USB trigger box)** | The modern replacement for the parallel port. The box appears as a COM port; SMACC writes the code as one byte and the box mirrors it onto 8 TTL lines. | A USB-serial trigger box and its COM port. |
| **Parallel port (LPT)** | The classic 25-pin port. Eight data pins carry the code byte, sampled by the amplifier. | An LPT port (often an add-in card) and the **InpOut32** driver (see below). |

!!! note "LSL stays on"
    Enabling a hardware transport does **not** turn LSL off — you always get the LSL
    marker stream as well. The hardware path is purely additional.

## Pulsed vs. set-and-hold

Amplifiers and trigger boxes differ in how they expect the code to appear on the
lines, so SMACC offers two modes:

* **Pulsed** — SMACC raises the code on the lines, waits a configurable **pulse
  width** (e.g. 10 ms), then drops them back to 0. Each event is a brief, distinct
  pulse. Choose this when the amplifier expects a momentary trigger, or when you want
  SMACC to control the pulse length.
* **Set-and-hold** — SMACC writes the code once and leaves it on the lines until the
  next event. Choose this for amplifiers that sample a held level, **and** for boxes
  that generate their own fixed-width pulse when they receive a byte (SMACC just sets
  the value; the box shapes the pulse).

If you're not sure which your hardware wants, start with **pulsed at 10 ms** and
verify with the **Test** button (below); switch to set-and-hold if events don't
register cleanly.

## Configuring trigger output in SMACC

1. Open **File ▸ Trigger output…** (available both in a live session and in the
   settings editor).
2. Tick **Enable hardware trigger output**.
3. Choose a **Transport**:
    * **Serial** — pick your box's **Port** from the dropdown (click **Refresh** if
      you plugged it in after opening the dialog) and set the **Baud** rate. If the
      rig isn't attached right now, you can type the port name (e.g. `COM3`) directly.
    * **Parallel port** — enter the **Address** as hex (see
      [Finding your parallel-port address](#finding-your-parallel-port-address)).
4. Choose a **Mode** (pulsed or set-and-hold) and, for pulsed, a **Pulse width**.
5. Click **Test** to send one pulse and confirm the amplifier sees it. The result
   appears next to the button; an error explains what went wrong.
6. Click **OK**.

The whole configuration is saved in your `.smacc`
[settings file](usage.md#settings-files-smacc), so it travels with the rest of your
setup. Because a COM port name or LPT address is specific to one computer, SMACC
reports a clear error if the saved port can't be opened on the machine you load it on
— re-pick it in the dialog and save again.

!!! warning "Always validate on the real hardware"
    A successful **Test** confirms SMACC could open the port and write to it. It does
    **not** prove the amplifier recorded the correct code on its trigger channel.
    Before relying on triggers for a study, record a few test events and confirm they
    appear, with the right codes, in the EEG.

## Finding your parallel-port address

A parallel port is addressed by a base **I/O address**, written in hexadecimal. The
most common values are:

* `0x378` — the usual address for the first parallel port (LPT1).
* `0x278` — a common second port (LPT2).
* `0x3BC` — older onboard ports.

Add-in PCIe/PCI parallel cards are frequently mapped somewhere else entirely, so
**don't assume** — look it up:

1. Open **Device Manager** (press `Win+X`, then choose Device Manager).
2. Expand **Ports (COM & LPT)** and double-click your parallel port.
3. Go to the **Resources** tab and read the first **I/O Range** — the start of that
   range is your address. Enter it in SMACC with a `0x` prefix (e.g. `0x378`).

## Installing the InpOut32 driver (parallel port only)

Modern Windows blocks direct port access from ordinary programs, so the parallel-port
path needs a small kernel driver, **InpOut32 / inpoutx64**. SMACC does **not**
download or install it for you (an earlier version did, and it proved fragile and
required admin rights every launch). Install it once, manually:

1. Download **InpOutBinaries** from [highrez.co.uk](https://www.highrez.co.uk/downloads/inpout32/).
2. Run the included **`InstallDriver.exe`** once (as administrator) to install the
   kernel driver.
3. Make sure **`inpoutx64.dll`** is where SMACC can load it — on the system path, in
   `C:\Windows\System32`, or beside `SMACC.exe`.

If the driver isn't available, SMACC's parallel transport reports a clear error and
falls back to LSL only — it never crashes a session over a missing driver.

## Verifying

* Use the **Test** button in the Trigger output dialog for a quick "can SMACC drive
  the line?" check.
* Then confirm end-to-end on the amplifier: record a short block, fire a few events
  from the **Event logging** window, and check that the codes land on the EEG trigger
  channel. Only the real recording proves the path works.
