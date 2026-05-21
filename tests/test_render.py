"""Tests for `kcd render` PNG graceful degradation (Round-4 field report B3-B).

PNG output is rasterized by the bundled `resvg_py`. If rasterization ever
fails on a specific SVG, the `--format png` path must degrade to emitting the
SVG (which always renders) rather than failing the command. The adapters are
monkeypatched so no real kicad-cli is needed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kcd.adapters import kicad_cli, kipy_pcb
from kcd.commands.render import (
    _composite_layers,
    _crop_svg_region,
    _region_dpi,
    _region_viewbox,
    _resolve_region,
    render_app,
)
from kcd.core.output import CommandError


@pytest.fixture
def proj_dir(tmp_path: Path) -> Path:
    (tmp_path / "demo.kicad_pro").write_text("{}")
    (tmp_path / "demo.kicad_sch").write_text("(kicad_sch)")
    (tmp_path / "demo.kicad_pcb").write_text("(kicad_pcb)")
    return tmp_path


def _boom(*a, **k):
    raise kicad_cli.CliError(["png-rasterize"], 1, "", "resvg could not rasterize")


def test_render_pcb_png_degrades_to_svg(proj_dir: Path, monkeypatch) -> None:
    monkeypatch.setattr(kicad_cli, "_rasterize_svg", _boom)

    def fake_pcb_svg(cli, pcb, out, layers=None, mirror=False):
        Path(out).write_text("<svg/>")
        return out

    monkeypatch.setattr(kicad_cli, "export_pcb_svg", fake_pcb_svg)
    r = CliRunner().invoke(
        render_app,
        ["pcb", str(proj_dir), "--out", str(proj_dir / "b.png"),
         "--format", "png", "--json"],
    )
    assert r.exit_code == 0, r.stdout
    out = json.loads(r.stdout)
    assert out["data"]["format"] == "svg"          # honest about the fallback
    assert any(a["kind"] == "pcb_svg" for a in out["artifacts"])
    assert any("PNG rasterization failed" in w for w in out["warnings"])


def test_render_sch_png_degrades_to_svg(proj_dir: Path, monkeypatch) -> None:
    monkeypatch.setattr(kicad_cli, "export_sch_png", _boom)

    def fake_sch_svg(cli, sch, out_dir):
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        (Path(out_dir) / "demo.svg").write_text("<svg/>")
        return Path(out_dir)

    monkeypatch.setattr(kicad_cli, "export_sch_svg", fake_sch_svg)
    r = CliRunner().invoke(
        render_app,
        ["sch", str(proj_dir), "--out", str(proj_dir / "s.png"),
         "--format", "png", "--json"],
    )
    assert r.exit_code == 0, r.stdout
    out = json.loads(r.stdout)
    assert out["data"]["format"] == "svg"
    assert any(a["kind"] == "schematic_svg" for a in out["artifacts"])
    assert any("PNG rasterization failed" in w for w in out["warnings"])


# ---------------------------------------------------------------------------
# Region cropping (Round-5 field report R5-2)
# ---------------------------------------------------------------------------

_BOARD = {"min_x": 0.0, "min_y": 0.0, "width": 40.0, "height": 40.0}


def test_region_viewbox_maps_region_to_fraction() -> None:
    """A 10 mm window of a 40 mm board is a quarter-width of the viewBox."""
    vb = _region_viewbox((10, 10, 20, 20), _BOARD, (0, 0, 4000, 4000))
    assert vb == (1000.0, 1000.0, 1000.0, 1000.0)


def test_region_viewbox_clamps_off_board_window() -> None:
    """A window running off the board edge is clamped to the board."""
    vb = _region_viewbox((-50, -50, 20, 20), _BOARD, (0, 0, 4000, 4000))
    assert vb == (0.0, 0.0, 2000.0, 2000.0)


def test_region_viewbox_rejects_non_overlapping_window() -> None:
    with pytest.raises(ValueError, match="does not overlap"):
        _region_viewbox((100, 100, 120, 120), _BOARD, (0, 0, 4000, 4000))


def test_crop_svg_region_rewrites_viewbox_and_dims(tmp_path: Path) -> None:
    svg = tmp_path / "b.svg"
    svg.write_text(
        '<svg width="40mm" height="40mm" viewBox="0 0 4000 4000"><rect/></svg>'
    )
    _crop_svg_region(svg, (10, 10, 20, 20), _BOARD)
    text = svg.read_text()
    assert 'viewBox="1000.000000 1000.000000 1000.000000 1000.000000"' in text
    assert 'width="10.000000mm"' in text   # 40 mm * (1000 / 4000)
    assert 'height="10.000000mm"' in text


def test_crop_svg_region_errors_on_missing_viewbox(tmp_path: Path) -> None:
    svg = tmp_path / "b.svg"
    svg.write_text('<svg width="40mm" height="40mm"><rect/></svg>')
    with pytest.raises(CommandError):
        _crop_svg_region(svg, (10, 10, 20, 20), _BOARD)


def test_region_dpi_scales_to_keep_detail() -> None:
    """Zooming in must not cost pixels — dpi scales by board/region width."""
    assert _region_dpi(300, (10, 10, 20, 20), _BOARD) == 1200   # 40 / 10
    assert _region_dpi(300, (0, 0, 1, 1), _BOARD) == 2400       # capped


def test_resolve_region_parses_bbox() -> None:
    assert _resolve_region(None, "20,5,10,15", 20.0) == (10.0, 5.0, 20.0, 15.0)


def test_resolve_region_rejects_both_flags() -> None:
    with pytest.raises(CommandError):
        _resolve_region("R5", "0,0,10,10", 20.0)


def test_resolve_region_rejects_malformed_bbox() -> None:
    with pytest.raises(CommandError):
        _resolve_region(None, "0,0,10", 20.0)


def test_resolve_region_ref_centres_window_on_footprint(monkeypatch) -> None:
    monkeypatch.setattr(
        kipy_pcb, "find_footprint", lambda ref: {"x_mm": 30.0, "y_mm": 50.0}
    )
    assert _resolve_region("R5", None, 10.0) == (25.0, 45.0, 35.0, 55.0)


def test_render_pcb_region_bbox_crops_the_svg(
    proj_dir: Path, monkeypatch,
) -> None:
    """`render pcb --region-bbox` rewrites the exported SVG's viewBox."""
    monkeypatch.setattr(kipy_pcb, "board_bbox", lambda: dict(_BOARD))

    def fake_pcb_svg(cli, pcb, out, layers=None, mirror=False):
        Path(out).write_text(
            '<svg width="40mm" height="40mm" viewBox="0 0 4000 4000"><rect/></svg>'
        )
        return out

    monkeypatch.setattr(kicad_cli, "export_pcb_svg", fake_pcb_svg)
    out_svg = proj_dir / "r.svg"
    r = CliRunner().invoke(
        render_app,
        ["pcb", str(proj_dir), "--out", str(out_svg), "--format", "svg",
         "--region-bbox", "10,10,20,20", "--json"],
    )
    assert r.exit_code == 0, r.stdout
    assert 'viewBox="1000.000000 1000.000000 1000.000000 1000.000000"' in (
        out_svg.read_text()
    )
    out = json.loads(r.stdout)
    assert out["data"]["region_mm"] == [10.0, 10.0, 20.0, 20.0]


def test_render_pcb_region_rejected_for_pdf(proj_dir: Path, monkeypatch) -> None:
    monkeypatch.setattr(kipy_pcb, "board_bbox", lambda: dict(_BOARD))
    r = CliRunner().invoke(
        render_app,
        ["pcb", str(proj_dir), "--out", str(proj_dir / "r.pdf"),
         "--format", "pdf", "--region-bbox", "10,10,20,20", "--json"],
    )
    assert r.exit_code == 1
    assert json.loads(r.stdout)["error"]["code"] == "bad_region"


# ---------------------------------------------------------------------------
# Side selection + layer transparency (Round-6 field report)
# ---------------------------------------------------------------------------

def _capturing_svg(calls: list[dict]):
    """An `export_pcb_svg` fake that records its layer/mirror args."""
    def fake(cli, pcb, out, layers=None, mirror=False):
        calls.append({"layers": layers, "mirror": mirror})
        tag = "F" if layers and "F.Cu" in layers else "B"
        Path(out).write_text(
            f'<svg width="40mm" viewBox="0 0 4000 4000"><rect id="{tag}"/></svg>'
        )
        return out
    return fake


def test_composite_layers_stacks_back_under_front() -> None:
    """`_composite_layers` keeps the front root and inserts the back first,
    inside a faded group, so the back shows through without hiding the front."""
    front = '<svg viewBox="0 0 10 10" width="10mm"><rect id="F"/></svg>'
    back = '<svg viewBox="0 0 10 10" width="10mm"><rect id="B"/></svg>'
    result = _composite_layers(front, back, 0.35)
    assert '<g opacity="0.350">' in result
    assert result.index('id="B"') < result.index('id="F"')   # back drawn first
    assert 'viewBox="0 0 10 10"' in result                    # front root kept
    assert result.count("<svg") == 1 and result.count("</svg>") == 1


def test_composite_layers_rejects_svg_without_root() -> None:
    with pytest.raises(CommandError):
        _composite_layers("not an svg", "<svg></svg>", 0.35)


def test_render_pcb_side_top_is_the_clean_default(
    proj_dir: Path, monkeypatch,
) -> None:
    """`render pcb` defaults to a single-side top view — no B.Cu, so a
    ground pour can't hide the front (Round-6 field report)."""
    calls: list[dict] = []
    monkeypatch.setattr(kicad_cli, "export_pcb_svg", _capturing_svg(calls))
    r = CliRunner().invoke(
        render_app,
        ["pcb", str(proj_dir), "--out", str(proj_dir / "b.svg"), "--json"],
    )
    assert r.exit_code == 0, r.stdout
    assert len(calls) == 1
    assert calls[0]["layers"] == ["F.Cu", "F.SilkS", "Edge.Cuts"]
    assert calls[0]["mirror"] is False
    assert json.loads(r.stdout)["data"]["side"] == "top"


def test_render_pcb_side_bottom_mirrors(proj_dir: Path, monkeypatch) -> None:
    """`--side bottom` renders the back layer set, mirrored so text reads."""
    calls: list[dict] = []
    monkeypatch.setattr(kicad_cli, "export_pcb_svg", _capturing_svg(calls))
    r = CliRunner().invoke(
        render_app,
        ["pcb", str(proj_dir), "--out", str(proj_dir / "b.svg"),
         "--side", "bottom", "--json"],
    )
    assert r.exit_code == 0, r.stdout
    assert calls[0]["layers"] == ["B.Cu", "B.SilkS", "Edge.Cuts"]
    assert calls[0]["mirror"] is True


def test_render_pcb_explicit_layers_override_side(
    proj_dir: Path, monkeypatch,
) -> None:
    """An explicit `--layers` wins over `--side`."""
    calls: list[dict] = []
    monkeypatch.setattr(kicad_cli, "export_pcb_svg", _capturing_svg(calls))
    r = CliRunner().invoke(
        render_app,
        ["pcb", str(proj_dir), "--out", str(proj_dir / "b.svg"),
         "--side", "bottom", "--layers", "F.Cu,Edge.Cuts", "--json"],
    )
    assert r.exit_code == 0, r.stdout
    assert calls[0]["layers"] == ["F.Cu", "Edge.Cuts"]
    assert json.loads(r.stdout)["data"]["side"] == "custom"


def test_render_pcb_side_both_composites(proj_dir: Path, monkeypatch) -> None:
    """`--side both` exports front + back and stacks them with the back faded."""
    calls: list[dict] = []
    monkeypatch.setattr(kicad_cli, "export_pcb_svg", _capturing_svg(calls))
    out_svg = proj_dir / "both.svg"
    r = CliRunner().invoke(
        render_app,
        ["pcb", str(proj_dir), "--out", str(out_svg), "--side", "both",
         "--back-opacity", "0.4", "--json"],
    )
    assert r.exit_code == 0, r.stdout
    assert len(calls) == 2   # one export per side
    text = out_svg.read_text()
    assert '<g opacity="0.400">' in text
    assert text.index('id="B"') < text.index('id="F"')   # back under front


def test_render_pcb_side_both_rejected_for_pdf(
    proj_dir: Path, monkeypatch,
) -> None:
    r = CliRunner().invoke(
        render_app,
        ["pcb", str(proj_dir), "--out", str(proj_dir / "b.pdf"),
         "--format", "pdf", "--side", "both", "--json"],
    )
    assert r.exit_code == 1
    assert json.loads(r.stdout)["error"]["code"] == "bad_side"


def test_render_pcb_rejects_bad_back_opacity(proj_dir: Path) -> None:
    r = CliRunner().invoke(
        render_app,
        ["pcb", str(proj_dir), "--out", str(proj_dir / "b.svg"),
         "--side", "both", "--back-opacity", "1.5", "--json"],
    )
    assert r.exit_code == 1
    assert json.loads(r.stdout)["error"]["code"] == "bad_opacity"


def test_render_pcb_rejects_bad_side(proj_dir: Path) -> None:
    r = CliRunner().invoke(
        render_app,
        ["pcb", str(proj_dir), "--out", str(proj_dir / "b.svg"),
         "--side", "sideways", "--json"],
    )
    assert r.exit_code == 1
    assert json.loads(r.stdout)["error"]["code"] == "bad_side"
