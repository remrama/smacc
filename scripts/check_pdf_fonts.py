"""IBM Plex enforcement for the single-file PDF manual.

orange-book's ``book()`` sets text *size* but never a font *family* and takes no
``mainfont``/``codefont`` argument, so unless ``docs/typst-preamble.typ`` sets the base
font explicitly, the body, cover, and code silently fall back to Typst's defaults
(Libertinus Serif / DejaVu Sans Mono). That fallback raises no ``unknown font family``
warning, so it shipped twice unnoticed — the condensed tables (#268), then the whole
body (#283) — which the existing warning-grep guard could not catch.

This guard reads the font behind every text span in the rendered PDF and fails if any
*letter or digit* is drawn in a non-IBM-Plex font: Plex covers every ASCII alphanumeric,
so an alphanumeric in another font is the signature of the fallback bug. Symbol glyphs
Plex genuinely lacks (the ▲▼ / ●○ / ✕ UI markers, callout icons, …) are allowed to fall
back, which also keeps the check platform-independent — the bundled Plex faces render
identically on every runner, and only those symbol fallbacks vary by OS (e.g. Segoe UI
Emoji locally vs DejaVu on Linux), but they never carry alphanumeric text. Run in CI
after the PDF build:

    uv run --extra docs python scripts/check_pdf_fonts.py docs/_book/SMACC-manual.pdf

Exits non-zero (listing the offending fonts and a sample) if any text is not Plex.
"""

import re
import sys

from pypdf import PdfReader

# A subset-embedded font carries a six-letter tag like ``ABCDEF+``; strip it to the
# family. Every bundled face — Sans, Mono, Sans Condensed, all weights/styles — shares
# the ``IBMPlex`` stem, so a single substring test covers them all.
_SUBSET = re.compile(r"^/[A-Z]{6}\+")
_PLEX = "IBMPlex"


def _offenders(reader: PdfReader) -> dict[str, tuple[int, str]]:
    """Map each non-Plex font drawing alphanumerics to its first (page, sample)."""
    hits: dict[str, tuple[int, str]] = {}
    for number, page in enumerate(reader.pages, start=1):

        def visit(text, cm, tm, font, size, _n=number):
            if not font:
                return
            family = _SUBSET.sub("", str(font.get("/BaseFont", "")))
            if _PLEX in family:
                return
            # Plex has every ASCII letter/digit, so one drawn in another font is the
            # fallback bug; symbol-only spans (shapes, icons, emoji) are legitimate.
            if any(c.isascii() and c.isalnum() for c in text):
                hits.setdefault(family, (_n, text.strip()[:50]))

        page.extract_text(visitor_text=visit)
    return hits


def main(path: str) -> int:
    hits = _offenders(PdfReader(path))
    if hits:
        print(
            f"FAIL: {path} draws text in non-IBM-Plex fonts (mainfont/codefont not applied?)"
        )
        for family, (number, sample) in sorted(hits.items()):
            print(f"  - {family}  p.{number}  «{sample}»")
        print(
            "  (set the base font in docs/typst-preamble.typ; orange-book ignores mainfont)"
        )
        return 1
    print(f"OK: {path} (all alphanumeric text is IBM Plex; symbol fallbacks allowed)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "docs/_book/SMACC-manual.pdf"))
