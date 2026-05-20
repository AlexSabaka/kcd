"""Tests for `kcd export` (Round-5 field report R5-4).

`export gerber` must ship a complete fab package — gerbers AND drill files —
because a fab house rejects a gerber set with no drills. The adapters are
monkeypatched so no real kicad-cli is needed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kcd.adapters import kicad_cli
from kcd.commands.export import export_app


@pytest.fixture
def proj_dir(tmp_path: Path) -> Path:
    (tmp_path / "demo.kicad_pro").write_text("{}")
    (tmp_path / "demo.kicad_sch").write_text("(kicad_sch)")
    (tmp_path / "demo.kicad_pcb").write_text("(kicad_pcb)")
    return tmp_path


def test_export_gerber_also_exports_drills(proj_dir: Path, monkeypatch) -> None:
    """`export gerber` must call both the gerber and the drill exporter."""
    calls: list[str] = []

    def fake_gerber(cli, pcb, out_dir):
        calls.append("gerber")
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        (Path(out_dir) / "demo-F_Cu.gbr").write_text("G04*")
        return out_dir

    def fake_drill(cli, pcb, out_dir):
        calls.append("drill")
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        (Path(out_dir) / "demo.drl").write_text("M48")
        return out_dir

    monkeypatch.setattr(kicad_cli, "export_gerber", fake_gerber)
    monkeypatch.setattr(kicad_cli, "export_drill", fake_drill)

    out_dir = proj_dir / "fab"
    r = CliRunner().invoke(
        export_app,
        ["gerber", str(proj_dir), "--out", str(out_dir), "--json"],
    )
    assert r.exit_code == 0, r.stdout
    out = json.loads(r.stdout)
    assert calls == ["gerber", "drill"]              # both run, gerber first
    assert out["data"]["drill_included"] is True
    assert (out_dir / "demo.drl").is_file()          # drills land in the set
