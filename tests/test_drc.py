"""Tests for `kcd drc` / `kcd erc` — the folded, token-efficient report.

`kicad_cli.run_drc` / `run_erc` are monkeypatched with a canned kicad-cli
report; the tests assert the folding, compaction, capping, and artifact
behaviour without a live KiCad.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from kcd.adapters import kicad_cli
from kcd.commands.drc import drc_cmd, erc_cmd

_drc_app = typer.Typer()
_drc_app.command()(drc_cmd)
_erc_app = typer.Typer()
_erc_app.command()(erc_cmd)


def _item(desc: str, x: float, y: float, uuid: str) -> dict:
    return {"description": desc, "pos": {"x": x, "y": y}, "uuid": uuid}


def _raw_drc() -> dict:
    """A canned kicad-cli DRC report: 8 clearance, 2 silk, 1 track, 1 unconnected."""
    violations = [
        {"description": "Clearance violation", "severity": "error",
         "type": "clearance", "items": [_item(f"Pad {i}", 1.0 + i, 2.0, f"c-{i}")]}
        for i in range(8)
    ]
    violations += [
        {"description": "Silk over copper", "severity": "warning",
         "type": "silk_overlap", "items": [_item(f"Silk {i}", 3.0, 4.0, f"s-{i}")]}
        for i in range(2)
    ]
    violations.append({
        "description": "Track has a dangling end", "severity": "error",
        "type": "track_dangling", "items": [_item("Track", 5.0, 6.0, "t-0")],
    })
    return {
        "violations": violations,
        "unconnected_items": [{
            "description": "Missing connection between items", "severity": "error",
            "type": "unconnected_items",
            "items": [_item("Pad A", 7.0, 8.0, "u-0"), _item("Pad B", 9.0, 10.0, "u-1")],
        }],
        "schematic_parity": [],
    }


@pytest.fixture
def proj_dir(tmp_path: Path) -> Path:
    (tmp_path / "demo.kicad_pro").write_text("{}")
    (tmp_path / "demo.kicad_pcb").write_text("(kicad_pcb)")
    (tmp_path / "demo.kicad_sch").write_text("(kicad_sch)")
    return tmp_path


def _invoke(app: typer.Typer, proj_dir: Path, *extra: str) -> tuple[dict, Path]:
    out_path = proj_dir / "report.json"
    r = CliRunner().invoke(
        app, [str(proj_dir), "--out", str(out_path), "--json", *extra]
    )
    assert r.exit_code == 0, r.stdout
    return json.loads(r.stdout), out_path


# ---------------------------------------------------------------------------
# drc — folding, summary, compaction
# ---------------------------------------------------------------------------

def test_drc_folds_violations_by_type(monkeypatch, proj_dir: Path) -> None:
    monkeypatch.setattr(kicad_cli, "run_drc", lambda *a, **k: _raw_drc())
    out, _ = _invoke(_drc_app, proj_dir)
    data = out["data"]
    assert out["command"] == "drc"
    assert data["total"] == 12
    groups = data["violations"]
    assert len(groups) == 4  # 4 distinct (type, severity)
    by_type = {g["type"]: g for g in groups}
    assert by_type["clearance"]["count"] == 8
    assert by_type["clearance"]["shown"] == 3      # capped at _SAMPLE
    assert len(by_type["clearance"]["occurrences"]) == 3
    assert by_type["silk_overlap"]["count"] == 2
    assert by_type["silk_overlap"]["shown"] == 2   # below the cap — all shown
    # errors sort ahead of warnings, biggest group first
    assert groups[0]["type"] == "clearance"
    assert groups[-1]["severity"] == "warning"


def test_drc_summary_counts(monkeypatch, proj_dir: Path) -> None:
    monkeypatch.setattr(kicad_cli, "run_drc", lambda *a, **k: _raw_drc())
    out, _ = _invoke(_drc_app, proj_dir)
    assert out["data"]["summary"] == {
        "errors": 10, "warnings": 2, "exclusions": 0,
        "unconnected": 1, "parity_issues": 0,
    }


def test_drc_drops_uuid_inline_and_compacts_pos(monkeypatch, proj_dir: Path) -> None:
    monkeypatch.setattr(kicad_cli, "run_drc", lambda *a, **k: _raw_drc())
    out, _ = _invoke(_drc_app, proj_dir)
    item = out["data"]["violations"][0]["occurrences"][0]["items"][0]
    assert item["at"] == [1.0, 2.0]   # pos {x,y} -> [x,y]
    assert "uuid" not in item         # uuid dropped from the inline envelope
    assert "pos" not in item


def test_drc_full_flag_inlines_every_occurrence(monkeypatch, proj_dir: Path) -> None:
    monkeypatch.setattr(kicad_cli, "run_drc", lambda *a, **k: _raw_drc())
    out, _ = _invoke(_drc_app, proj_dir, "--full")
    clearance = next(
        g for g in out["data"]["violations"] if g["type"] == "clearance"
    )
    assert clearance["count"] == 8
    assert clearance["shown"] == 8    # per-group cap lifted


def test_drc_artifact_holds_full_report_with_uuids(
    monkeypatch, proj_dir: Path,
) -> None:
    monkeypatch.setattr(kicad_cli, "run_drc", lambda *a, **k: _raw_drc())
    out, out_path = _invoke(_drc_app, proj_dir)
    assert out["artifacts"][0]["kind"] == "drc_report"
    full = json.loads(out_path.read_text())
    clearance = next(g for g in full["violations"] if g["type"] == "clearance")
    assert clearance["shown"] == 8    # the artifact is never capped
    assert clearance["occurrences"][0]["items"][0]["uuid"] == "c-0"


def test_drc_warns_when_folded(monkeypatch, proj_dir: Path) -> None:
    monkeypatch.setattr(kicad_cli, "run_drc", lambda *a, **k: _raw_drc())
    out, _ = _invoke(_drc_app, proj_dir)
    assert any("12 violations" in w for w in out["warnings"])
    assert any("artifact" in w for w in out["warnings"])


# ---------------------------------------------------------------------------
# erc
# ---------------------------------------------------------------------------

def test_erc_folds_and_keeps_sheet_count(monkeypatch, proj_dir: Path) -> None:
    raw = {
        "violations": [
            {"description": "Pin not connected", "severity": "error",
             "type": "pin_not_connected",
             "items": [_item("Pin 3", 1.0, 2.0, "e-0")]},
            {"description": "Pin not connected", "severity": "error",
             "type": "pin_not_connected",
             "items": [_item("Pin 5", 3.0, 4.0, "e-1")]},
        ],
        "sheets": [{"name": "root"}, {"name": "sub"}],
    }
    monkeypatch.setattr(kicad_cli, "run_erc", lambda *a, **k: raw)
    out, _ = _invoke(_erc_app, proj_dir)
    data = out["data"]
    assert out["command"] == "erc"
    assert data["total"] == 2
    assert data["summary"]["errors"] == 2
    assert data["summary"]["sheet_count"] == 2
    assert len(data["violations"]) == 1
    assert data["violations"][0]["type"] == "pin_not_connected"
    assert data["violations"][0]["count"] == 2
