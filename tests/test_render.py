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

from kcd.adapters import kicad_cli
from kcd.commands.render import render_app


@pytest.fixture
def proj_dir(tmp_path: Path) -> Path:
    (tmp_path / "demo.kicad_pro").write_text("{}")
    (tmp_path / "demo.kicad_sch").write_text("(kicad_sch)")
    (tmp_path / "demo.kicad_pcb").write_text("(kicad_pcb)")
    return tmp_path


def _boom(*a, **k):
    raise kicad_cli.CliError(["png-rasterize"], 1, "", "resvg could not rasterize")


def test_render_pcb_png_degrades_to_svg(proj_dir: Path, monkeypatch) -> None:
    monkeypatch.setattr(kicad_cli, "export_pcb_png", _boom)

    def fake_pcb_svg(cli, pcb, out, layers=None):
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
