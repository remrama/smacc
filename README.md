# Sleep Manipulation And Communication Clickything

[![CI](https://github.com/remrama/smacc/actions/workflows/ci.yml/badge.svg)](https://github.com/remrama/smacc/actions/workflows/ci.yml)
[![Release](https://github.com/remrama/smacc/actions/workflows/release.yml/badge.svg)](https://github.com/remrama/smacc/actions/workflows/release.yml)
[![Codecov](https://codecov.io/gh/remrama/smacc/graph/badge.svg)](https://codecov.io/gh/remrama/smacc)
[![Python](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

**SMACC** is a Windows desktop app for running sleep and dream studies: presenting
cues to a sleeping participant, communicating with them, marking events on the EEG,
and collecting dream reports.

Full documentation is at <https://remrama.github.io/smacc>.

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

## Installation

Download `SMACC-Setup.exe` from the latest release's _Assets_ on the
[releases page](https://github.com/remrama/smacc/releases) and run it. It installs
per-user (no administrator rights needed) on 64-bit Windows 10 or later. The
[documentation](https://remrama.github.io/smacc) covers other install options.

## Used by

SMACC is used for dream engineering research, including by
[Ken Paller's Cognitive Neuroscience Lab](https://sites.northwestern.edu/pallerlab)
at Northwestern University and
[Michelle Carr's Dream Engineering Lab](https://www.dreamengineeringlab.com) at the
University of Montreal.
