---
name: quarto
description: Reference for SMACC's documentation toolchain — the Quarto Book that renders both the HTML site and the single-file PDF manual from docs/, the Markdown conventions (callouts, screenshot sizing, download buttons), the Typst PDF engine, the GitHub Pages deploy, and the link/completeness checks. Use when touching docs/, docs/_quarto.yml, the docs or release CI workflows, scripts/check_links.py / scripts/check_manual.py, or anything about building/publishing the docs or the PDF manual.
---

# SMACC docs: the Quarto toolchain

SMACC's docs moved from MkDocs (Material) + `mkdocs-exporter` to **Quarto** (#259).
One Quarto **Book** renders both the HTML site (→ GitHub Pages) and a single-file
**Typst PDF** manual from the same Markdown under `docs/` — no plugin stack, no
system libraries. Quarto is a standalone binary (bundles Typst + Pandoc); it is
**not** a Python package, so it is not in `uv sync`.

## Commands

```sh
quarto preview docs    # live-reload HTML while writing
quarto render docs     # build HTML site + PDF into docs/_book/
quarto render docs --to typst   # PDF only (the release manual-pdf job)

uv run python scripts/check_links.py docs/_book                                 # internal links + anchors
uv run --extra docs python scripts/check_manual.py docs/_book/smacc-manual.pdf  # PDF completeness
```

The project root is `docs/` (so Quarto only scans the docs tree, never README.md /
AGENTS.md / the rest of the repo). Output and cache (`docs/_book`, `docs/.quarto`)
are gitignored.

## `docs/_quarto.yml` — decisions that must not regress

- **`from: markdown+gfm_auto_identifiers`** (top level) makes heading slugs match
  GitHub/Material's slugifier, so the existing cross-page `#anchor` links keep
  resolving. Plain Pandoc keeps periods (e.g. `pulsed-vs.-set-and-hold`) and would
  break them. (Note: Pandoc's `-implicit_figures` does **not** stop Quarto turning a
  lone image into a captioned figure — Quarto has its own filter; see screenshots.)
- **`book:` is the project type** (not `website`) — it's the one that yields a single
  combined PDF.
- **`author:` is required.** The default Typst book template (`orange-book`) crashes
  (`expected content, found array`) if `author` is unset. Keep it a single string.
- **Theme** `light: pulse`, `dark: darkly` (Bootswatch, built-in). Plain baseline;
  heavy/brand theming is deferred (see below).
- **`number-sections: false`** — books number chapters by default; SMACC's docs are
  unnumbered.
- **`output-file: smacc-manual`** — the PDF lands at `docs/_book/smacc-manual.pdf`
  and, published, at `…/smacc/smacc-manual.pdf`.

## Markdown conventions

- **Admonitions are callouts:** `::: {.callout-note title="…"}` … `:::`
  (Material `!!! note "…"` is gone). Types in use: note, tip, warning. There is no
  `info` callout — Material `info` blocks became `note`.
- **Screenshots:** `![](path){width=N% fig-alt="description"}` — empty caption +
  `fig-alt` is what keeps Quarto from rendering the alt text as a *visible numbered
  caption* (matching the old Material site, which showed none). Widths: narrow `45%`,
  medium `75%`, wide `100%` (the old `.shot` / `--narrow` / `--wide` intent). Avoid a
  literal `"` inside `fig-alt` — use single quotes there (a `\"` escape gets stripped
  by mdformat, which silently breaks the attribute).
- **Download buttons:** `[text](url){.btn .btn-primary role="button"}` (or
  `.btn-secondary`) — Bootstrap, styled by the theme; degrade to plain links in PDF.

## CI

- **`.github/workflows/docs.yml`** — two jobs: `build` (quarto-actions/setup, render,
  run both checks, upload-pages-artifact) and `deploy` (actions/deploy-pages, push to
  `main` only). Uses the official GitHub Actions Pages deployment — **no `gh-pages`
  branch**; the repo's Pages source must be set to "GitHub Actions" (Settings → Pages).
- **`.github/workflows/release.yml`** `manual-pdf` job — on a tag, render `--to typst`,
  check, and attach `docs/_book/smacc-manual.pdf` (unversioned name; the release is the
  version) to the release.
- **`scripts/check_links.py`** replaces `mkdocs build --strict`'s link validation:
  it parses the rendered `_book` HTML and fails on any dead internal link or `#anchor`
  (the main migration footgun). **`scripts/check_manual.py`** (renderer-agnostic,
  carried over unchanged) fails if the PDF is short or missing late-section content.

## Formatting

`mdformat` (CI + pre-commit) still runs with **`mdformat-mkdocs`** — kept not for
Material syntax (gone) but because it preserves the repo's four-space list-nesting
style across *all* markdown; dropping it would reflow every list (incl. README.md /
AGENTS.md). It leaves Quarto `:::` callouts and `{…}` attributes intact. `docs/_book`
and `docs/.quarto` are excluded in `.mdformat.toml`.

## Deferred (separate follow-up PR)

Heavy visual customization is **out of scope** for the migration: a brand SCSS theme,
a custom **Typst** cover and running header (the old `pdf/cover.html` +
`pdf/print.css` + `pdf/hooks.py`, which injected the cover/footer version), and table
styling. The brand color is **`#3c48aa`** (matches the icon background); the logo is
`docs/assets/icon.png`. Because the PDF engine is Typst, that custom cover/template
work will be authored in **Typst**, not CSS/Paged.js or LaTeX.
