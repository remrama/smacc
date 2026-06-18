# Contributing

::: {.callout-note title="For both human and AI contributors"}

This page is the canonical development guide for SMACC. It is written for both
human contributors and AI coding assistants — AI agents are pointed here from
[`AGENTS.md`](https://github.com/remrama/smacc/blob/main/AGENTS.md), so the
instructions live here once rather than being duplicated across files.

:::

::: {.callout-note title="Requesting a change? Open a GitHub issue"}

Human contributors should open a
[GitHub issue](https://github.com/remrama/smacc/issues) for new feature
requests or bug reports before starting work, so changes can be discussed
first.

:::

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
uv run --extra dev pytest --cov=smacc --cov-report=term-missing   # CI also adds --cov-report=xml
```

To actually watch a test render, override the platform for that run (Windows:
`$env:QT_QPA_PLATFORM = "windows"` before `uv run pytest`).

## Building the executable

Build the Windows app — one `--onedir` bundle that includes the EEG Annotator:

```sh
uv run pyinstaller entry.py --name SMACC --onedir --noconsole \
  --icon src/smacc/assets/icon.ico \
  --add-data "src/smacc/assets/icon.png:smacc/assets" \
  --add-data "src/smacc/assets/default.smacc:smacc/assets" \
  --add-data "src/smacc/assets/cues:smacc/assets/cues" \
  --add-data "src/smacc/assets/biocals:smacc/assets/biocals" \
  --add-data "src/smacc/assets/surveys:smacc/assets/surveys" \
  --collect-submodules mne --collect-data mne \
  --collect-submodules matplotlib.backends
```

This produces `dist/SMACC/SMACC.exe` (a folder, not a single file). `--onedir`
rather than `--onefile` is deliberate: a session launch imports lazily off the
install folder and never loads the heavy MNE stack, with no per-launch temp
extraction (and so no ~120 MB blob for antivirus to rescan each run). On Windows
the `--add-data` separator is `;` rather than `:` (i.e. `...png;smacc/assets`).
`--icon` sets the executable's file icon; `--add-data` bundles the runtime
window/taskbar icon, which SMACC resolves via `sys._MEIPASS`.

The EEG Annotator (#136) is a mode of this same binary — `SMACC.exe --eeg`,
re-exec'd as its own process (see `smacc.eeg.launch`) — so it is built in, not a
second exe. The `--collect-*` flags are what make its MNE stack survive freezing:
MNE uses `lazy_loader`, which imports submodules by name at runtime and reads the
package's `.pyi` stubs — both invisible to PyInstaller's static analysis — so
without them the build succeeds and dies on first MNE use. matplotlib is a real
dependency too: figure export (`eeg/export.py`, #180) writes PDF/SVG via
`savefig`, and MNE's IO layer imports `mne.viz.ui_events` (→ matplotlib) at import
time — so `--collect-submodules matplotlib.backends` bundles its PDF/SVG
backends, and `--exclude-module matplotlib` would break both `read_raw_*` and the
export.

Verify the built app with `SMACC.exe --eeg --selftest` (the check is exit
code 0): it round-trips a synthetic recording through MNE, the display filters,
and the annotation sidecar. A plain `--version` would not catch broken MNE
bundling — MNE is imported lazily, so it only loads when a recording is touched.

PyYAML (settings export/import) is pure Python and is picked up automatically by
PyInstaller; if a frozen build ever fails to import `yaml`, add
`--hidden-import yaml`.

The `blinkstick` driver (BlinkStick visual cues) and its Windows backend
`pywinusb` are pure Python and bundle the same way. PyInstaller may warn that
`usb.core` is missing — that is BlinkStick's non-Windows backend, which SMACC
never uses, so the warning is harmless. If a frozen build ever fails to import
the driver, add `--hidden-import pywinusb`.

Releases are built automatically: pushing a `v*` tag (e.g. `v0.1.0`) triggers the
[release workflow](https://github.com/remrama/smacc/blob/main/.github/workflows/release.yml),
which checks the tag against `smacc.__version__`, builds the onedir
`SMACC.exe` (stamped with version metadata from `tools/make_versionfile.py`),
wraps it in an Inno Setup installer (`tools/smacc.iss` → `SMACC-Setup.exe`),
smoke-tests the app (`--version` and `--eeg --selftest`) and the installer, and
attaches `SMACC-Setup.exe` to the GitHub Release. The installer's asset name is a
stable contract — the docs' download button links
`releases/latest/download/SMACC-Setup.exe` — so don't rename it. The installer's
`[Registry]` section must mirror `winassoc.association_entries()` exactly (so an
installed build sees the association as already registered);
`tests/test_winassoc.py` cross-checks them.

## Building the docs

The documentation site and the single-file PDF manual are both built with
[Quarto](https://quarto.org) — a standalone binary that renders the HTML site and a
native Typst PDF from the same Markdown sources under `docs/`, with no plugin stack
and no system libraries. Install Quarto once (it bundles the Typst PDF engine); it
is not a Python package, so it is not part of `uv sync`.

```sh
quarto preview docs   # live-reload HTML preview while writing
quarto render docs    # build the HTML site and the PDF into docs/_book/
```

The project config is `docs/_quarto.yml` — a Quarto *book*, the project type that
yields one combined PDF. Pages are plain Markdown; admonitions are
[callouts](https://quarto.org/docs/authoring/callouts.html) (`::: {.callout-note}`),
and each screenshot carries a `width=` attribute with its description in `fig-alt`.
Heading slugs use `gfm_auto_identifiers` so the cross-page `#anchor` links resolve
the same way GitHub renders them.

The [docs workflow](https://github.com/remrama/smacc/blob/main/.github/workflows/docs.yml)
renders and checks the docs on every pull request and push, and publishes the live
site to GitHub Pages only on a **stable release tag** (`vX.Y.Z`) — so the site always
reflects the current stable version, never a dev or pre-release build. The PDF manual
is attached to *every* release (stable, pre-release, and the rolling `dev` build) by
the [release workflow](https://github.com/remrama/smacc/blob/main/.github/workflows/release.yml),
and the live site serves the current stable manual via the sidebar **Download PDF**
button.

Two checks run in CI after the render — run them locally before a docs PR. Together
they replace what `mkdocs build --strict` used to cover:

```sh
uv run python scripts/check_links.py docs/_book                                 # internal links + heading anchors
uv run --extra docs python scripts/check_manual.py docs/_book/SMACC-manual.pdf  # PDF completeness
```

`check_links.py` fails on any dead cross-page link or `#anchor` (heading slugs
differ between renderers — the main migration footgun). `check_manual.py` fails if
the manual is short or missing content from its later sections, guarding against a
renderer silently dropping pages (the bug behind #250).

## Versioning

SMACC follows [semantic versioning](https://semver.org/).

- **Pre-1.0, the app is not stable.** Settings files, marker codes, the UI, and
  behavior may change between releases, and there are no compatibility shims. Pin
  one version for the duration of a study.
- **Versions are `0.x.y` until 1.0.0.** A new `0.x.0` collects features and `0.x.y`
  is a smaller follow-up; no pre-1.0 bump is a stability promise.
- **`0.1.0` is the first published release** — the first with installers attached, a
  [release-notes](release-notes.md) entry, and a working in-app update check.
  Earlier `0.0.x` tags predate it and are not in the release notes.
- **1.0.0 is the first stable release.** From then on semantic versioning is binding
  (backward-compatible changes bump the minor/patch, breaking changes bump the
  major).

There are three kinds of build:

- **Stable — `vX.Y.Z`** (no suffix): a full GitHub release, badged *Latest*. The
  homepage download button, `/releases/latest`, and the in-app update check all
  resolve to it. `__version__` equals `X.Y.Z`.
- **Pre-release — `vX.Y.Z-rc.N`** (also `-alpha.N`/`-beta.N`): a tagged candidate for
  the upcoming `X.Y.Z`. Any tag with a hyphen is marked *Pre-release* on GitHub, so
  `/releases/latest` and the update check skip it. Allowed at any point, including
  the `0.x` line. Set `__version__` to the suffixed string and tag to match.
- **Development build — the `dev` tag**: a single fixed, *moving* tag (not a version
  number), rebuilt and republished on every code merge to `main` and marked
  *Pre-release*. It carries the portable `SMACC-dev.zip` (see
  [Installation](installation.md#development-build-experimental)) and is identified at
  runtime by the running version plus the commit it was built from, e.g.
  `v0.1.2 (dev build a1b2c3d)`. The word **dev** is reserved for this channel and the
  matching **dev** docs site; version pre-releases use `-rc`/`-alpha`/`-beta`, never a
  literal `-dev` suffix.

Cutting a release: bump `__version__` in `src/smacc/__init__.py` and push a matching
`vX.Y.Z` tag (use `vX.Y.Z-rc.N` for a candidate). CI checks the tag equals
`__version__`, builds and smoke-tests the installer, attaches it to the GitHub Release,
and publishes the docs. Right after a stable release, bump `__version__` on `main` to
the next target `X.Y.(Z+1)`, so development builds report the version they're heading
toward rather than the one just shipped.

## Project notes

- `src/` layout: the package lives in `src/smacc/`.
- The single source of truth for the version is `__version__` in
  `src/smacc/__init__.py`; `config.py` and the packaging metadata both read from
  it.
- The build/runtime Python is pinned to **3.13** in `.python-version`. The
  minimum OS is **Windows 10**, set by Qt 6 (PyQt6) — Qt 5 was the last line that
  still ran on Windows 8.1. Keep the pin unless you intend to move the Python floor.
- SMACC is distributed only as a frozen `SMACC.exe` (no PyPI), so CI tests what
  ships rather than a version range: the `test` job in `ci.yml` runs on the same
  `windows-2022` + Python 3.13 + locked dependencies as the release build
  (`release.yml`), across `windows-2022` and `windows-latest` rather than a
  Python-version matrix.
