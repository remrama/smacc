# EEG review

SMACC's **EEG review tool** is a post-hoc viewer for recorded EEG: open a
file, scroll through the night, apply display filters, and place named
annotations — saved as a small sidecar file next to the recording, which is
**never modified**. It is a review tool, not a real-time display; nothing
about it runs during a live session.

It opens from the Launcher's **Review EEG** button, from its own Start-menu
entry (**SMACC EEG review**), and always runs as its own window and process —
you can keep reviewing last night's file while tonight's session runs.

!!! note "An optional component"

    The viewer ships as the installer's **EEG Review Tools** component, off by
    default (it carries the MNE library, which would triple the install for
    labs that only run sessions). To add it later, re-run the
    [installer](installation.md) and pick **Full installation** — the existing
    install is upgraded in place. When the component is missing, the
    Launcher's button is shown disabled with a hint, so you always know the
    tool exists.

## Supported recordings

| Format               | Open via                                        |
| -------------------- | ----------------------------------------------- |
| European Data Format | `.edf`                                          |
| BrainVision          | `.vhdr` (of the `.vhdr`/`.eeg`/`.vmrk` triplet) |
| FIF (MNE / Elekta)   | `.fif`                                          |

Recordings are memory-mapped, never loaded whole: an 8-hour high-density
night opens in seconds and scrolling stays smooth regardless of file size.

## Viewing

- **Window length** — 10/30/60/120 s pages; **30 s** (one scoring epoch) is
    the default. PageUp/PageDown page; the mouse wheel and scrollbar scroll;
    click the traces and the arrow keys nudge, Home/End jump.
- **Filters** — high-pass, low-pass, and a 50/60 Hz notch, applied to the
    *display only* (zero-phase, so nothing shifts in time). Recordings open
    **unfiltered** — the usual sleep view is two clicks away (HP 0.3 Hz, LP
    35 Hz).
- **Scale** — microvolts per channel lane; smaller numbers mean bigger
    traces. Trigger/stim channels are auto-fit to their lane.
- The status bar shows the cursor's time from recording start **and the
    wall-clock time**, so events line up with the night's session log.

## Annotating

1. **Drag** across the traces to mark a span (drag never pans — the time
    axis only moves when you ask it to).
1. Name it in the label dialog — recent labels and common marks (LRLR,
    arousal, artifact, cue response) are one click; free text always works.
    Tick **instantaneous** to keep just the moment instead of the dragged span.
1. **Click** an annotation to select it; use the side list to rename,
    delete, or jump to one (double-click).
1. **Save annotations** writes the sidecar next to the recording:
    `night1.edf` → `night1.annotations.tsv` (+ a small `.json` describing it).
    Unsaved changes star the title and prompt before closing.

For fast signal scoring, the **Quick marks** row drops a labeled point mark at
the cursor in one click — or press **1–9** for the first nine. Use **Edit
palette…** to set the buttons; the palette defaults to the lucid eye-signal
vocabulary (LRLR, LRLRx2, LRLRx3, IEIE).

Events already stored **inside** the recording — amp markers, SMACC's own
trigger codes — are imported automatically the *first* time a file is
reviewed, so your cues appear on the traces alongside your new marks. Once a
sidecar exists it is the single source of truth (nothing is re-imported or
duplicated).

The sidecar format is documented in the
[annotations file reference](reference/annotations-file.md).

## Session log overlay

Load the night's SMACC session [`.log`](reference/session-log.md) onto the
timeline as a **read-only reference track** — every marker, cue, dream report,
and survey shown where it happened, so you see what SMACC *did* alongside the
EEG. Click **Load session log…** in the **Session log** panel (a recording must
be open; the log aligns to *its* clock). Ticks appear in a thin lane across the
top, coloured by log level, with the full message on hover. The per-level
checkboxes show or hide levels just like the live preview — `DEBUG` (raw-trigger
and volume-edit noise) is off by default. The log is reference context only: it
is never editable and never saved into your annotations.

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
SMACC-EEG.exe --rater alice --blind study.smacc-blind.json night1.edf
```

Blinding is a workflow aid, not a security boundary: the guarantee is that the
app never *renders* a hidden label. Someone with file access can still read the
recording or the truth sidecar directly.

## For developers

Run it from a source checkout with the `eeg` extra:

```sh
uv sync --extra dev --extra eeg
uv run python -m smacc.eeg [recording.edf]
```
