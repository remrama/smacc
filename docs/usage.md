# Usage

SMACC opens to a small **launcher** where you pick a **settings file** and choose
what to do; from there you run a live session for collecting data. This page walks
through the main features.

<!-- Add an annotated screenshot of the launcher + main window here once available,
e.g.: ![SMACC main window](assets/screenshot-main.png) -->

## Opening SMACC

SMACC opens to a small launcher (its opening menu) rather than dropping straight
into a session. From here you:

- **pick a settings file** — the current `.smacc` is shown at the top, with
  **Open…** to choose another, **Edit…** to open it in the settings editor, and a
  **Recent** dropdown to switch between ones you have used. With none chosen, SMACC
  uses built-in defaults (and the seeded `default.smacc`), so it works out of the
  box. (See [Settings files](#settings-files-smacc) for what one holds.)
- **Start session** — open the live session interface using the selected settings,
  writing runs to that file's **data directory**. The run folder and log are created
  only now, when the session starts.
- **Create settings** — build a new `.smacc` in the **settings editor**: configure
  the tools (cues, noise, visual, event codes, surveys), choose a data directory,
  and save it anywhere. Use **Edit…** to reopen an existing one.
- **Design cues** — open the standalone **Cue designer** to build a simple tone cue
  and export it as a WAV into a study's `cues/` folder, ready to use from the Audio
  cue board (see [Designing a cue](#designing-a-cue)).
- **Analyze** — open a past session (a `.log`, a session folder, or a
  zipped session) to see a summary (events, duration, subject/session, dream
  reports), export its events to a BIDS `events.tsv`, or recover its settings to a
  `.smacc` — all without starting a new session.

Interface preferences (theme, log preview, always-on-top) live under **File
&rsaquo; Preferences** in the launcher. Closing a session (or other tool) returns
you to the launcher; closing the launcher quits SMACC. On the Windows build you can
also **double-click a `.smacc`** to jump straight into a session for it — closing it
returns to the launcher.

## Audio cues

Place sound files where your settings expect them — by default the data directory's
`cues/` folder (e.g. `~/SMACC/data/cues/`; `.wav`, `.mp3`, `.flac`, `.ogg`, and
`.aiff` are supported) — and trigger them from the cue controls. SMACC seeds a few
`demo-*` cues there so there is always something to test with. You start with one
cue — prefilled with a random demo — and use **+ Add cue** and each row's **✕** to
add or remove cues to match a protocol (one minimum, up to 20).

### Designing a cue

No sound file ready? Open **Design cues** from the launcher to build a simple cue
inside SMACC — no external audio editor needed. Lay out a sequence of **tone** and
**silence** segments (each tone has a frequency, duration, and level, with an
optional bell-like **decay**), add an optional whole-cue fade in/out, **Preview** it
on your default output, then **Export WAV…** into your study's `cues/` folder. The
exported file then appears in the Audio cue board like any other cue. The designer is
a standalone tool: it plays on the default device and ignores the session's device
routing and volume safety cap.

### Is the cue reaching the bedroom?

The Audio cue window has a **Monitoring** section — a *Sending* meter (what SMACC is
emitting) beside a *Bedroom* meter (what a mic actually picks up in the room) — so you
can confirm a cue is audible to the participant, not just leaving SMACC. See
[Audio &amp; routing](audio.md#is-the-cue-reaching-the-bedroom) for how to read them
and how to set up a dedicated monitor mic.

## Dream reports

Use the **Record Dream Report** button to record from the mic bound to the
**Bedroom mic** role in the **Devices** window.
Recordings are saved into the current session folder. Each report is also stamped
with the time elapsed since you pressed **Start recording** (in the Event logging
panel), so it is easy to locate in the EEG file; if recording has not been marked
yet, the report is still logged and SMACC reminds you to mark it.

Surveys (e.g. a dream-report questionnaire on Qualtrics or REDCap) open in your
browser. Manage your saved surveys with the **Manage…** button next to the survey
dropdown — each has a name and URL and is stored in your settings YAML. Select one
in the dropdown to open it automatically when recording starts, or open any saved
survey on its own from **File &rsaquo; Surveys** (each open is logged as a
`SurveyOpened` event).

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
all retunable in **File &rsaquo; Event codes…** like any built-in event.

**Sequences.** **Play sequence** runs every Seq-checked row top to bottom,
depressing each button as it goes. Pressing the *active biocal's* button skips just
that item (cancel marker, then on to the next); pressing the sequence button again
aborts the rest. Rows can **repeat** a biocal (eyes-closed twice, extra LRLRs —
use **+ Add** to add another instance), be reordered with **▲/▼**, and removed
with **✕**; the stack is locked while something is running. Need a biocal SMACC
doesn't ship? Use a custom event button in the Event logging panel instead.

**Voice recordings** live in your SMACC directory's `biocals/` folder (e.g.
`~/SMACC/biocals/`), seeded from a bundled set on first launch (generated with
[ElevenLabs](https://elevenlabs.io) text-to-speech). Prefer another voice or
language? Replace any file with your own recording under the same name — SMACC
never overwrites existing files, and each session start warns about any that
are missing (a biocal with a missing voice still runs, just unvoiced). The shared
**Voice volume** rides the cue route, so the master output cap and the
control-room monitor fan-out apply to instructions exactly as they do to cues.

## EEG portcodes

SMACC marks experiment events — a cue played, a dream report, observed REM, the
lights toggled — by sending a numeric **portcode** to its marker stream and writing a
matching line to the session log, keeping cue delivery and your neural data in sync.

### Configuring codes

Open **File &rsaquo; Event codes…** to see every event in one table. For each event you
can set:

- **Code** — the 8-bit portcode (1–255) sent when the event triggers.
- **Trigger** — whether the event is sent to the marker stream at all.
- **Preview** — whether the event shows in the live log preview. The session log
  *file* always records every event regardless; this only controls the on-screen
  preview.
- **Increment** — give an event a unique, increasing code on each firing (e.g. **dream
  reports**: 201, 202, 203, …) so individual occurrences are findable in the trigger
  channel. Off uses one fixed code each time.

**Safe max code** raises a soft warning for codes above it — handy when your trigger
hardware only accepts a limited range (some older systems do). Codes must be unique
among triggered events and within 1–255; the editor blocks anything else.

**Custom events.** Use **Add event…** to create your own button events (a label and a
code); they appear in the **Event logging** panel alongside the built-ins and can be
removed again with **Remove**. Built-in events can be retuned but not removed or renamed.

The editor stays available throughout a session. If you change a code mid-session, the
change is written to the log with a timestamp, so the code-to-event mapping for that
session is always recoverable.

Beyond portcodes, SMACC logs the important interactions too — volume, color, device,
and fade changes — as plain log lines (no portcode), so the session record is complete.

### Event logging panel

The manual event buttons (Start recording, REM detected, Sleep onset, your custom events, …) live in the
**Event logging** panel — open it from the session window's **Tools** column; the
first nine buttons take the 1–9 keyboard shortcuts while it's focused. The **Lights**
toggle stays on the main window (it also flips the dark theme).

### Where codes live

Your codes are saved in the `.smacc` settings file (so they travel with it) and
written into every session `.log` (both the initial and final settings blocks), so any
session is self-documenting: you can decode its markers later even if the codes changed
mid-session.

## Event log

Every run writes a detailed `.log` to its own timestamped folder under the settings
file's **data directory** (e.g. `~/SMACC/data/`), capturing the events and settings
for that session. Open one later from the launcher's **Analyze** to see a
summary, export its events to BIDS, or recover its settings.

## Settings files (`.smacc`)

A **settings file** captures your reusable setup — cue files, volumes, noise,
visual cues, survey presets, event codes, the display choices that apply to a
session (always-on-top and log-preview levels), and the **data directory** where runs
are written — in a single portable `.smacc` (plain YAML you can read and edit). The easiest way to build one is the **settings editor** (the launcher's
**Create settings**, or **Edit…** for an existing one): configure the tools, set the
data directory, and save. SMACC ships a `default.smacc` in your SMACC directory as a
working example you can copy. For the exact on-disk format — every field, the
sub-blocks, and the schema version — see the
[`.smacc` reference](reference/settings-file.md).

You can keep settings files anywhere — for instance one per participant
(`peter.smacc`, `paul.smacc`, …), each pointing at whatever data directory you like
(they can share one). Configuring settings and running a session are separate steps:
the editor never records a run, and a session never rewrites your settings file.

Cue/noise files and the data directory are stored **relative** to the `.smacc` when
they sit beside it (so a self-contained folder stays valid if you move, copy, or zip
it) and **absolute** when they point elsewhere.

### Opening a settings file

On the Windows build you can **double-click a `.smacc` file** to launch SMACC and go
straight to a session for it — the first launch offers to set up this association,
and you can (re)enable it any time from **File &rsaquo; Associate .smacc files
(Windows)** in a session. From a terminal, `SMACC path/to/file.smacc` does the same.

## Preferences

Some display choices apply to a session and are stored in the `.smacc` settings file,
so they travel with the study: **always-on-top** and which **log levels** show in the
preview. Edit them from **File &rsaquo; Preferences** in the launcher.

Separately, the machine remembers window positions and sizes and your recent files in
`~/SMACC/preferences.yaml`, restored on the next launch.
