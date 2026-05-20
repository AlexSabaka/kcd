"""Tests for analyzer false-confidence guards.

Round-3 B5/B6/B7 and Round-5 R5-3/R5-5/R5-6 — the vendored analyzers report
confident verdicts from partial or empty evaluation, or crash on inputs they
don't handle. kcd's command layer post-processes / guards the analyzer JSON:
  B5   — fab-gate routing PASS while DRC finds unconnected pads
  B6   — thermal_score 100 from zero assessed components
  B7   — MPN coverage blind to the SnapEDA `MP` field
  R5-3 — analyze_pcb connectivity routing_complete vs DRC
  R5-5 — analyze diff crashes on gerber (and other unsupported) JSONs
  R5-6 — analyze_cross 0 findings reads as a clean bill of health
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from kcd.adapters import analyzers, kicad_cli
from kcd.commands.analyze import (
    analyze_cross_cmd,
    analyze_diff_cmd,
    analyze_fab_gate_cmd,
    analyze_pcb_cmd,
    analyze_thermal_cmd,
)

_fab_gate_app = typer.Typer()
_fab_gate_app.command()(analyze_fab_gate_cmd)
_thermal_app = typer.Typer()
_thermal_app.command()(analyze_thermal_cmd)
_pcb_app = typer.Typer()
_pcb_app.command()(analyze_pcb_cmd)
_cross_app = typer.Typer()
_cross_app.command()(analyze_cross_cmd)
_diff_app = typer.Typer()
_diff_app.command()(analyze_diff_cmd)


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


# ---------------------------------------------------------------------------
# R5-3 — analyze_pcb connectivity reconciled against DRC
# ---------------------------------------------------------------------------

def test_pcb_connectivity_downgraded_when_drc_finds_unconnected(
    monkeypatch, proj_dir: Path,
) -> None:
    _stub_analyzer(monkeypatch, {
        "findings": [],
        "connectivity": {"routing_complete": True, "unrouted_count": 0},
    })
    monkeypatch.setattr(
        kicad_cli, "run_drc",
        lambda *a, **k: {"unconnected_items": [{"i": 1}, {"i": 2}]},
    )
    out = _invoke(_pcb_app, proj_dir)
    conn = out["data"]["connectivity"]
    assert conn["routing_complete"] is False
    assert conn["drc_unconnected"] == 2
    assert any("connectivity downgraded" in w for w in out["warnings"])


def test_pcb_connectivity_kept_when_drc_clean(
    monkeypatch, proj_dir: Path,
) -> None:
    _stub_analyzer(monkeypatch, {
        "findings": [],
        "connectivity": {"routing_complete": True, "unrouted_count": 0},
    })
    monkeypatch.setattr(
        kicad_cli, "run_drc", lambda *a, **k: {"unconnected_items": []}
    )
    out = _invoke(_pcb_app, proj_dir)
    assert out["data"]["connectivity"]["routing_complete"] is True


def test_pcb_connectivity_skips_drc_when_already_incomplete(
    monkeypatch, proj_dir: Path,
) -> None:
    """No DRC run when routing is already reported incomplete — the
    reconciliation only ever downgrades a falsely-passing verdict."""
    _stub_analyzer(monkeypatch, {
        "findings": [],
        "connectivity": {"routing_complete": False, "unrouted_count": 5},
    })

    def boom(*a, **k):
        raise AssertionError("DRC must not run when routing is incomplete")

    monkeypatch.setattr(kicad_cli, "run_drc", boom)
    out = _invoke(_pcb_app, proj_dir)
    assert out["data"]["connectivity"]["routing_complete"] is False


# ---------------------------------------------------------------------------
# R5-6 — analyze_cross flags an unevaluated (0-finding) report
# ---------------------------------------------------------------------------

def test_cross_flagged_insufficient_when_no_findings(
    monkeypatch, proj_dir: Path,
) -> None:
    _stub_analyzer(monkeypatch, {"findings": []})
    _stub_argv(monkeypatch, {
        "analyzer_type": "cross_analysis",
        "summary": {"total_findings": 0, "by_severity": {}},
        "findings": [],
        "trust_summary": {"trust_level": "high", "provenance_coverage_pct": None},
    })
    out = _invoke(_cross_app, proj_dir)
    summary = out["data"]["summary"]
    assert summary["assessment_status"] == "insufficient_data"
    assert any("insufficient_data" in w for w in out["warnings"])


def test_cross_not_flagged_when_findings_present(
    monkeypatch, proj_dir: Path,
) -> None:
    _stub_analyzer(monkeypatch, {"findings": []})
    _stub_argv(monkeypatch, {
        "analyzer_type": "cross_analysis",
        "summary": {"total_findings": 1, "by_severity": {"warning": 1}},
        "findings": [{"severity": "warning", "rule_id": "X", "detail": "y"}],
        "trust_summary": {"trust_level": "medium"},
    })
    out = _invoke(_cross_app, proj_dir)
    assert "assessment_status" not in out["data"]["summary"]


# ---------------------------------------------------------------------------
# R5-5 — analyze diff guards unsupported analyzer types instead of crashing
# ---------------------------------------------------------------------------

def _write_json(p: Path, obj: dict) -> Path:
    p.write_text(json.dumps(obj))
    return p


def test_diff_rejects_gerber_json(tmp_path: Path) -> None:
    """A gerber JSON used to KeyError inside the vendored differ — it now
    returns a clean `unsupported_diff` error."""
    base = _write_json(tmp_path / "base.json", {"analyzer_type": "gerber"})
    head = _write_json(tmp_path / "head.json", {"analyzer_type": "gerber"})
    r = CliRunner().invoke(_diff_app, [str(base), str(head), "--json"])
    assert r.exit_code == 1
    out = json.loads(r.stdout)
    assert out["ok"] is False
    assert out["error"]["code"] == "unsupported_diff"
    assert "gerber" in out["error"]["message"]


def test_diff_rejects_mismatched_types(tmp_path: Path) -> None:
    base = _write_json(tmp_path / "base.json", {"analyzer_type": "pcb"})
    head = _write_json(tmp_path / "head.json", {"analyzer_type": "schematic"})
    r = CliRunner().invoke(_diff_app, [str(base), str(head), "--json"])
    assert r.exit_code == 1
    out = json.loads(r.stdout)
    assert out["error"]["code"] == "unsupported_diff"
    assert "same analyzer type" in out["error"]["message"]


def test_diff_supported_types_pass_the_guard(
    monkeypatch, tmp_path: Path,
) -> None:
    """Two pcb JSONs clear the guard; the differ is stubbed so this stays a
    unit test."""
    base = _write_json(tmp_path / "base.json", {"analyzer_type": "pcb"})
    head = _write_json(tmp_path / "head.json", {"analyzer_type": "pcb"})
    monkeypatch.setattr(
        analyzers, "run_analyzer_argv",
        lambda *a, **k: {"analyzer_type": "pcb", "findings": []},
    )
    r = CliRunner().invoke(
        _diff_app,
        [str(base), str(head), "--out", str(tmp_path / "d.json"), "--json"],
    )
    assert r.exit_code == 0, r.stdout
