# Preface {#chap-index .unnumbered}

**Sleep Manipulation And Communication Clickything** (SMACC) is a Windows desktop
app for running sleep and dream studies — presenting cues to a sleeping participant,
communicating with them, marking events on the EEG, and collecting dream reports.

In a dream-engineering session the experimenter has to deliver a precisely-timed cue
to a sleeping participant, mark each event so it lines up with the EEG, talk with the
sleeper, and collect a dream report — all from a dark control room, late at night, on
whatever hardware the lab has. SMACC is the clickable control surface for that work:
one window per job, glanceable in the dark, with a volume safety cap and explicit
device routing so a misclick can't blast or mislead a sleeping participant.

## What SMACC does

- Trigger **audio cues** (and design them in-app with the Audio Cue Designer)
- Trigger **visual cues** on a BlinkStick or Philips Hue light
- Play masking **background noise**
- Run **biocalibrations** as timed, marked tasks
- Record **dream reports** and administer **surveys**
- **Talk, listen, and type** with the participant over an intercom
- Mark events with **EEG port codes** over LSL or a hardware TTL trigger
- Review and score recordings in the **EEG Annotator**
- Save a detailed **event log** for every run

## How this manual is organized

This is the SMACC user manual, published two ways from a single source: a live
website that tracks the current stable release, and a PDF attached to every release
for offline and historical reference. Both have identical content.

The manual is a book in five parts:

- **Getting started** installs SMACC and explains the `.smacc` study file that every
  session is configured from.
- **Running a session** is the core: the Launcher and Session window, then a chapter
  per tool — audio cues, visual cues, biocals, dream reports and surveys, the
  intercom, and EEG markers.
- **Devices, volume & timing** covers binding equipment, routing it to the tools, and
  the volume cap and stimulus latency that govern what the participant actually
  receives.
- **After the night** is the post-hoc side: the EEG Annotator, and troubleshooting.
- **Reference** documents every file SMACC reads and writes, field by field.

The appendices hold a [glossary](glossary.md#chap-glossary), the
[release notes](release-notes.md#chap-release-notes), the
[developer guide](contributing.md#chap-contributing), and
[credits](about.md#chap-about). A first-time user should read **Getting started** and
**Running a session** in order; the rest is there to reach for as needed.

## Conventions

- **Bold** marks the parts of the interface you act on — window names, buttons, and
  fields (the **Markers** window, **Apply**). Monospace marks filenames, paths, and
  literal values (`.smacc`, `COM3`).
- Notes, tips, and warnings appear as callouts. A **warning** flags something that can
  wake a participant, lose data, or mislead an analysis — read those before relying on
  a feature.
- Screenshots are numbered figures, captioned beneath the image.
- SMACC uses a precise vocabulary for event signaling: *event*, *marker*, *port
  code*, *trigger*, and *transport*, each meaning exactly one thing. The
  [Glossary](glossary.md#chap-glossary) defines these and the other recurring terms.

SMACC runs on 64-bit Windows 10 or later and installs per-user, with no administrator
rights. To download and install it, see [Installation](installation.md#chap-installation).
