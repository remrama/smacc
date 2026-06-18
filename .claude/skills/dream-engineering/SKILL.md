---
name: dream-engineering
description: The research use-case behind SMACC — dream engineering, targeted memory reactivation (TMR) and targeted lucidity reactivation (TLR), sleep-stage cueing, REM/NREM, lucidity signaling (LRLR), and overnight dream-report collection. Use when designing features, weighing UX, or interpreting requirements that depend on how sleep/dream researchers actually run a session.
---

# Dream engineering: the use-case behind SMACC

SMACC ("Sleep Manipulation And Communication Clickything") is the control surface a
researcher clicks during an **overnight sleep study** — to cue a sleeping
participant, mark events on the EEG, and collect dream reports. It is used by the
[Paller Lab](https://sites.northwestern.edu/pallerlab/) at Northwestern and the
[DxE Lab](https://www.dreamengineeringlab.com/). Designing for SMACC means designing
for that room at 3 a.m.

## Core concepts

- **Dream engineering** — deliberately influencing sleep and dreams (memory,
  lucidity, content) with timed sensory cues and feedback, rather than just
  observing them.
- **TMR (targeted memory reactivation)** — re-presenting a cue (a sound or odor)
  that was paired with learning *while the participant sleeps*, to reactivate and
  strengthen that specific memory. The cue must land in the right sleep stage.
- **TLR (targeted lucidity reactivation)** — a TMR-style protocol that re-presents
  cues associated with "notice you're dreaming" training during REM, to prompt
  **lucid dreaming**. SMACC's registry has generic `TrainingStart`/`End` markers for
  the learning phase (TMR cue learning, TLR practice).
- **Cueing** — playing the audio (or light) cue at the moment that matters. Timing
  relative to sleep stage is the whole game; a cue at the wrong time is wasted or
  wakes the participant.

## Sleep stages, briefly

A night cycles through **NREM** (N1 → N2 → N3, light to deep) and **REM** (where
most vivid dreaming and lucidity occur). A human (or another tool) scores the stage
from live EEG — SMACC does not. But its **markers must align with the EEG** so cues
and observations sit at the right point in that record.

## Lucidity & two-way communication

- A trained lucid dreamer can signal awareness from inside REM with a deliberate
  **left-right-left-right (LRLR) eye-movement** pattern, visible on EOG/EEG (the
  classic lucid-signaling paradigm). SMACC marks any such signal (LRLR, sniff,
  facial, …) with one generic `SignalObserved` marker, tagged with the signal type
  and a confidence.
- The **intercom** lets the experimenter **Talk** to the participant (marked in the
  EEG) and **Listen** back — two-way communication with a sleeping or lucid person.
- After an awakening, the participant gives a **dream report** (recorded audio + an
  optional survey). SMACC timestamps each report against the recording-start
  reference clock.

## A typical session, in SMACC terms

1. Set up the rig and a `.smacc` settings file (cues, devices, event codes).
1. Start the EEG recording → `RecordingStarted` marker sets the reference clock.
1. Watch the participant fall asleep (`SleepOnset`), then monitor stages; mark
   observations (`REMDetected`, `TechInRoom`, notes).
1. At the target stage, fire a **cue** (audio, sometimes a **BlinkStick** light),
   optionally with masking **noise**; each fires its marker.
1. Watch for a lucidity signal (`SignalObserved`); use the intercom as needed.
1. **Wake** the participant and **record a dream report** (`DreamReportStarted`,
   which increments so each report is unique); maybe open a survey.
1. Repeat across the night, then review the event log.

## Why this shapes design

- **Timing & markers are sacred.** Anything that delays a cue or misaligns a marker
  corrupts the science. Favor low-latency, predictable behavior; preserve the
  portcode contract (see the **portcodes** skill).
- **It runs in the dark, next to a sleeping person.** The operator is tired, the
  room is dark, and a misclick can wake a participant and end a rare data point. So
  the UI leans on:
  - large, glanceable controls and a **dark theme**;
  - **always-on-top**, so the control window never gets buried;
  - an **audio safety cap**, so a cue can't blast a sleeper (see the
    **audio-routing** skill);
  - clear device/routing indicators (which speaker am I about to play to?);
  - minimal, reversible interactions — confirm or cap the costly, irreversible ones.
- **Labs are heterogeneous.** Different amps, trigger transports, speakers, and
  protocols. Prefer *configuration over assumption*, and surface what's
  connected/missing rather than failing silently.

## Glossary (terms you'll meet in the code)

TMR, TLR, REM/NREM, sleep onset, cue, masking noise, LRLR (lucid eye signal),
dream report, clapper (a sync marker), portcode/trigger, intercom Talk/Listen.

## Further reading

The two labs' sites (linked above) describe their dream-engineering and TMR/TLR
work; SMACC's own [docs site](https://remrama.github.io/smacc/) covers the app.
Foundational background: Ken Paller and colleagues on TMR, and Stephen LaBerge's
work on lucid eye-signaling — worth a look when a feature hinges on the science.
