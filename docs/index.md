# SMACC

**Sleep Manipulation And Communication Clickything** (SMACC) is a Windows desktop
app for running sleep and dream studies — presenting cues to a sleeping participant,
communicating with them, marking events on the EEG, and collecting dream reports.

In a dream-engineering session the experimenter has to deliver a precisely-timed cue
to a sleeping participant, mark each event so it lines up with the EEG, talk with the
sleeper, and collect a dream report — all from a dark control room, late at night, on
whatever hardware the lab has. SMACC is the clickable control surface for that work:
one window per job, glanceable in the dark, with a volume safety cap and explicit
device routing so a misclick can't blast or mislead a sleeping participant.

[Download SMACC](https://github.com/remrama/smacc/releases/latest/download/SMACC-Setup.exe){ .md-button .md-button--primary }
[Installation guide](installation.md){ .md-button }

The button downloads the installer (`SMACC-Setup.exe`) for the latest version, which
installs per-user (no admin rights) and runs on 64-bit Windows 10 or later. See
[Installation](installation.md), which also covers the Windows SmartScreen warning on
the unsigned download and how to get older versions.

Working offline? [Download these docs as a single PDF](https://remrama.github.io/smacc/latest/pdf/smacc-manual.pdf).

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

## Get started

**Getting started**

- [Installation](installation.md) — download and run SMACC.
- [SMACC files](smacc-files.md) — create and reuse a study's configuration (`.smacc`).

**Running a session**

- [Overview](usage.md) — the Launcher, the Session window, and the tools.
- [Audio cues](audio-cues.md) · [Visual cues](visual.md) · [Biocals](biocals.md) ·
    [Dream reports & surveys](surveys.md) · [Intercom & chat](intercom.md) ·
    [Markers & port codes](triggers.md)

**Devices, volume & timing**

- [Audio routing](audio.md) · [Compatible devices](devices.md) ·
    [Volume & latency](latency.md)

**After the night**

- [EEG Annotator](eeg-annotator.md) — review and score recorded EEG.
- [Troubleshooting](troubleshooting.md) · [Reference](reference/index.md) ·
    [Contributing](contributing.md)

## Used by

SMACC is used in dream engineering research, including by:

- [Ken Paller's Cognitive Neuroscience Lab](https://sites.northwestern.edu/pallerlab/)
    at Northwestern University
    - Torres-Platas et al. (2026). Intentional lucid dreaming with a transformative learning agenda. *Research Square* doi:[10.21203/rs.3.rs-8745420/v1](https://doi.org/10.21203/rs.3.rs-8745420/v1)
    - Konkoly et al. (2026). Using real-time reporting to investigate visual experiences in dreams. *J Cogn Neurosci* doi:[10.1162/jocn.a.107](https://doi.org/10.1162/JOCN.a.107)
    - Morris et al. (2026). Inducing lucid dreaming based on a contemplative practice of compassion. *Brain Sci* doi:[10.3390/brainsci16030315](https://doi.org/10.3390/brainsci16030315)
    - Konkoly et al. (2026). Creative problem-solving after experimentally provoking dreams of unsolved puzzles during REM sleep. *Neurosci Conscious* doi:[10.1093/nc/niaf067](https://doi.org/10.1093/nc/niaf067)
    - Konkoly et al. (2025). Investigating dreams by strategically presenting sounds during REM sleep to reactivate waking experiences. *Neuropsychologia* doi:[10.1016/j.neuropsychologia.2025.109229](https://doi.org/10.1016/j.neuropsychologia.2025.109229)
    - Morris et al. (2025). Lucid dreaming of a prior virtual-reality experience with ego-transcendent qualities: A proof-of-concept study. *Neurosci Conscious* doi:[10.1093/nc/niaf017](https://doi.org/10.1093/nc/niaf017)
    - Mundt et al. (2024). Treating narcolepsy-related nightmares with cognitive behavioural therapy and targeted lucidity reactivation: A pilot study. *J Sleep Res* doi:[10.1111/jsr.14384](https://doi.org/10.1111/jsr.14384)
    - Wolk et al. (2024). Lucid dreams from reactivating mindfulness during REM sleep: A pilot study. *Int J Dream Res* doi:[10.11588/ijodr.2024.2.98233](https://doi.org/10.11588/ijodr.2024.2.98233)
- [Michelle Carr's Dream Engineering Lab](https://www.dreamengineeringlab.com/)
    at the University of Montreal and the Center for Advanced Research in Sleep Medicine
    - Jafarzadeh Esfahani et al. (2024). Highly effective verified lucid dream induction using combined cognitive-sensory training and wearable EEG: A multi-centre study. *bioRxiv* doi:[10.1101/2024.06.21.600133](https://doi.org/10.1101/2024.06.21.600133)

SMACC is free software released under the
[GPL-3.0-or-later](https://github.com/remrama/smacc/blob/main/LICENSE.txt) license.
