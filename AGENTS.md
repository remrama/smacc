# Agent & contributor instructions

This is the canonical instruction file for both human contributors and AI coding
assistants working on SMACC.

Human contributors should open a
[GitHub issue](https://github.com/remrama/smacc/issues) for new feature requests or
bug reports before starting work.

## Conventions

- Always use `uv` when running Python scripts or installing dependencies. Never
    `pip install` or run naked `python`.
- One-line commits with a [Conventional Commits](https://www.conventionalcommits.org)
    prefix (`feat:`, `fix:`, `docs:`, …); no commit body and no AI attribution. Pull
    request bodies stay brief. Full guide:
    [Commit and pull-request style](./docs/contributing.md#commit-and-pull-request-style).

## Architecture at a glance

SMACC is a PyQt6 desktop app (`src/smacc/`). A launcher opens a settings (`.smacc`)
file, then a set of per-modality **tool windows** — each a `ModalityWindow`
([`panels/base.py`](./src/smacc/panels/base.py)) sharing one `SmaccSession`
([`session.py`](./src/smacc/session.py)). Panels emit markers and log lines through
the session (`emit_event`), persist via `gather_state`/`apply_state`, and own their
own [`sounddevice`](https://python-sounddevice.readthedocs.io/) streams.

Deeper subsystem and domain context lives in skills under
[`.claude/skills/`](./.claude/skills/): **dream-engineering** (the research
use-case), **portcodes** (EEG triggers/markers), and **audio-routing** (devices,
routing, volume).

## Development

The full development guide — environment setup, running the app, tests, linting,
building the executable, and building the docs — lives in the Contributing page
so it is not duplicated here: [docs/contributing.md](./docs/contributing.md).

See the [README](./README.md) for user-facing project information.
