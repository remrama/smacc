# EEG Annotator

The **EEG Annotator** is SMACC's post-hoc viewer for recorded EEG: open a
file, scroll through the night, apply display filters, and place named
annotations — saved as a small sidecar file next to the recording, which is
**never modified**. It is a review tool, not a real-time display; nothing
about it runs during a live session.

It opens from the Launcher's **EEG Annotator** button and always runs as its own
window and process — so you can keep reviewing last night's file while tonight's
session runs.

**How it differs from a generic EEG viewer.** The Annotator is built for the
overnight cueing workflow, not for clinical reading:

- It is **read-only by contract** — the recording is never written; every mark,
    stage score, and overlay lives in a small sidecar beside it.
- It is **SMACC-aware** — it imports SMACC's own portcodes off the recording and
    can overlay a night's [session log](#session-log-overlay) (cues, dream
    reports, even the recorded report audio), so you see *what SMACC did* on the
    same timeline.
- It has **blind, multi-rater scoring** built in (see
    [blind-rater mode](#blind-rater-mode)) — for objective signal and stage
    scoring, not an afterthought.
- Its **[epoch model](#the-epoch-model)** is decoupled from the on-screen window
    and can be anchored to any feature.
- Recordings are **memory-mapped**, so an 8-hour high-density night opens in
    seconds and scrolls smoothly regardless of file size.

::: {.callout-note title="Built in, runs in its own process"}

The Annotator is part of SMACC — there is nothing extra to install. It opens
in its own process, so it can outlive the Launcher and a heavy recording can
never disturb a running session; that is why it appears as a separate window
rather than a panel inside the session app.

:::

## Supported recordings

| Format               | Open via                                        |
| -------------------- | ----------------------------------------------- |
| European Data Format | `.edf`                                          |
| BrainVision          | `.vhdr` (of the `.vhdr`/`.eeg`/`.vmrk` triplet) |
| FIF (MNE / Elekta)   | `.fif`                                          |
| Neuroscan            | `.cnt`                                          |
| EEGLAB               | `.set` (continuous recordings only)             |

The open dialog's file filter is generated from this list, so it never drifts
from what the tool can actually read. An *epoched* `.set` is not a continuous
recording and is rejected with MNE's own message. Recordings are memory-mapped,
never loaded whole: an 8-hour high-density night opens in seconds and scrolling
stays smooth regardless of file size.

## Viewing

- **Window length** — 10/30/60/120 s pages; **30 s** is the default. This is the
    *on-screen* window, separate from the [scoring epoch](#the-epoch-model).
- **Filters** — high-pass, low-pass, and a 50/60 Hz notch, applied to the
    *display only* (zero-phase, so nothing shifts in time). Recordings open
    **unfiltered** — the usual sleep view is two clicks away (HP 0.3 Hz, LP
    35 Hz).
- **Scale** — microvolts per channel lane; smaller numbers mean bigger
    traces. Trigger/stim channels are auto-fit to their lane.
- **Channels…** picks which channels are shown and reorders them; each channel
    type (EEG, EOG, EMG, …) scales on its own. **Save profile…** stores the whole
    montage — channels, filters, scale, and the window/epoch lengths — to a file,
    and **Load profile…** applies it to any recording, so a lab's house view is
    one click on every night.
- **Export figure…** writes the current window to a publication-ready **PNG, PDF,
    or SVG**.
- The status bar shows the cursor's time from recording start **and the
    wall-clock time**, so events line up with the night's session log.

### Keyboard navigation

The arrow keys drive the view from anywhere in the window — you do **not** have
to click the traces first:

| Key                   | Action                                   |
| --------------------- | ---------------------------------------- |
| `←` / `→`             | step back / forward one **epoch**        |
| `Shift`+`←` / `→`     | nudge 1 s, to peek across a boundary     |
| `↑` / `↓`             | bigger / smaller traces (`Shift` = fine) |
| `Home` / `End`        | jump to the start / end of the recording |
| `PageUp` / `PageDown` | page back / forward one window           |

The mouse wheel and scrollbar scroll as well.

### The epoch model

The **scoring epoch** is a first-class concept, deliberately *separate* from the
on-screen window — a 30 s epoch can be inspected inside a 60 s window, and the
arrow keys step by epoch regardless of how much is on screen.

- **Epoch** length is set in seconds (default **30 s**, the polysomnography
    standard; 1–300 s).
- **Epoch grid** draws faint, **numbered** epoch boundaries over the traces.
- **Anchor epochs to view** starts an epoch at the left edge of the current view
    and back/front-fills the whole grid from there (boundaries fall at
    `anchor + k·epoch`) — so you can line the grid up with lights-out or any
    feature in the record. **Reset anchor** puts epoch 1 back at the recording
    start.
- **Time axis** labels the x-axis as wall-clock **Clock** time or **Elapsed**
    seconds from the start. Clock needs a recording start time; an anonymized file
    that has none falls back to elapsed.

## Annotating

1. **Drag** across the traces to mark a span (drag never pans — the time
    axis only moves when you ask it to). To drop a **point** instead,
    **Ctrl+click** (or press **M**) at the cursor.
1. Name it in the label dialog — recent labels and common marks (LRLR,
    arousal, artifact, cue response) are one click; free text always works.
    Tick **instantaneous** to keep just the moment instead of the dragged span.
1. A plain **click** on an annotation selects it; use the side list to rename,
    delete, or jump to one (double-click).
1. **Save annotations** writes the sidecar next to the recording:
    `night1.edf` → `night1.annotations.tsv` (+ a small `.json` describing it).
    The recording itself is **never modified**. Unsaved changes star the title
    and prompt before closing, and saving over a sidecar **this review did not
    open** asks first — so you never clobber another file by accident.

For fast signal scoring, the **Quick marks** row drops a labeled point mark at
the cursor in one click — or press **1–9** for the first nine. Use **Edit
palette…** to set the buttons; the palette defaults to the lucid eye-signal
vocabulary (LRLR, LRLRx2, LRLRx3, IEIE).

**Autosave & recovery.** A couple of seconds after you stop editing, your work
autosaves to a distinct `night1.annotations.autosave.tsv` (a per-rater file when
a [rater id](#multiple-raters) is set). It is purely a crash net — if the tool
finds one when a recording opens, a non-modal banner offers to **Restore** or
**Dismiss** it; nothing is ever applied silently, and your real sidecar is
untouched until you Save.

Events already stored **inside** the recording — amp markers, SMACC's own
trigger codes — are imported automatically the *first* time a file is
reviewed, so your cues appear on the traces alongside your new marks. Once a
sidecar exists it is the single source of truth (nothing is re-imported or
duplicated).

The sidecar format is documented in the
[annotations file reference](reference/annotations-file.md).

## Sleep staging

Score the night a 30 s epoch at a time. Staging is a separate layer from
annotating — both are always live on the same view, so you can drop an LRLR or
arousal mark mid-sweep without leaving your place — and it saves to its **own**
sidecar (`night1.edf` → `night1.stages.tsv`), a partition of one stage per epoch,
never mixed into the event annotations.

**Stage focus.** Press **Tab** (or the **Stage focus** button) to start a sweep.
The view locks to one epoch per screen and the epoch grid/length is fixed (so a
score can't land in the wrong span), a **STAGE FOCUS** chip shows in the status
bar, and the epoch at the left edge — the one you're about to score — gets a teal
bracket.

**Scoring.** With stage focus on, the number keys score the epoch at the left
edge and **auto-advance** to the next one:

| Key               | AASM stage                  |
| ----------------- | --------------------------- |
| `W`               | Wake                        |
| `1` / `2` / `3`   | N1 / N2 / N3                |
| `R`               | REM                         |
| `0` / `Backspace` | clear (un-score, stays put) |

The stage **buttons** do the same with the mouse and also work outside stage
focus (so the number keys stay free for [quick marks](#annotating) until you
deliberately start a sweep). Re-scoring an epoch overwrites it; `Left`/`Right`
page back and forth to fix one.

**Reading the night.** Each scored epoch tints the traces a faint stage colour,
the big readout names the current epoch's stage, and a **hypnogram overview
strip** under the traces shows the whole night as a colour staircase — click it
to jump anywhere. The status bar counts scored / total epochs.

**Scoring manual.** AASM (W/N1/N2/N3/R) is the default; switch the **Manual**
dropdown to **Rechtschaffen & Kales** (S1–S4 + a Movement-Time epoch) before you
start — it locks once the first epoch is scored, and a resumed hypnogram reopens
under the manual it was scored with. A sub-epoch **movement or artifact** isn't a
stage under AASM; mark it as an [annotation](#annotating) over the epoch's stage
instead (`Artifact` is a default quick mark).

Each [rater](#multiple-raters) scores to their own `night1.stages.<id>.tsv`, so
two scorers of one night produce two hypnograms to compare.

## Session log overlay

Load the night's SMACC session [`.log`](reference/session-log.md) onto the
timeline as a **read-only reference track** — every marker, cue, dream report,
and survey shown where it happened, so you see what SMACC *did* alongside the
EEG. Click **Load session log…** in the **Session log** panel. Ticks appear in a
thin lane across the top, coloured by log level, with the full message on hover.
The per-level checkboxes show or hide levels just like the live preview —
`DEBUG` (raw-trigger and volume-edit noise) is off by default. The log is
reference context only: it is never editable and never saved into your
annotations.

You can load a log **with or without a recording open**. With one, it overlays
and aligns to *that* recording's clock. With none, it opens **standalone** on a
bare time axis — for inspecting a log on its own (the **Analyzer**'s *Open log in
EEG Annotator* hands a session off this way). Opening a recording while a
standalone log is shown switches to the overlaid view.

**Artifacts.** Selecting a dream-report entry lets you **Play** its recorded
audio (`report-NN.wav`, beside the log in the session folder) — press again to
stop — and **Reveal file** opens that folder in the file browser. Playback is
disabled for an entry with no audio (a marker, or a log opened away from its
recordings).

**Aligning the log.** The log's timestamps come from the recording PC while the
EEG's clock comes from the amplifier, so the two can differ by seconds or more.
Slide the whole log along the EEG to line them up, three ways — all adjusting one
offset:

- **Drag the log lane.** A left-drag that starts in the top lane slides the log
    (a drag anywhere else still draws an annotation). On release it snaps onto a
    nearby mark of yours, so a clapper lands exactly on the artifact it made.
- **Pair an entry to a feature.** Select a log entry, click **Align entry to
    feature…**, then click the EEG feature it produced — useful when the two are
    far apart to drag. (Esc cancels.)
- **Nudge the offset.** The **Offset** box is the exact value, and the fine
    control.

**Auto-align to triggers.** When the amplifier itself recorded SMACC's trigger
codes — a hardware-TTL rig, where the codes are embedded events in the EEG file —
**Auto-align to triggers** estimates the offset by matching the log's markers to
them. It anchors only on *rare* codes (a clapper, a dream report, the
recording-start marker), never the periodic cue codes that could line up at the
wrong firing, and grades the result: a confident match is applied silently, a
low-confidence one is applied but marked *unverified* in the status bar, and an
unreliable or contradictory one (too few matches, or two clusters from a clock
jump or the wrong log) is refused so you align by hand instead. It runs
automatically when a log is loaded, and the button re-runs it. An LSL-only rig
records markers only to its side file, not the EEG, so there is nothing embedded
to match — use the manual gestures.

The classic clapper workflow fits directly: press **Clapper** on the SMACC PC at
the same instant as a manual trigger on the recording system, then pair (or drag)
the logged clapper onto the marker it left in the EEG. Clapping at both lights-off
and lights-on gives two reference points. A recording with no start time
(anonymized) has no absolute anchor, so the log starts at its first entry and you
align it entirely by hand.

The log is **never shown in a blind review** — it records every cue and portcode,
which would unblind the rater.

## Multiple raters

For blind, multi-rater scoring, give each reviewer a **rater id** — click the
**Rater** button, or launch with `--rater <id>`. Their annotations then save to
a per-rater sidecar (`night1.annotations.alice.tsv`) instead of the plain one,
so several raters can score the same recording without overwriting each other.
The active id shows in the window title and on the Rater button, and the first
save under an id confirms it (so a forgotten id is caught). Leave it blank for
an ordinary single-rater review. See the
[annotations file reference](reference/annotations-file.md#multiple-raters).

Once several raters have scored a recording, opening it shows the **other
raters** as a read-only overlay — each rater's marks in their own colour behind
your editable ones — with a show/hide checkbox per rater in the **Other raters**
list. Only your own marks are clickable and editable; the overlay is for
comparison. (Overlays are off during a blind review, so a blind rater never sees
their peers.)

## Blind-rater mode

Objective scoring asks raters to judge the EEG without seeing what was already
marked. The **Blind** button (or `--blind`) filters annotations **before they
are ever shown**, so a rater cannot glimpse what is hidden, with three presets:

- **Fully naive** — every mark is hidden; the rater scrolls a clean recording.
- **Reports visible** — only dream-report markers are shown; detected signals
    and cues are hidden.
- **Signal-present (classify only)** — signal *positions* are shown with their
    labels blanked (a `?`), so the rater sees *where* a signal is and classifies
    *what* it is.

Blind mode **requires a rater id** — a blind review seeds from the coordinator's
truth sidecar (`night1.annotations.tsv`) but saves to the rater's own
(`night1.annotations.alice.tsv`), so the truth file is never overwritten and
each rater's judgements stay separate for later comparison. Reopening a rater's
own file resumes their work unfiltered.

A coordinator can save a preset (plus the visible/signal label lists and a
quick-mark palette) as a shareable `study.smacc-blind.json` and hand out a
one-click command:

```sh
SMACC.exe --eeg --rater alice --blind study.smacc-blind.json night1.edf
```

Blinding is a workflow aid, not a security boundary: the guarantee is that the
app never *renders* a hidden label. Someone with file access can still read the
recording or the truth sidecar directly.

## For developers

Run it from a source checkout:

```sh
uv sync --extra dev
uv run python -m smacc.eeg [recording.edf]
```
