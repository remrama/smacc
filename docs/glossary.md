# Glossary {#chap-glossary}

SMACC uses a precise vocabulary in its interface, this manual, and the session log —
each of these terms means exactly one thing. The event-signaling words (*event*,
*marker*, *port code*, *trigger*, *transport*) are the ones most often used loosely
in the field; SMACC keeps them distinct.

- **Action** — Something SMACC does with a device, such as *Play audio cue* or
  *Record dream report*. Each action is routed to a piece of equipment in the Devices
  window. See [Audio routing](audio.md#chap-audio).
- **Biocal (biocalibration)** — A scripted participant action (eyes open, look
  left/right, hold breath, …) with a known physiological signature, run as a timed,
  marked task to verify the recording channels. See [Biocals](biocals.md#chap-biocals).
- **Cue** — A stimulus delivered to the participant: an **audio cue** (a sound) or a
  **visual cue** (light on a BlinkStick or Philips Hue).
- **Data directory** — The folder a SMACC file writes its runs to. Each run gets its
  own timestamped subfolder. See [SMACC files](smacc-files.md#chap-smacc-files).
- **Equipment** — A physical endpoint of the rig, named by place (Bedroom speaker,
  Bedroom mic 1, Control-room mic, …) and bound once to a device in the Devices
  window. See [Audio routing](audio.md#chap-audio).
- **Event** — A named thing that can happen during a session — a cue started, REM
  observed, lights off. Each is an entry in the study's event registry, with a label
  and a port code.
- **LSL (Lab Streaming Layer)** — The network marker stream SMACC always emits,
  recorded by an LSL-aware recorder (e.g. LabRecorder). See
  [Markers & port codes](triggers.md#chap-triggers).
- **Log level** — The severity tag on a session-log line (`DEBUG`, `INFO`, `WARNING`,
  `ERROR`, `CRITICAL`). The log file records every level; levels only filter the live
  preview. See [Session log](reference/session-log.md#log-levels).
- **Marker** — The durable record produced when an event fires. A marker is always a
  [log line](reference/session-log.md#chap-reference-session-log); if the event is
  routed to a transport, it also carries the port code there.
- **Port code** — The 8-bit number (1–255) identifying an event on the amplifier's
  trigger channel. Also called a *trigger code*.
- **Rater** — A reviewer in the EEG Annotator. A *rater id* keeps each reviewer's
  annotations in a separate sidecar, for blind, multi-rater scoring. See
  [EEG Annotator](eeg-annotator.md#multiple-raters).
- **Route / routing** — Pointing an action at a piece of equipment in the Devices
  window, so SMACC knows which device performs it. See
  [Audio routing](audio.md#chap-audio).
- **Run** — One recorded execution of a session: a timestamped folder holding the
  session's log, recordings, survey responses, and exports. Each session produces one
  run.
- **Scoring epoch** — In the EEG Annotator, the fixed-length window (30 s by default)
  that one sleep stage is assigned to, kept separate from the on-screen view. See
  [EEG Annotator](eeg-annotator.md#the-epoch-model).
- **Session** — A live run of SMACC for collecting data, opened from the Launcher's
  **Session…** tool. A SMACC file can start any number of sessions, each writing its
  own run. See [Overview](usage.md#chap-usage).
- **SMACC file (`.smacc`)** — A portable study configuration (cues, volumes, event
  codes, device routing, …) plus the data directory its runs are written to. See
  [SMACC files](smacc-files.md#chap-smacc-files).
- **Transport** — A path that carries a port code to the recording: the LSL marker
  stream, or a hardware TTL line (serial trigger box or parallel port).
- **Trigger** — The act of sending a port code over a transport. An event can be
  logged without being triggered.
- **TTL** — A hardware trigger line (a serial USB trigger box or a parallel/LPT port)
  that mirrors a port code onto physical pins for an amplifier that does not read LSL.
  See [Markers & port codes](triggers.md#chap-triggers).
