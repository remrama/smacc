"""Tests for the publication figure export (#180) — pure, headless, no Qt.

Snapshots are built by hand from numpy arrays (no view, no MNE) and rendered
through matplotlib's Agg/PDF/SVG backends, mirroring the pure style of
``test_eeg_profiles``. ``build_figure`` is the introspection seam: assert on the
artists without writing a file.
"""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET

import numpy as np
import pytest

pytest.importorskip("matplotlib")  # ships with the eeg extra; skip a bare env

from smacc.eeg import export  # noqa: E402
from smacc.eeg.snapshot import (  # noqa: E402
    Snapshot,
    SnapshotEpoch,
    SnapshotMark,
    SnapshotTrace,
)

N = 600


def _snapshot(**overrides) -> Snapshot:
    times = np.linspace(0.0, 30.0, N)
    base = dict(
        times=times,
        window_seconds=30.0,
        traces=(
            SnapshotTrace("C3", "eeg", 0, 0.4 * np.sin(times), 100.0),
            SnapshotTrace("EMG", "emg", 1, 0.1 * np.cos(times), 200.0),
        ),
        marks=(
            SnapshotMark(12.0, 0.0, "LRLR"),
            SnapshotMark(20.0, 3.0, "spindle"),
        ),
        epochs=(SnapshotEpoch(10.0, "2"), SnapshotEpoch(20.0, "3")),
        time_ticks=tuple((float(x), f"{int(x)}") for x in (0, 10, 20, 30)),
        time_axis_label="time (s)",
    )
    base.update(overrides)
    return Snapshot(**base)


def _png_width(data: bytes) -> int:
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    return int.from_bytes(data[16:20], "big")  # IHDR width, big-endian


def _trace_lines(figure):
    return [ln for ln in figure.axes[0].lines if ln.get_zorder() == -10]


# ----- file output (requirement d) --------------------------------------------------


def test_png_pixel_width_tracks_dpi(tmp_path):
    widths = {}
    for dpi in (150, 300):
        path = tmp_path / f"f{dpi}.png"
        export.render(_snapshot(), export.ExportOptions(fmt="png", dpi=dpi), path)
        data = path.read_bytes()
        widths[dpi] = _png_width(data)
        assert widths[dpi] == round(10.0 * dpi)  # default width_in is 10
    assert widths[300] > widths[150]


def test_pdf_has_a_pdf_header(tmp_path):
    path = tmp_path / "f.pdf"
    export.render(_snapshot(), export.ExportOptions(fmt="pdf", dpi=150), path)
    assert path.read_bytes()[:5] == b"%PDF-"


def test_svg_keeps_clean_labels_as_editable_text(tmp_path):
    path = tmp_path / "f.svg"
    export.render(
        _snapshot(), export.ExportOptions(fmt="svg", svg_text_as_text=True), path
    )
    text = path.read_text(encoding="utf-8")
    # svg.fonttype="none" → labels are real <text>, searchable and editable.
    texts = [el.text for el in ET.fromstring(text).iter() if el.tag.endswith("}text")]
    flat = " ".join(t for t in texts if t)
    assert "spindle" in flat and "LRLR" in flat


def test_relabeling_replaces_the_technical_text(tmp_path):
    snap = _snapshot(marks=(SnapshotMark(12.0, 0.0, "two-way comms"),))
    path = tmp_path / "f.svg"
    export.render(snap, export.ExportOptions(fmt="svg"), path)
    text = path.read_text(encoding="utf-8")
    assert "two-way comms".replace(" ", "") in text.replace(" ", "")  # tspan-split safe
    assert "Cue started" not in text


def test_unknown_format_raises(tmp_path):
    with pytest.raises(ValueError, match="format"):
        export.render(
            _snapshot(), export.ExportOptions(fmt="tiff"), tmp_path / "f.tiff"
        )


def test_empty_snapshot_renders_without_crashing(tmp_path):
    snap = Snapshot(times=np.empty(0), window_seconds=30.0, traces=())
    path = tmp_path / "empty.png"
    export.render(snap, export.ExportOptions(fmt="png", dpi=100), path)
    assert path.stat().st_size > 0


# ----- content options (requirements a/b/c) -----------------------------------------


def test_one_trace_line_per_channel_at_the_set_weight():
    fig = export.build_figure(_snapshot(), export.ExportOptions(line_width_pt=1.4))
    lines = _trace_lines(fig)
    assert len(lines) == 2  # C3, EMG
    assert all(ln.get_linewidth() == 1.4 for ln in lines)


def test_epoch_grid_toggle_controls_the_numbers():
    on = export.build_figure(_snapshot(), export.ExportOptions(show_epoch_grid=True))
    off = export.build_figure(_snapshot(), export.ExportOptions(show_epoch_grid=False))
    assert "2" in [t.get_text() for t in on.axes[0].texts]
    assert "2" not in [t.get_text() for t in off.axes[0].texts]


def test_shading_toggle_controls_the_span_patch():
    on = export.build_figure(_snapshot(), export.ExportOptions(show_mark_shading=True))
    off = export.build_figure(
        _snapshot(), export.ExportOptions(show_mark_shading=False)
    )
    assert len(on.axes[0].patches) == 1  # one span mark in the sample
    assert len(off.axes[0].patches) == 0


def test_mark_labels_toggle():
    on = export.build_figure(_snapshot(), export.ExportOptions(show_mark_labels=True))
    off = export.build_figure(_snapshot(), export.ExportOptions(show_mark_labels=False))
    assert "spindle" in [t.get_text() for t in on.axes[0].texts]
    assert "spindle" not in [t.get_text() for t in off.axes[0].texts]


def test_point_mark_is_a_vertical_line_at_its_onset():
    fig = export.build_figure(_snapshot(), export.ExportOptions())
    verticals = [
        ln
        for ln in fig.axes[0].lines
        if ln.get_zorder() == 2 and ln.get_xdata()[0] == ln.get_xdata()[-1]
    ]
    assert any(v.get_xdata()[0] == 12.0 for v in verticals)  # the point mark at 12 s


def test_channel_labels_toggle():
    on = export.build_figure(
        _snapshot(), export.ExportOptions(show_channel_labels=True)
    )
    off = export.build_figure(
        _snapshot(), export.ExportOptions(show_channel_labels=False)
    )
    assert [t.get_text() for t in on.axes[0].get_yticklabels()] == ["C3", "EMG"]
    assert off.axes[0].get_yticks().tolist() == []


# ----- vector trace handling --------------------------------------------------------


def test_rasterized_traces_embed_one_image_not_many_paths():
    raster = _render_svg(export.ExportOptions(fmt="svg", rasterize_traces=True))
    vector = _render_svg(export.ExportOptions(fmt="svg", rasterize_traces=False))
    assert "<image" in raster  # the dense trace layer flattens to one bitmap
    assert "<image" not in vector


def test_svg_is_reproducible(tmp_path):
    # A fixed hashsalt + suppressed date → byte-identical re-render (no git churn).
    first = _render_svg(export.ExportOptions(fmt="svg"))
    second = _render_svg(export.ExportOptions(fmt="svg"))
    assert first == second


def _render_svg(options) -> str:
    buffer = io.BytesIO()
    export.render(_snapshot(), options, buffer)
    return buffer.getvalue().decode("utf-8")
