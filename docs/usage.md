# Usage

SMACC opens to a small **launcher** where you pick a study and choose what to do;
from there you run a live session for collecting data. This page walks through the
main features.

<!-- Add an annotated screenshot of the launcher + main window here once available,
e.g.: ![SMACC main window](assets/screenshot-main.png) -->

## Opening SMACC

SMACC opens to a small launcher (its opening menu) rather than dropping straight
into a session. From here you:

- **pick a study** — the current study is shown at the top, with **Open…** to
  choose another study folder, **Edit…** to open the current study in the designer,
  and a **Recent** dropdown to switch between ones you have used. Until you pick
  one, SMACC uses an auto-managed `default` study, so it works out of the box.
  (See [Study config](#study-config-smacc) for what a study holds.)
- **Start session** — open the live session interface for the selected study,
  loading its saved `study.smacc` if it has one. A session's run folder and log
  are created only now, when the session starts.
- **Create study** — name a new study and set it up in the **study designer**:
  configure its tools (cues, noise, visual, event codes, surveys) and save them to
  the study's `study.smacc`. Use **Edit…** to reopen an existing study there.
- **Analyze session** — open a past session (a `.log`, a session folder, or a
  zipped session/study) to see a summary (events, duration, subject/session, dream
  reports), export its events to a BIDS `events.tsv`, or recover its study config to
  a `.smacc` — all without starting a new session.

Closing a session (or other tool) returns you to the launcher; closing the
launcher quits SMACC. On the Windows build you can also **double-click a `.smacc`**
to jump straight into a session for that study — closing it returns to the launcher.

## Audio cues

Place sound files in your study's `cues/` folder (e.g.
`~/SMACC/studies/default/cues/`; `.wav`, `.mp3`, `.flac`, `.ogg`, and `.aiff` are
supported) and trigger them from the cue controls. SMACC seeds a few `demo-*`
cues into each study so there is always something to test with.

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

The editor stays available throughout a session. If you change a code mid-study, the
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

Your codes are saved in the study `.smacc` file (so they travel with the study) and
written into every session `.log` (both the initial and final settings blocks), so any
session is self-documenting: you can decode its markers later even if the codes changed
mid-study.

## Event log

Every run writes a detailed `.log` to its own timestamped folder under its
study's `sessions/` (e.g. `~/SMACC/studies/default/sessions/`), capturing the
events and settings for that session. Open one later from the launcher's
**Analyze session** to see a summary, export its events to BIDS, or recover its
study config.

## Study config (`.smacc`)

A **study** captures your reusable setup — cue files, volumes, noise, BlinkStick
color, survey presets, event codes — in a single portable `.smacc` file (plain YAML you
can read and edit). The easiest way to build one is the **study designer** (the
launcher's **Create study**, or **Edit…** for an existing one), which configures all
the tools and saves them to the study's `study.smacc`. You can also save the current
setup from a live session with **File &rsaquo; Export study (.smacc)…** and reload it
with **File &rsaquo; Load study (.smacc)…**, or pull the initial or final setup back
out of a session `.log` with **File &rsaquo; Load study from log…**.

Cue/noise files are *referenced*, never copied. When a referenced sound sits in or
below the same folder as the `.smacc` file, its path is stored **relative**, so a
study folder (the `.smacc` plus its `cues/`) stays valid if you move, copy, or zip
it. Sounds outside the study folder are stored as absolute paths.

### Opening a study

On the Windows build you can **double-click a `.smacc` file** to launch SMACC with
that study already loaded — the first launch offers to set up this association, and
you can (re)enable it any time from **File &rsaquo; Associate .smacc files
(Windows)**. From a terminal, `SMACC path/to/study.smacc` does the same.

## Preferences

SMACC remembers operator/machine choices — window size and position, light/dark
theme, always-on-top, and which log levels show in the preview — in
`~/SMACC/preferences.yaml`, restored on the next launch. These are separate from a
portable study; they stay with this machine.
