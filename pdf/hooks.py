"""Build-time hooks for the single-file PDF manual.

Wired in via ``hooks:`` in mkdocs-pdf.yml only, so an ordinary website build
(mkdocs.yml) is untouched. Responsibilities:

* fill the cover's version token (``@@SMACC_VERSION@@`` in pdf/cover.html);
* add the version to the running footer, drop the unused favicon link, and remove
  Material's runtime bundle (which otherwise fetches versions.json — 404 under
  file:// — for the version switcher). These are applied to ``page.html``, the copy
  mkdocs-exporter renders to PDF, so the published website keeps its own scripts;
* delete the per-page PDFs mkdocs-exporter writes alongside the aggregated manual,
  leaving only pdf/smacc-manual.pdf in the published site.
"""

import glob
import os
import re

from mkdocs.plugins import event_priority

from smacc import __version__

_VERSION_TOKEN = "@@SMACC_VERSION@@"
_MANUAL = "pdf/smacc-manual.pdf"

# The favicon link isn't used in the PDF and only adds a render-log request.
_FAVICON_RE = re.compile(r'<link\b[^>]*\brel="(?:shortcut )?icon"[^>]*>', re.IGNORECASE)
# Material's runtime bundle is unneeded for the static print render (Paged.js and the
# exporter's own scripts drive it); dropping it stops the version switcher's
# versions.json fetch, which 404s under file:// rendering.
_BUNDLE_RE = re.compile(
    r'<script\b[^>]*\bsrc="[^"]*bundle[^"]*"[^>]*>\s*</script>', re.IGNORECASE
)

# A Paged.js running footer carrying the version (bottom-right of every page). The
# cover clears all footers via `@page :first` in pdf/print.css.
_FOOTER_STYLE = (
    "<style>@page { @bottom-right { "
    f"content: 'v{__version__}'; font-size: 7pt; color: #888; "
    "} }</style>"
)


def on_page_content(html: str, page, config, files):
    """Fill the cover's version token in the rendered page content."""
    if _VERSION_TOKEN in html:
        return html.replace(_VERSION_TOKEN, __version__)
    return html


# Priority 95: after mkdocs-exporter captures page.html (100) and before it renders
# the PDF (90), so these edits reach the PDF but not the returned website HTML.
@event_priority(95)
def on_post_page(output: str, page, config):
    """Add the footer, drop the favicon, strip the runtime bundle — PDF copy only."""
    html = getattr(page, "html", None)
    if html is not None:
        html = _FAVICON_RE.sub("", html)
        html = _BUNDLE_RE.sub("", html)
        html = html.replace("</head>", _FOOTER_STYLE + "</head>", 1)
        page.html = html
    return output


# Priority -110: after mkdocs-exporter has written the per-page PDFs (-90) and the
# aggregated manual (-95), so only the strays are removed.
@event_priority(-110)
def on_post_build(config):
    """Remove the per-page PDFs, keeping only the aggregated manual."""
    site_dir = config["site_dir"]
    keep = os.path.normpath(os.path.join(site_dir, *_MANUAL.split("/")))
    for path in glob.glob(os.path.join(site_dir, "**", "*.pdf"), recursive=True):
        if os.path.normpath(path) != keep:
            os.remove(path)
