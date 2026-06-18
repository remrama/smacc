---
name: portcodes
description: Reference for SMACC's EEG event markers ("portcodes") — the 8-bit trigger byte, transports (LSL marker stream, parallel/LPT port, USB-serial trigger box, serial TTL), the InpOut32/inpoutx64 driver landscape, PsychoPy's ParallelPort set-and-hold vs pulsed semantics, SMACC's marker history, the events.py code registry, and the issue #28 hardware-output design. Use when touching event markers, triggers, portcodes, trigger hardware or drivers, the marker-send path in session.py, or issue #28.
---

# Portcodes & EEG event markers

A **portcode** is a small integer (an 8-bit byte, 1–255) that marks *when* an
experiment event happened so it lines up with the EEG recording. The amplifier
records markers on a dedicated **trigger channel** alongside the brain signal;
analysis later finds events by their code. SMACC fires a portcode for events like a
cue starting, observed REM, or a dream report (`src/smacc/events.py`).

The 8-bit range isn't arbitrary: a hardware **TTL** trigger is one byte on 8
physical lines, so every code must fit in 1–255. `events.py` enforces this
(`CODE_MIN = 1`, `CODE_MAX = 255`).

## How SMACC sends a marker today

Every marker flows through one function — `SmaccSession.emit_event()` in
`src/smacc/session.py`. It looks up the `EventDef`, computes the runtime code
(incrementing events advance per firing), writes a log line, and — if the event is
`trigger=True` and an outlet exists — pushes the code:

```python
self.outlet.push_sample([str(code)])   # session.py, ~line 239
```

The outlet is an **LSL** (Lab Streaming Layer) marker stream created in
`init_lsl_stream()` (`StreamInfo("MyMarkerStream", "Markers", …)`). Design mode has
no outlet, so triggers are logged but not sent. **This is the single integration
point** for any additional transport: a parallel/serial write belongs right next to
`push_sample`, with its handle created alongside `init_lsl_stream`.

## The events.py contract (don't break it)

- `EventDef`: `code` (1–255), `trigger`, `preview`, `category`
  (`manual`/`control`/`system`), `increment`, plus `key`/`label`/`tooltip`.
- `increment` events (e.g. `DreamReportStarted`, code 201) advance the code each
  firing (`runtime_code`) so every occurrence is individually findable; clamped to
  255\.
- `validate_events` **errors** on a code outside 1–255, a duplicate code among
  *triggerable* events (they'd collide on the channel), or a duplicate key; it
  **warns** on a code above a study's `safe_max` (older hardware) and on an
  incrementing band overlapping another code.
- A study persists code + routing overrides in its `.smacc`; labels/categories stay
  app-defined. Existing EEG marker maps and recovered logs depend on these codes —
  preserve the contract.

## Transports & trigger hardware

Rigs ingest markers differently; SMACC should support all *known* ones via
configuration (issue #28):

| Transport                  | What it is                                                                                                   | How a byte goes out                                                                                             |
| -------------------------- | ------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------- |
| **LSL marker stream**      | Network marker recorded by an LSL-aware recorder (LabRecorder → XDF). Current default.                       | `StreamOutlet.push_sample`. Same- or cross-computer; no extra hardware.                                         |
| **Parallel port (LPT)**    | Legacy 25-pin port; 8 data pins = the trigger byte, sampled by the amp. Still required by an active lab rig. | Write the byte to the port's data register. On modern Windows needs the **InpOut32 / inpoutx64** kernel driver. |
| **USB-serial trigger box** | The modern LPT replacement; presents as a COM port and mirrors a received byte onto 8 TTL lines.             | `pyserial` write to a configured COM port + baud.                                                               |
| **Serial TTL**             | A device that takes the byte directly over serial.                                                           | `pyserial`, same as above.                                                                                      |

## Parallel port: the driver reality

- Direct port I/O is blocked in user space on modern Windows; you need **InpOut32**
  (`inpoutx64.dll`) or a similar kernel shim, plus admin rights to install it.
- PsychoPy wraps this in `psychopy.parallel.ParallelPort`: `port.setData(0)` then
  `port.setData(code)` writes the byte and **holds** it (set-and-hold — no automatic
  strobe back to 0). To *pulse*, write `code`, wait the pulse width, then write `0`.
- **Do not** resurrect SMACC's old runtime DLL download (see history). If a lab
  needs LPT, document a manual driver install instead.

## Pulse behavior

Trigger boxes and amps differ:

- **Set-and-hold** — leave the lines at `code` until the next event (old parallel
  semantics).
- **Pulsed** — raise `code` for a configurable width (e.g. ~5–10 ms), then drop to
  0\. SMACC's labs use **pulsed**; make the width configurable.

## SMACC's marker history (so you don't relitigate it)

- ≤ v0.0.5 SMACC sent triggers via `psychopy.parallel.ParallelPort(address=0x3FD8)`
  as an 8-bit byte, with a startup connection-test marker (`TriggerInitialization`).
  It even auto-downloaded InpOutBinaries from highrez.co.uk and copied the DLL into
  `C:\Windows\System32` at runtime (admin-gated, fragile).
- `56aa27c` (Oct 2023) swapped psychopy/pport → LSL; `09a0a63` (Feb 2024) removed
  the inpout machinery entirely.
- Motivation: parallel ports are vanishing and the runtime driver install was
  brittle. LSL is cleaner and network-capable — but a **hardware-TTL-only
  amplifier** gets nothing from an LSL-only build, which is the gap issue #28 closes.

## Issue #28 — design constraints

Add **opt-in hardware TTL output alongside LSL**, not instead of it:

- **Dual emission** from the one `emit_event` path; LSL stays default-on.
- Support **LSL + parallel TTL + serial TTL**, all selectable via **configuration**
  (the owner confirmed LSL and parallel are both on active rigs, serial should be
  supported too, and **LPT is still required** by an active rig).
- **Pulsed** triggers with configurable width; preserve the **8-bit portcode
  contract**.
- **Graceful no-op** when unconfigured; never crash if a port is absent;
  **informative error messages** (called out specifically by the owner).
- **Persist** transport/port/baud/mode in the `.smacc` settings.
- **No** runtime DLL download; document a manual LPT driver install.
- Treat easy configuration + an intro docs page as part of the deliverable — the
  owner considers good portcode handling one of SMACC's most valuable features.

## Testing

- The serial/parallel *send* path can be unit-tested against a **fake/loopback**
  port (no hardware).
- Real **TTL output must be validated on the lab hardware** before anyone relies on
  it — a green unit test does not prove the amp saw the pulse.

## Key files & references

- `src/smacc/events.py` — the code registry, validation, `runtime_code`.
- `src/smacc/session.py` — `emit_event`, `init_lsl_stream`, the `push_sample` send
  point (where hardware output hooks in).
- Issue #28 (`gh issue view 28 --comments`) — full design discussion and owner
  constraints.
- External: `psychopy.parallel.ParallelPort` (`setData`); InpOut32/inpoutx64
  (highrez.co.uk) for LPT on modern Windows; `pyserial` for COM-port trigger boxes.
- See also the **dream-engineering** skill (why markers must align with the EEG).
