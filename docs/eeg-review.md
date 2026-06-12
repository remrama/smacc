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

Events already stored **inside** the recording — amp markers, SMACC's own
trigger codes — are imported automatically the *first* time a file is
reviewed, so your cues appear on the traces alongside your new marks. Once a
sidecar exists it is the single source of truth (nothing is re-imported or
duplicated).

The sidecar format is documented in the
[annotations file reference](reference/annotations-file.md).

## Multiple raters

For blind, multi-rater scoring, give each reviewer a **rater id** — click the
**Rater** button, or launch with `--rater <id>`. Their annotations then save to
a per-rater sidecar (`night1.annotations.alice.tsv`) instead of the plain one,
so several raters can score the same recording without overwriting each other.
The active id shows in the window title and on the Rater button, and the first
save under an id confirms it (so a forgotten id is caught). Leave it blank for
an ordinary single-rater review. See the
[annotations file reference](reference/annotations-file.md#multiple-raters).

## For developers

Run it from a source checkout with the `eeg` extra:

```sh
uv sync --extra dev --extra eeg
uv run python -m smacc.eeg [recording.edf]
```
