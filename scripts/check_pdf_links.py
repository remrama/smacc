"""Internal-link checker for the single-file PDF manual.

Quarto/Typst emits a cross-chapter link that lacks a ``#fragment`` — e.g.
``[Installation](installation.md)`` — as an *external* ``/URI`` annotation pointing
at the bare ``installation.md`` filename, which is nothing in a single combined PDF,
so the link leads nowhere (#262). Links that carry an explicit anchor
(``installation.md#installation``) are emitted as internal ``/GoTo`` destinations and
resolve. ``scripts/check_links.py`` only sees the HTML site, so it never catches this.

This guard closes that gap for the PDF: it walks every ``/Link`` annotation and fails
on any ``/URI`` that points at a relative ``.md`` (or ``.html``) document — the
signature of an unresolved intra-book link. Genuine external links (``http(s)://`` …)
are left alone. Run in CI after the PDF build:

    uv run --extra docs python scripts/check_pdf_links.py docs/_book/SMACC-manual.pdf

Exits non-zero (listing every dead link) if anything dangles.
"""

import sys
from collections.abc import Iterator

from pypdf import PdfReader
from pypdf.generic import ArrayObject, DictionaryObject

# An unresolved intra-book link points at a bare local document file. A real external
# link is absolute (has a scheme); we only flag relative targets ending in these.
_DEAD_SUFFIXES = (".md", ".html")
_EXTERNAL_SCHEMES = ("http://", "https://", "mailto:", "tel:", "data:", "ftp://")


def _uris(reader: PdfReader) -> Iterator[tuple[int, str]]:
    """Yield (page number, /URI) for every link annotation that carries one."""
    for number, page in enumerate(reader.pages, start=1):
        if "/Annots" not in page:
            continue
        annots = page["/Annots"].get_object()
        if not isinstance(annots, ArrayObject):
            continue
        for ref in annots:
            annot = ref.get_object()
            if not isinstance(annot, DictionaryObject):
                continue
            if annot.get("/Subtype") != "/Link" or "/A" not in annot:
                continue
            action = annot["/A"].get_object()
            if not isinstance(action, DictionaryObject):
                continue
            uri = action.get("/URI")
            if uri:
                yield number, str(uri)


def _is_dead(uri: str) -> bool:
    if uri.startswith(_EXTERNAL_SCHEMES):
        return False
    target = uri.split("#", 1)[0].lower()
    return target.endswith(_DEAD_SUFFIXES)


def main(path: str) -> int:
    reader = PdfReader(path)
    links = list(_uris(reader))
    dead = sorted({(number, uri) for number, uri in links if _is_dead(uri)})

    if dead:
        print(f"FAIL: {len(dead)} dead intra-book link(s) in {path}")
        for number, uri in dead:
            print(f"  - p.{number}: {uri}")
        print("  (cross-chapter links need an explicit #anchor; see #262)")
        return 1
    print(f"OK: {path} ({len(links)} link annotations, no dead intra-book links)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "docs/_book/SMACC-manual.pdf"))
