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
- **Analyze session** — open a past session (a `.log`, a session folder, or a
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
`demo-*` cues there so there is always something to test with.

## Dream reports

Use the **Record Dream Report** button to record from the selected input device.
Choose the device from **Audio &rsaquo; Input device &rsaquo; [choose device]**.
Recordings are saved into the current session folder.

Surveys (e.g. a dream-report questionnaire on Qualtrics or REDCap) open in your
browser. Manage your saved surveys with the **Manage…** button next to the survey
dropdown — each has a name and URL and is stored in your settings YAML. Select one
in the dropdown to open it automatically when recording starts, or open any saved
survey on its own from **File &rsaquo; Surveys** (each open is logged as a
`SurveyOpened` event).

## EEG portcodes

SMACC marks experiment events — a cue played, a dream report, observed REM, the
lights toggled — by sending a numeric **portcode** to its marker stream and writing a
matching line to the session log, keeping cue delivery and your neural data in sync.

### Configuring codes

Open **File &rsaquo; Event codes…** to see every event in one table. For each event you
can set:

- **Code** — the 8-bit portcode (1–255) sent when the event triggers.
- **Trigger** — whether the event is sent to the marker stream at all.
- **Preview** — whether the event shows in the live log viewer. The session log
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

The manual event buttons (REM detected, Sleep onset, your custom events, …) live in the
**Event logging** panel — open it from the session window's **Open tools** column; the
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
for that session. Open one later from the launcher's **Analyze session** to see a
summary, export its events to BIDS, or recover its settings.

## Settings files (`.smacc`)

A **settings file** captures your reusable, data-related setup — cue files, volumes,
noise, BlinkStick color, survey presets, event codes, and the **data directory**
where runs are written — in a single portable `.smacc` (plain YAML you can read and
edit). The easiest way to build one is the **settings editor** (the launcher's
**Create settings**, or **Edit…** for an existing one): configure the tools, set the
data directory, and save. SMACC ships a `default.smacc` in your SMACC directory as a
working example you can copy.

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

SMACC remembers interface choices — window size and position, light/dark theme,
always-on-top, and which log levels show in the preview — in
`~/SMACC/preferences.yaml`, restored on the next launch. Edit them from **File
&rsaquo; Preferences** in the launcher. These are machine-level, separate from a
portable settings file.
