"""Publication-figure export for the EEG Annotator (#180).

Renders a :class:`~smacc.eeg.snapshot.Snapshot` to PNG / PDF / SVG with
matplotlib's headless backends — the engine MNE itself uses for static figures,
and the only one of the available libraries that does PDF and reliable vector
text (pyqtgraph has no PDF exporter and its SVG exporter mishandles the view's
stacked transforms). matplotlib already ships in the frozen build as an MNE
dependency, so this adds no packaging weight.

The figure is built straight on a :class:`matplotlib.figure.Figure` with an
explicit Agg canvas — never via ``pyplot`` — so there is no global backend state
to clash with MNE in the same process, and ``savefig`` selects the PDF/SVG
backend from the format. Dense traces are flattened into one rasterized layer at
the chosen DPI while axes, ticks, marks and labels stay crisp vector (the
file-size fix for thousands of samples in a vector file).

Pure numpy + matplotlib, no Qt and no MNE — directly unit-testable headless,
mirroring :mod:`smacc.eeg.dsp` / :mod:`smacc.eeg.profiles`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import matplotlib
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from .snapshot import Snapshot

# The three output formats; PNG raster (DPI), PDF/SVG vector.
FORMATS = ("png", "pdf", "svg")

# Publication palette: black traces, grey epoch grid, firebrick point marks (the
# screen's accent), near-black span brackets and labels. Light, print-friendly.
_TRACE_COLOR = "black"
_EPOCH_COLOR = "0.6"
_EPOCH_LABEL_COLOR = "0.45"
_POINT_COLOR = "firebrick"
_SPAN_COLOR = "0.1"
_SHADE_COLOR = "steelblue"


@dataclass(frozen=True)
class ExportOptions:
    """What to keep, strip, relabel, and how to write the file.

    The figure is faithful to the on-screen view by construction; these options
    only *remove* chrome (grid/shading), *relabel* marks, set line weight, and
    pick the output format/resolution.
    """

    # Content (requirements a/b/c)
    show_epoch_grid: bool = True  # honored only if the snapshot carries epochs
    show_mark_shading: bool = False  # span wash; off = clean publication default
    show_mark_labels: bool = True  # caret/bracket labels for marks
    show_channel_labels: bool = True  # left-axis channel-name ticks
    line_width_pt: float = 0.7  # all traces; publication-thin
    # Output (requirement d)
    fmt: str = "png"  # "png" | "pdf" | "svg"
    dpi: int = 300  # PNG pixels and rasterized-trace resolution in PDF/SVG
    width_in: float = 10.0
    height_per_channel_in: float = 0.5  # total height auto from channel count (capped)
    rasterize_traces: bool = True  # flatten traces to one image; False = full vector
    svg_text_as_text: bool = (
        True  # editable <text> (svg.fonttype="none") vs outlined paths
    )
    title: str = ""  # optional caption


def render(snapshot: Snapshot, options: ExportOptions, path: str | Path) -> None:
    """Render ``snapshot`` to ``path`` in ``options.fmt``.

    Raises:
        ValueError: for an unknown ``options.fmt``.
        OSError: if the file cannot be written.
    """
    if options.fmt not in FORMATS:
        raise ValueError(
            f"Unknown export format {options.fmt!r}; expected one of {FORMATS}"
        )
    figure = build_figure(snapshot, options)
    # rc_context so these never leak into the shared process (MNE also uses
    # matplotlib). svg.fonttype "none" keeps text as editable <text>; a fixed
    # hashsalt makes SVG ids deterministic; pdf.fonttype 42 embeds TrueType.
    overrides = {
        "svg.fonttype": "none" if options.svg_text_as_text else "path",
        "svg.hashsalt": "smacc-eeg",
        "pdf.fonttype": 42,
    }
    # Drop the per-format timestamp so re-renders are reproducible (no git churn).
    metadata = {"CreationDate": None} if options.fmt == "pdf" else {"Date": None}
    with matplotlib.rc_context(overrides):
        figure.savefig(path, format=options.fmt, dpi=options.dpi, metadata=metadata)


def build_figure(snapshot: Snapshot, options: ExportOptions) -> Figure:
    """Build (but do not write) the figure — the unit-test seam for artists."""
    lanes = [t.lane for t in snapshot.traces]
    height = min(14.0, max(1, len(lanes)) * options.height_per_channel_in + 1.0)
    figure = Figure(figsize=(options.width_in, height))
    FigureCanvasAgg(figure)  # bind a canvas without pyplot's global state
    axes = figure.add_subplot(111)
    axes.set_xlim(0.0, snapshot.window_seconds)
    top = 0.6
    axes.set_ylim(-(max(lanes, default=0) + 0.6), top)

    # Rasterized layer (zorder < 0): span shading + every trace flatten to one
    # image at `dpi`. Rasterizing per-line instead would embed one bitmap per
    # artist and bloat the file; this keeps everything above zorder 0 vector.
    axes.set_rasterization_zorder(0 if options.rasterize_traces else None)
    if options.show_mark_shading:
        for mark in snapshot.marks:
            if mark.duration > 0:
                axes.axvspan(
                    mark.onset,
                    mark.onset + mark.duration,
                    color=_SHADE_COLOR,
                    alpha=0.18,
                    lw=0,
                    zorder=-20,
                )
    for trace in snapshot.traces:
        axes.plot(
            snapshot.times,
            -trace.lane + trace.values,
            color=_TRACE_COLOR,
            lw=options.line_width_pt,
            antialiased=True,
            zorder=-10,
        )

    # Vector layer (zorder >= 0): grid, marks, labels stay crisp at any zoom.
    if options.show_epoch_grid:
        for epoch in snapshot.epochs:
            axes.axvline(epoch.x, color=_EPOCH_COLOR, lw=0.6, ls=(0, (4, 4)), zorder=1)
            axes.text(
                epoch.x,
                top - 0.04,
                epoch.number,
                color=_EPOCH_LABEL_COLOR,
                fontsize=6,
                ha="left",
                va="top",
                zorder=1,
            )
    for mark in snapshot.marks:
        if mark.duration == 0:
            axes.axvline(mark.onset, color=_POINT_COLOR, lw=0.8, zorder=2)
        else:
            axes.plot(
                [mark.onset, mark.onset + mark.duration],
                [top - 0.14, top - 0.14],
                color=_SPAN_COLOR,
                lw=0.9,
                zorder=2,
            )
        if options.show_mark_labels and mark.label:
            axes.text(
                mark.onset + mark.duration / 2,
                top - 0.02,
                mark.label,
                color=_SPAN_COLOR,
                fontsize=7,
                ha="center",
                va="bottom",
                zorder=2,
            )

    if options.show_channel_labels:
        axes.set_yticks([-t.lane for t in snapshot.traces])
        axes.set_yticklabels([t.name for t in snapshot.traces])
        axes.tick_params(left=False)  # names only, no tick marks (as on screen)
    else:
        axes.set_yticks([])
    if snapshot.time_ticks:
        axes.set_xticks([x for x, _ in snapshot.time_ticks])
        axes.set_xticklabels([label for _, label in snapshot.time_ticks])
    axes.set_xlabel(snapshot.time_axis_label)
    for side in ("top", "right", "left"):
        axes.spines[side].set_visible(False)
    title = options.title or snapshot.title
    if title:
        axes.set_title(title)
    figure.tight_layout()  # reproducible: keeps figsize, unlike bbox_inches="tight"
    return figure
