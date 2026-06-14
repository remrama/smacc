# Contributing

!!! info "For both human and AI contributors"

    This page is the canonical development guide for SMACC. It is written for both
    human contributors and AI coding assistants — AI agents are pointed here from
    [`AGENTS.md`](https://github.com/remrama/smacc/blob/main/AGENTS.md), so the
    instructions live here once rather than being duplicated across files.

!!! info "Requesting a change? Open a GitHub issue"

    Human contributors should open a
    [GitHub issue](https://github.com/remrama/smacc/issues) for new feature
    requests or bug reports before starting work, so changes can be discussed
    first.

## Conventions

- Always use [uv](https://docs.astral.sh/uv/) to run Python scripts and install
    dependencies. Never `pip install` or run naked `python`.
- Use the marker vocabulary consistently in UI text, docs, and docstrings — *event*,
    *marker*, *port code*, *trigger*, *transport* each mean exactly one thing; see the
    [terminology table](triggers.md#terminology).
- Write the docs as **reference**, not marketing: lead with the fact, keep pages
    scannable (short paragraphs, tables, steps), and go easy on em-dashes and the
    "not X, but Y" construction. Page filenames are stable, so cross-link with
    relative links and matching heading anchors.
- Pick log levels by the [session-log convention](reference/session-log.md#log-levels):
    `DEBUG` for housekeeping/high-frequency detail, `INFO` for markers and meaningful
    operator actions, `WARNING` for mid-session config changes and recoverable faults,
    `ERROR` for faults that cost something. The file records every level, so demoting a
    line to `DEBUG` only moves it out of the default live preview, never out of the
    record.

## Commit and pull-request style

Keep the history skimmable and merge commits clean.

**Commits**

- One line only — a subject, with no body or extended description.
- Start with a [Conventional Commits](https://www.conventionalcommits.org/) prefix:
    `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`, `build:`, `ci:`, or
    `perf:`.
- Imperative mood, lower-case after the prefix, no trailing period, and ideally
    under ~72 characters.
- No AI attribution or co-author trailers.

```text
feat: optional hardware TTL trigger output
docs: document audio routing
fix: clamp incrementing port codes to 255
```

**Pull requests**

- The title follows the same one-line Conventional-Commits rule — on a squash merge
    it becomes the commit subject (GitHub appends the `(#NN)` PR number).
- The body is a brief summary, not an exhaustive change list: what changed, why, and
    how it was verified. A few sentences or bullets is plenty.
- No AI attribution footer.

**Merging**

- Squash-merge, and clear the auto-generated commit body so the merged commit is the
    one-line title alone — no bundled description or commit list.

## Development

```sh
uv sync --extra dev        # create the environment with dev tools
uv run python -m smacc     # launch the app
uv run pytest              # run the test suite
uv run ruff check .        # lint
uv run ruff format .       # format
uv run mypy                # type-check
uv run --extra docs mdformat .   # format Markdown (docs, README, …)
pre-commit install         # enable the lint/format/type-check git hooks
```

`uv run smacc` also works once the environment is synced — it's the installed GUI
launcher and opens no console window, so prefer `python -m smacc` when you want
terminal output (e.g. tracebacks).

### Tests

The suite runs headless. `tests/conftest.py` selects Qt's `offscreen` platform before
any Qt import, so the GUI tests (built on
[pytest-qt](https://pytest-qt.readthedocs.io/)) construct windows and panels with no
display and no popups — there's no extra setup on your part. Hardware access (audio
device enumeration, the Windows volume read-out) is stubbed in fixtures, so tests don't
depend on the machine's audio setup.

```sh
uv run --extra dev --extra eeg pytest --cov=smacc --cov-report=term-missing   # CI also adds --cov-report=xml
```

To actually watch a test render, override the platform for that run (Windows:
`$env:QT_QPA_PLATFORM = "windows"` before `uv run pytest`).

## Building the executable

Build the standalone Windows executable:

```sh
uv run pyinstaller entry.py --name SMACC --onefile --noconsole \
  --icon src/smacc/assets/icon.ico \
  --add-data "src/smacc/assets/icon.png:smacc/assets" \
  --add-data "src/smacc/assets/default.smacc:smacc/assets" \
  --add-data "src/smacc/assets/cues:smacc/assets/cues" \
  --add-data "src/smacc/assets/biocals:smacc/assets/biocals" \
  --add-data "src/smacc/assets/surveys:smacc/assets/surveys"
```

`--icon` sets the executable's file icon; `--add-data` bundles the runtime
window/taskbar icon, which SMACC resolves via `sys._MEIPASS`. On Windows the
`--add-data` separator is `;` rather than `:` (i.e. `...png;smacc/assets`).

PyYAML (settings export/import) is pure Python and is picked up automatically by
PyInstaller; if a frozen build ever fails to import `yaml`, add
`--hidden-import yaml`.

The optional EEG Annotator component (#136) is a second frozen exe with its own
entry point — it carries the MNE/pyqtgraph/matplotlib stack the base exe deliberately
doesn't (requires `uv sync --extra dev --extra eeg`):

```sh
uv run pyinstaller entry_eeg.py --name SMACC-EEG --onefile --noconsole \
  --icon src/smacc/assets/icon.ico \
  --add-data "src/smacc/assets/icon.png:smacc/assets" \
  --collect-submodules mne --collect-data mne \
  --collect-submodules matplotlib.backends
```

The `--collect-*` flags matter: MNE uses `lazy_loader`, which imports
submodules by name at runtime and reads the package's `.pyi` stubs — both
invisible to PyInstaller's static analysis. Without them the exe builds
cleanly and dies on first MNE use. matplotlib is a real dependency too — the
figure export (`eeg/export.py`, #180) writes PDF/SVG via `savefig`, and MNE's IO
layer imports `mne.viz.ui_events` (→ matplotlib) at import time — so
`--collect-submodules matplotlib.backends` bundles its PDF/SVG backends, and
`--exclude-module matplotlib` would break both `read_raw_*` and the export.

Verify a built `SMACC-EEG.exe` with `--selftest` (the check is exit code 0):
it round-trips a synthetic recording through MNE, the display filters, and the
annotation sidecar. `--version` alone would not catch a broken MNE bundling —
MNE is imported lazily, so it only loads when a recording is actually touched.

The `blinkstick` driver (BlinkStick visual cues) and its Windows backend
`pywinusb` are pure Python and bundle the same way. PyInstaller may warn that
`usb.core` is missing — that is BlinkStick's non-Windows backend, which SMACC
never uses, so the warning is harmless. If a frozen build ever fails to import
the driver, add `--hidden-import pywinusb`.

Releases are built automatically: pushing a `v*` tag (e.g. `v0.0.11`) triggers the
[release workflow](https://github.com/remrama/smacc/blob/main/.github/workflows/release.yaml),
which checks the tag against `smacc.__version__`, builds `SMACC.exe` and
`SMACC-EEG.exe` (each stamped with version metadata from
`tools/make_versionfile.py`), wraps them in an Inno Setup installer
(`tools/smacc.iss` → `SMACC-Setup.exe`, with the EEG exe as the optional
component), smoke-tests the exes (`--version`, and `--selftest` for the EEG
one) and both installer component configurations, and attaches the three
artifacts to the GitHub Release. The installer's asset name is a stable
contract — the docs' download button links
`releases/latest/download/SMACC-Setup.exe` — so don't rename it. The installer's
`[Registry]` section must mirror `winassoc.association_entries()` exactly (so an
installed build sees the association as already registered);
`tests/test_winassoc.py` cross-checks them.

## Building the docs

The documentation site is built with [MkDocs](https://www.mkdocs.org/) +
[Material](https://squidfunk.github.io/mkdocs-material/) and versioned with
[mike](https://github.com/jimporter/mike). All pages are plain Markdown under
`docs/`.

```sh
uv run --extra docs mkdocs serve          # live-reload preview at http://localhost:8000
uv run --extra docs mkdocs build --strict # the exact build the PR CI runs
uv run --extra docs mike serve            # preview the versioned site
```

The [docs workflow](https://github.com/remrama/smacc/blob/main/.github/workflows/docs.yaml)
runs `mkdocs build --strict` on every pull request, deploys a `dev` version on
pushes to `main`, and publishes a numbered version (updating the `latest` alias)
on each `v*` release tag.

## Project notes

- `src/` layout: the package lives in `src/smacc/`.
- The single source of truth for the version is `__version__` in
    `src/smacc/__init__.py`; `config.py` and the packaging metadata both read from
    it.
- The build/runtime Python is pinned to **3.13** in `.python-version`. The
    minimum OS is **Windows 10**, set by Qt 6 (PyQt6) — Qt 5 was the last line that
    still ran on Windows 8.1. Keep the pin unless you intend to move the Python floor.
- SMACC is distributed only as a frozen `SMACC.exe` (no PyPI), so CI tests what
    ships rather than a version range: the `test` job in `ci.yaml` runs on the same
    `windows-2022` + Python 3.13 + locked dependencies as the release build
    (`release.yaml`), across `windows-2022` and `windows-latest` rather than a
    Python-version matrix.
