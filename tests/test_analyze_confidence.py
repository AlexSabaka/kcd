"""Tests for analyzer false-confidence guards (Round-3 field report B5/B6/B7).

The vendored analyzers report confident verdicts from partial or empty
evaluation. kcd's command layer post-processes the analyzer JSON to catch:
  B5 — fab-gate routing PASS while DRC finds unconnected pads
  B6 — thermal_score 100 from zero assessed components
  B7 — MPN coverage blind to the SnapEDA `MP` field
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from kcd.adapters import analyzers, kicad_cli
from kcd.commands.analyze import analyze_fab_gate_cmd, analyze_thermal_cmd

_fab_gate_app = typer.Typer()
_fab_gate_app.command()(analyze_fab_gate_cmd)
_thermal_app = typer.Typer()
_thermal_app.command()(analyze_thermal_cmd)


@pytest.fixture
def proj_dir(tmp_path: Path) -> Path:
    (tmp_path / "demo.kicad_pro").write_text("{}")
    (tmp_path / "demo.kicad_sch").write_text("(kicad_sch)")
    (tmp_path / "demo.kicad_pcb").write_text("(kicad_pcb)")
    return tmp_path


def _stub_analyzer(monkeypatch, data: dict) -> None:
    monkeypatch.setattr(analyzers, "run_analyzer", lambda *a, **k: data)


def _stub_argv(monkeypatch, data: dict) -> None:
    monkeypatch.setattr(analyzers, "run_analyzer_argv", lambda *a, **k: data)


def _routing_pass_gate() -> dict:
    return {
        "overall_status": "PASS",
        "summary": {"total_checks": 1, "pass": 1, "warn": 0, "fail": 0, "skip": 0},
        "checks": [
            {"category": "routing", "check_id": "routing_completeness",
             "status": "pass", "message": "All nets routed (80/80)",
             "details": None},
        ],
    }


def _invoke(app: typer.Typer, proj_dir: Path) -> dict:
    r = CliRunner().invoke(
        app, [str(proj_dir), "--out", str(proj_dir / "o.json"), "--json"]
    )
    assert r.exit_code == 0, r.stdout
    return json.loads(r.stdout)


# ---------------------------------------------------------------------------
# B5 — fab-gate routing reconciled against DRC
# ---------------------------------------------------------------------------

def test_fab_gate_routing_downgraded_when_drc_finds_unconnected(
    monkeypatch, proj_dir: Path,
) -> None:
    _stub_analyzer(monkeypatch, {"findings": []})
    _stub_argv(monkeypatch, _routing_pass_gate())
    monkeypatch.setattr(
        kicad_cli, "run_drc",
        lambda *a, **k: {"unconnected_items": [{"i": 1}, {"i": 2}, {"i": 3}]},
    )
    out = _invoke(_fab_gate_app, proj_dir)
    data = out["data"]
    routing = next(
        c for c in data["checks"] if c["check_id"] == "routing_completeness"
    )
    assert routing["status"] == "fail"
    assert routing["details"]["drc_unconnected"] == 3
    assert data["overall_status"] == "FAIL"
    assert data["summary"]["fail"] == 1
    assert data["summary"]["pass"] == 0
    assert any("downgraded to FAIL" in w for w in out["warnings"])


def test_fab_gate_routing_kept_when_drc_clean(
    monkeypatch, proj_dir: Path,
) -> None:
    _stub_analyzer(monkeypatch, {"findings": []})
    _stub_argv(monkeypatch, _routing_pass_gate())
    monkeypatch.setattr(
        kicad_cli, "run_drc", lambda *a, **k: {"unconnected_items": []}
    )
    out = _invoke(_fab_gate_app, proj_dir)
    routing = next(
        c for c in out["data"]["checks"] if c["check_id"] == "routing_completeness"
    )
    assert routing["status"] == "pass"
    assert out["data"]["overall_status"] == "PASS"


def test_fab_gate_routing_drc_failure_is_graceful(
    monkeypatch, proj_dir: Path,
) -> None:
    """A DRC cross-check that errors must not break the gate — it warns and
    leaves the gate verdict untouched."""
    _stub_analyzer(monkeypatch, {"findings": []})
    _stub_argv(monkeypatch, _routing_pass_gate())

    def boom(*a, **k):
        raise RuntimeError("kicad-cli not found")

    monkeypatch.setattr(kicad_cli, "run_drc", boom)
    out = _invoke(_fab_gate_app, proj_dir)
    routing = next(
        c for c in out["data"]["checks"] if c["check_id"] == "routing_completeness"
    )
    assert routing["status"] == "pass"
    assert any("could not cross-check routing" in w for w in out["warnings"])


# ---------------------------------------------------------------------------
# B6 — thermal score guarded against empty assessment
# ---------------------------------------------------------------------------

def test_thermal_score_flagged_insufficient_when_nothing_assessed(
    monkeypatch, proj_dir: Path,
) -> None:
    _stub_analyzer(monkeypatch, {"findings": []})
    _stub_argv(monkeypatch, {
        "summary": {"thermal_score": 100, "components_assessed": 0,
                    "total_board_dissipation_w": 0},
        "findings": [],
    })
    out = _invoke(_thermal_app, proj_dir)
    summary = out["data"]["summary"]
    assert summary["thermal_score"] is None
    assert summary["thermal_score_status"] == "insufficient_data"
    assert any("insufficient_data" in w for w in out["warnings"])


def test_thermal_score_kept_when_components_assessed(
    monkeypatch, proj_dir: Path,
) -> None:
    _stub_analyzer(monkeypatch, {"findings": []})
    _stub_argv(monkeypatch, {
        "summary": {"thermal_score": 87, "components_assessed": 5},
        "findings": [],
    })
    out = _invoke(_thermal_app, proj_dir)
    summary = out["data"]["summary"]
    assert summary["thermal_score"] == 87
    assert "thermal_score_status" not in summary


# ---------------------------------------------------------------------------
# B7 — MPN key set recognizes the SnapEDA `MP` field
# ---------------------------------------------------------------------------

def test_mpn_keys_recognize_mp_and_mfr_part_no() -> None:
    """The vendored schematic analyzer's `_MPN_KEYS` recognizes `MP` and
    `Mfr_Part_No` aliases (loaded by path — the engine is subprocess-only)."""
    path = (Path(__file__).parent.parent / "src" / "kcd" / "analyzers"
            / "analyze_schematic.py")
    spec = importlib.util.spec_from_file_location("_kcd_analyze_sch_probe", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert "mp" in mod._MPN_KEYS
    assert "mfr_part_no" in mod._MPN_KEYS
    assert "mpn" in mod._MPN_KEYS  # original aliases preserved
