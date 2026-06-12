# Usage

SMACC opens to its **Launcher**, where you pick a **SMACC file** and choose what
to do; from there you run a live **Session** for collecting data. This page walks
through the main features.

SMACC has three main windows, named consistently throughout these docs:

- the **SMACC Launcher** (*Launcher* for short) — the small hub that opens when
    you start the app;
- the **SMACC Session** window (*Session*) — the live interface for running a
    night and collecting data;
- the **SMACC Editor** window (*Editor*) — where you create or edit a
    [SMACC file](smacc-files.md) without recording anything.

<!-- Add an annotated screenshot of the Launcher + Session window here once
available, e.g.: ![SMACC Session window](assets/screenshot-session.png) -->

## Opening SMACC

Open the app itself to get the Launcher — SMACC never drops straight into a
session (the one exception: double-clicking a `.smacc` file, which starts a
Session for it directly). In the Launcher you:

- **pick a SMACC file** — the dropdown lists the seeded `default.smacc`, your
    recent files, and **Browse…** to find any other. With none chosen, SMACC uses
    built-in defaults, so it works out of the box. (See
    [SMACC files](smacc-files.md) for what one holds.)
- **Start** — open a live Session using the selected SMACC file, writing runs to
    that file's **data directory**. The run folder and log are created only now,
    when the session starts.
- **Create** — build a new SMACC file in the Editor: configure the tools (cues,
    noise, visual, event codes, surveys), choose a data directory, and save it
    anywhere.
- **Edit** — reopen the selected SMACC file in the Editor.
- **Design cues** — open the standalone **Cue designer** to build a simple tone cue
    and export it as a WAV into a study's `cues/` folder, ready to use from the Audio
    cue board (see [Designing a cue](#designing-a-cue)).
- **Analyze** — open a past session (a `.log`, a session folder, or a
    zipped session) to see a summary (events, duration, subject/session, dream
    reports), export its events to a BIDS `events.tsv`, or recover its settings to a
    `.smacc` — all without starting a new session.

Closing the Editor or a standalone tool returns you to the Launcher. Ending a
Session quits SMACC entirely — the night is over. Closing the Launcher also
quits SMACC.

## Audio cues

Place sound files where your settings expect them — by default the data directory's
`cues/` folder (e.g. `~/SMACC/data/cues/`; `.wav`, `.mp3`, `.flac`, `.ogg`, and
`.aiff` are supported) — and trigger them from the cue controls. SMACC seeds a few
`demo-*` cues there so there is always something to test with. You start with one
cue — prefilled with a random demo — and use **+ Add cue** and each row's **✕** to
add or remove cues to match a protocol (one minimum, up to 20).

### Designing a cue

No sound file ready? Open **Design cues** from the Launcher to build a simple cue
inside SMACC — no external audio editor needed. Lay out a sequence of **tone** and
**silence** segments (each tone has a frequency, duration, and level, with an
optional bell-like **decay**), or start from a **preset** (a single chime, a pip
train). The whole pattern can **repeat** — ×N with a gap between repeats, the
classic pip-train shape — and an optional whole-cue fade in/out and normalize
finish it. A live **waveform** shows the cue as you edit, **Preview** plays it on
your default output, and **Export WAV…** writes it into your study's `cues/`
folder, where it appears in the Audio cue board like any other cue.

The WAV is what the cue board plays; the *design* stays editable through **Save
design… / Open design…** (a small `.json` file, kept alongside the WAVs by
default) — reopen it tomorrow and nudge a level instead of rebuilding the cue from
scratch. The designer is a standalone tool: it plays on the default device and
ignores the session's device routing and volume safety cap.

### Is the cue reaching the bedroom?

The Audio cue window has a **Monitoring** section — a *Sending* meter (what SMACC is
emitting) beside a *Bedroom* meter (what a mic actually picks up in the room) — so you
can confirm a cue is audible to the participant, not just leaving SMACC. See
[Audio & routing](audio.md#is-the-cue-reaching-the-bedroom) for how to read them
and how to set up a second bedroom mic dedicated to monitoring.

## Visual cues

Light cues live in the **Visual cue** window: one row per cue — color, brightness,
pattern (steady, a smooth pulse, or a flash at a rate in Hz), length, and loop —
with a shared fade-in/out, fired on a USB BlinkStick or a Philips Hue light. You
start with a single red steady cue and use **+ Add cue** / **✕** to match a
protocol (one minimum, up to 10). Every play and stop is marked in the EEG record,
every stop path turns the light off, and a *Sending* swatch mirrors exactly what
SMACC is emitting. See [Visual cues](visual.md) for the patterns, the
BlinkStick-vs-Hue comparison, marker timing, and the photosensitivity notes.

## Dream reports

Use the **Record Dream Report** button to record from the mic bound to the
**Bedroom mic 1** equipment in the **Devices** window.
Recordings are saved into the current session folder. Each report is also stamped
with the time elapsed since you pressed **Start recording** (in the Event logging
panel), so it is easy to locate in the EEG file; if recording has not been marked
yet, the report is still logged and SMACC reminds you to mark it.

Surveys can follow a report two ways: **in-app surveys** (the bundled LuCiD, DLQ,
and LUSK instruments, plus any you build) open in a SMACC window and save their
responses into the run folder next to the report; **web surveys** (e.g. a
questionnaire on Qualtrics or REDCap, added by URL) open in your browser. Manage
both with the **Manage…** button next to the survey dropdown. Select a survey in
the dropdown to open it automatically when recording starts, or open any survey
on its own from **File › Surveys** (each open is logged as a
`SurveyOpened` event). See [Surveys](surveys.md) for the bundled instruments,
the response-file format, and building your own.

## Biocals

Sleep studies open with **biocalibrations** — scripted participant actions (eyes
open, eyes closed, look left/right, …) whose known physiological signatures verify
the recording channels. The **Biocals** window runs them as timed, marked events:
every standard biocal plus the common lucid-dreaming signal practices (LRLR
variants, fist clenches, sniffs), each on its own row.

Each row has a toggle button plus two checkboxes and a duration:

- **Press the biocal's button** to run it. The button stays depressed while it
    runs and the countdown at the top shows the time remaining in its task window;
    press it again to cancel early (no waiting out a botched 30-second window).
- **Voice** — speak the pre-recorded instruction (e.g. *"Please close your eyes
    and relax for thirty seconds."*) over the cue output when the biocal starts.
    Leave it unchecked if you prefer to give instructions yourself.
- **Seq** — include this row when **Play sequence** runs the whole stack in
    order. Standard biocals start checked; the lucid-dreaming ones start unchecked.
- **Duration** — the task window in seconds. With the voice on, the window (and
    its countdown) starts when the instruction *ends*, so a 10-second breath hold
    is a full 10 seconds — matching the manual practice of speaking first and
    marking when the participant complies.

**Markers.** Each biocal's *start* code fires when its task window opens; a shared
**completed** code fires when the window runs out and a shared **cancelled** code
fires on an early stop (the preceding start code identifies which biocal). A played
sequence is bracketed by its own start/stop codes and otherwise fires the identical
per-biocal markers. Defaults: sequence start/stop **105**/**106**, cancelled
**107**, completed **108**, and one start code per biocal in the **110–126** band —
all retunable in the **Markers** window like any built-in event.

**Sequences.** **Play sequence** runs every Seq-checked row top to bottom,
depressing each button as it goes. Pressing the *active biocal's* button skips just
that item (cancel marker, then on to the next); pressing the sequence button again
aborts the rest. Rows can **repeat** a biocal (eyes-closed twice, extra LRLRs —
use **+ Add** to add another instance), be reordered with **▲/▼**, and removed
with **✕**; the stack is locked while something is running. Need a biocal SMACC
doesn't ship? Use a custom event button in the Event logging panel instead.

**Voice recordings** ship inside SMACC (generated with
[ElevenLabs](https://elevenlabs.io) text-to-speech) and are read straight from
the bundle, so they stay current when you upgrade. Prefer another voice or
language? Drop your own recording under the same name in your SMACC directory's
`biocals/` folder (e.g. `~/SMACC/biocals/`) — a file there overrides the bundled
one. (A biocal with no recording in either place still runs, just unvoiced;
session start warns if that happens.) The shared **Voice volume** rides the cue
route, so the master output cap and the control-room monitor fan-out apply to
instructions exactly as they do to cues.

## Intercom

The **Intercom** window is the live channel between the control room and the
bedroom. **Talk** pipes the control-room mic to the participant's output (click to
latch, or hold the **spacebar** anywhere in SMACC as push-to-talk) and is marked in
the EEG record; **Listen** brings the bedroom mic to your control-room speakers,
unmarked.
The two directions route through equipment set once in the **Devices** window (see
[Audio & routing](audio.md)). A **level meter** beside each button shows the
live input level while that direction is on — signal on the bar means audio is
actually flowing (your mic for Talk, the participant's mic for Listen), not just
a latched button.

### Text chat

Below the voice controls is a **typed channel** — for hearing-impaired
participants, or whenever audio would intrude or you want the exchange in writing.
You type in the Intercom panel; the participant reads and replies in a separate
**Participant chat** window made for a dark bedroom: always dark regardless of the
lights toggle, large text (default 18 pt, resize with `Ctrl+=` / `Ctrl+-`), and an
optional **red night text** mode (**Display** menu), with no flashing and no
sounds.

**Setup.** The first cut assumes one computer: extend the desktop onto a
bedroom-facing monitor and plug in a second keyboard for the participant. Click
**Pass keyboard to participant** to open the participant window, drag it onto the
bedroom display once, and it reopens there next session.

**One keyboard at a time.** Windows gives the machine a single input focus, so the
two keyboards type into whichever window is active — text chat is half-duplex,
like push-to-talk. **Pass keyboard to participant** (or `Ctrl+Enter`, which sends
your message first) activates the participant window so their keystrokes land
there; clicking back into SMACC takes the focus back. The participant window shows
a banner — *"● The keyboard is yours"* / *"○ Waiting"* — so a drowsy participant
always knows whether typing will land.

**Quick replies.** Canned messages save both sides from typing a full sentence at
3 a.m.; they travel with the study. Click **Manage quick messages…** on the Intercom
panel to edit two lists — *experimenter prompts* (one click sends a standardized
prompt, e.g. the lab's dream-report question or *"Are you awake?"*) and *participant
replies* mapped to the number keys **1–9** (e.g. *"Got it"*, *"I'm awake"*, *"Yes"*,
*"No"*). The participant's replies appear as large numbered chips; pressing a number
sends that reply, but only while their entry box is empty, so a typed reply that
contains digits still works. A sent preset is logged and marked exactly like a typed
message.

**What's recorded.** Every message is written verbatim to the session log as a
DEBUG line (tick *Debug* above the log preview to watch the exchange live). By
default no port codes fire and nothing reaches the BIDS events export — a typed
exchange is rapid and conversational, and would flood the marker channel. If a
study needs marker timestamps, route `Chat to participant` (code 69) and/or
`Chat from participant` (code 70) to LSL/TTL in the **Markers** window;
the markers stay bare (no message text) so the trigger channel remains legible.

## EEG port codes

SMACC marks experiment events — a cue played, a dream report, observed REM, the
lights toggled — by sending a numeric **port code** to its marker stream and writing a
matching line to the session log, keeping cue delivery and your neural data in sync.

### Configuring codes

Open the **Markers** window from the **Tools** column (in a Session or in the
Editor). It is the definitive home for everything about event signaling: a
**routing legend** (what the log file, the live preview, LSL, and TTL each
receive, and which switch governs it), the full event registry grouped by
category — including the events with no grid button (lights, panel controls,
biocals, chat, system) — and the
[hardware TTL transport](triggers.md#configuring-trigger-output-in-smacc).
For each event you can set:

- **Code** — the 8-bit port code (1–255) sent when the event triggers.
- **LSL** — whether a firing sends the code over the LSL marker stream.
- **TTL** — whether a firing sends the code over the hardware TTL trigger. The
    column is grayed out until a transport is enabled in the window's **Hardware
    TTL transport** section (the ticks are kept and re-arm with it). An event with
    neither LSL nor TTL ticked is log-only.
- **Preview** — whether the event shows in the live log preview. The session log
    *file* always records every event regardless; this only controls the on-screen
    preview.
- **Increment** — give an event a unique, increasing code on each firing (e.g. **dream
    reports**: 201, 202, 203, …) so individual occurrences are findable in the trigger
    channel. Off uses one fixed code each time.

**TTL safe max code** raises a soft warning for TTL-routed codes above it — handy
when your trigger hardware only accepts a limited range (some older systems do; LSL
carries any code). Codes must be unique among routed events and within 1–255; the
window blocks anything else.

**Custom events.** Use **Add event…** — in the **Event logging** panel itself, or in
the Markers window — to create your own button events (a label and a code); they
appear in the Event logging panel alongside the built-ins and can be removed again
with the Markers window's **Remove**. Built-in events can be retuned but not removed
or renamed.

Edits are staged until you press **Apply** (which validates them first); **Revert**
re-reads the session's current setup. The window stays available throughout a
session. If you change a code mid-session, the change is written to the log with a
timestamp, so the code-to-event mapping for that session is always recoverable.

Beyond port codes, SMACC logs the important interactions too — volume, color, device,
and fade changes — as plain log lines (no port code), so the session record is complete.

### Event logging panel

The manual event buttons (the sleep-stage family, Signal observed, Sleep onset, Note,
your custom events, …) live in the **Event logging** panel — open it from the session
window's **Tools** column. The sleep-stage buttons take a fixed keypad — **0** Wake,
**1** N1, **2** N2, **3** N3, **4** REM — and the remaining buttons take **5**–**9** in
order; the shortcuts are active while the panel is focused. The **Lights** toggle stays
on the main window (it also flips the dark theme).

**Signal observed.** One button covers every lucidity/communication signal a study uses
(LRLR, sniff, facial, …), so you don't need a separate button per signal. Pick the
**signal** type (the box is editable — type your own and it's remembered for the rest of
the session) and a **confidence** (certain / probable / possible) beside the button;
pressing it fires the marker immediately and logs your selection as the detail, so the
marker's timing tracks the observation. Confidence is recorded as a comment — it never
changes whether the marker reaches the EEG.

### Where codes live

Your codes are saved in the SMACC file (so they travel with it) and
written into every session `.log` (both the initial and final settings blocks), so any
session is self-documenting: you can decode its markers later even if the codes changed
mid-session.

## Event log

Every run writes a detailed `.log` to its own timestamped folder under the SMACC
file's **data directory** (e.g. `~/SMACC/data/`), capturing the events and settings
for that session. Open one later from the Launcher's **Analyze** to see a
summary, export its events to BIDS, or recover its settings.

### If SMACC crashes

Separately from the per-run logs, SMACC keeps a permanent crash log at
`~/SMACC/logs/crash.log`. Uncaught errors, Qt's own fatal messages, and — via
Python's `faulthandler` — the stack of every thread at a hard crash (such as an
access violation inside Qt or an audio driver) are appended there, even when no
session is running. Note that a hard-crash dump shows where the *Python* side
was at that moment, which is usually enough to identify the failing subsystem.
Every launch and every session start is also stamped in the file, so a crash
can be matched to its night and run folder. When reporting a crash, send
`crash.log` together with the affected run's folder. The file is rotated at
launch once it grows large (one older `crash.log.1` generation is kept).

## SMACC files (`.smacc`)

A **SMACC file** captures your study's whole configuration — cue files, volumes,
noise, visual cues, survey presets, event codes, display choices, and the **data
directory** where runs are written — in a single portable `.smacc`. Create one in
the Editor (the Launcher's **Create**/**Edit** buttons) or snapshot a running
Session with **File › Save SMACC file as…**. Opening one starts a new
session with that configuration. See [SMACC files](smacc-files.md) for the full
story (creating, the data directory, opening by double-click), and the
[SMACC file reference](reference/settings-file.md) for the exact on-disk format.

## Display preferences

Some display choices apply to a session and travel with the study in the SMACC
file: **always-on-top** (toggled per window — the Session window's **File**
menu, or each tool window's **View** menu, or **Ctrl+T** in whichever window is
active) and which **log levels** show in the preview (the checkboxes above the
log preview). Save them with the rest of the configuration from the Editor or
with **File › Save SMACC file as…** in a Session.

Tool windows close with **Ctrl+W** (or **File › Close window**) — that
only hides the window, with its state intact; the session keeps running and the
Session window's Tools column reopens it.

Separately, the machine remembers window positions and sizes and your recent files in
`~/SMACC/preferences.yaml`, restored on the next launch.
