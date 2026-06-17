"""Internal-link checker for the rendered Quarto site.

The MkDocs build validated cross-page links and heading anchors with
``mkdocs build --strict``; Quarto has no equivalent, and a stale ``page.md#anchor``
fails silently as a dead fragment in the rendered site. Heading slugs also differ
between renderers (Material vs Pandoc), which is the main footgun of the migration.
This script closes that gap for the HTML site: it parses the rendered ``_book`` HTML
and verifies that every internal link resolves to a real page and, when it carries a
``#fragment``, to a real ``id`` on that page. Run in CI after ``quarto render``:

    uv run python scripts/check_links.py docs/_book

Exits non-zero (listing every broken link) if anything dangles. External links
(``http(s)://``, ``mailto:`` …) are not checked — only the internal cross-links the
migration can break.
"""

from __future__ import annotations

import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urldefrag


class _Collector(HTMLParser):
    """Collect every element ``id`` and every anchor ``href`` on a page."""

    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if a.get("id"):
            self.ids.add(a["id"])
        # Quarto also targets footnote/section anchors by name= in a few spots.
        if tag == "a" and a.get("name"):
            self.ids.add(a["name"])
        if tag == "a" and a.get("href"):
            self.hrefs.append(a["href"])


def _is_external(href: str) -> bool:
    return href.startswith(("http://", "https://", "mailto:", "tel:", "data:"))


def main(book: str) -> int:
    root = Path(book).resolve()
    if not root.is_dir():
        print(f"FAIL: {book} is not a directory (run `quarto render docs` first)")
        return 1

    pages = {p.resolve(): _parse(p) for p in root.rglob("*.html")}
    broken: list[str] = []

    for path, page in pages.items():
        rel = path.relative_to(root)
        for href in page.hrefs:
            target, frag = urldefrag(href.strip())
            if _is_external(href) or href.startswith("#") and not href[1:]:
                continue
            if not target:  # same-page "#fragment"
                dest = path
            else:
                dest = (path.parent / unquote(target)).resolve()
                if dest.is_dir():
                    dest = dest / "index.html"
            # Non-HTML resources (PDF, images): just confirm the file exists.
            if dest.suffix.lower() != ".html":
                if not dest.exists():
                    broken.append(f"{rel}: missing resource -> {href}")
                continue
            if dest not in pages:
                broken.append(f"{rel}: link to missing page -> {href}")
                continue
            if frag and frag not in pages[dest].ids:
                broken.append(f"{rel}: dead anchor -> {href}")

    if broken:
        print(f"FAIL: {len(broken)} broken internal link(s) in {book}")
        for b in sorted(broken):
            print(f"  - {b}")
        return 1
    print(f"OK: {book} ({len(pages)} pages, all internal links resolve)")
    return 0


def _parse(path: Path) -> _Collector:
    c = _Collector()
    c.feed(path.read_text(encoding="utf-8"))
    return c


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "docs/_book"))
