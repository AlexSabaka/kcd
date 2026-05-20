"""Tests for `kcd analyze` inline-envelope folding (Round-3 field report B2).

The vendored analyzers emit large JSON — a real board overruns the 1MB MCP
result cap. `_compact` folds `findings`, keeps the headline, and spills bulk
sections to the artifact. These tests monkeypatch `analyzers.run_analyzer`
with a deliberately large canned report and assert the folded shape; the
artifact must still hold the complete report.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from kcd.adapters import analyzers
from kcd.commands.analyze import _compact, analyze_sch_cmd

_sch_app = typer.Typer()
_sch_app.command()(analyze_sch_cmd)


@pytest.fixture
def proj_dir(tmp_path: Path) -> Path:
    (tmp_path / "demo.kicad_pro").write_text("{}")
    (tmp_path / "demo.kicad_sch").write_text("(kicad_sch)")
    (tmp_path / "demo.kicad_pcb").write_text("(kicad_pcb)")
    return tmp_path


def _big_report() -> dict:
    """A canned analyzer report large enough to force spilling."""
    return {
        "analyzer_type": "schematic",
        "schema_version": "1.3.0",
        "summary": {"total_findings": 14, "components": 200},
        "trust_summary": {"trust_level": "high"},
        "findings": (
            [{"severity": "error", "rule_id": "RS-001",
              "detail": f"missing source {i}"} for i in range(8)]
            + [{"severity": "warning", "rule_id": "DC-002",
                "detail": f"thin decoupling {i}"} for i in range(5)]
            + [{"severity": "info", "rule_id": "CG-AUD", "detail": "ground ok"}]
        ),
        # bom + nets are the bulk — each well over _VALUE_BUDGET (24k chars).
        "bom": [{"ref": f"R{i}", "value": "10k", "blob": "x" * 400}
                for i in range(200)],
        "nets": [{"name": f"N{i}", "pins": list(range(60))}
                 for i in range(200)],
    }


def _invoke(proj_dir: Path) -> tuple[dict, Path]:
    out_path = proj_dir / "report.json"
    r = CliRunner().invoke(
        _sch_app, [str(proj_dir), "--out", str(out_path), "--json"]
    )
    assert r.exit_code == 0, r.stdout
    return json.loads(r.stdout), out_path


# ---------------------------------------------------------------------------
# _compact — unit
# ---------------------------------------------------------------------------

def test_compact_folds_findings_by_rule_and_severity() -> None:
    data = _compact(_big_report())
    assert data["finding_total"] == 14
    by_rule = {g["rule_id"]: g for g in data["findings"]}
    assert by_rule["RS-001"]["count"] == 8
    assert len(by_rule["RS-001"]["sample"]) == 3  # capped at _FOLD_SAMPLE
    assert by_rule["DC-002"]["count"] == 5
    assert len(by_rule["DC-002"]["sample"]) == 3
    assert by_rule["CG-AUD"]["count"] == 1
    # errors sort ahead of warnings ahead of info
    assert data["findings"][0]["severity"] == "error"
    assert data["findings"][-1]["severity"] == "info"


def test_compact_spills_bulk_sections() -> None:
    data = _compact(_big_report())
    assert set(data["spilled"]["sections"]) == {"bom", "nets"}
    # a spilled list keeps a count stub so the agent still sees the size
    assert data["bom"] == {"count": 200}
    assert data["nets"] == {"count": 200}


def test_compact_keeps_headline_and_scalars() -> None:
    data = _compact(_big_report())
    assert data["summary"] == {"total_findings": 14, "components": 200}
    assert data["trust_summary"] == {"trust_level": "high"}
    assert data["analyzer_type"] == "schematic"


def test_compact_small_report_keeps_everything() -> None:
    """A report under budget keeps every section — only findings are folded."""
    small = {"analyzer_type": "pcb", "footprints": [{"ref": "R1"}],
             "findings": [{"severity": "warning", "rule_id": "X", "detail": "y"}]}
    data = _compact(small)
    assert "spilled" not in data
    assert data["footprints"] == [{"ref": "R1"}]
    assert data["finding_total"] == 1


# ---------------------------------------------------------------------------
# command-level — inline stays small, artifact holds the full report
# ---------------------------------------------------------------------------

def test_analyze_sch_inline_is_small(monkeypatch, proj_dir: Path) -> None:
    monkeypatch.setattr(
        analyzers, "run_analyzer", lambda *a, **k: _big_report()
    )
    out, _ = _invoke(proj_dir)
    inline = json.dumps(out["data"])
    raw = json.dumps(_big_report())
    assert len(inline) < 96_000          # under the compaction budget
    assert len(inline) < len(raw) // 4   # and far smaller than the raw report
    assert out["data"]["spilled"]["sections"] == ["bom", "nets"]


def test_analyze_sch_artifact_holds_full_report(
    monkeypatch, proj_dir: Path,
) -> None:
    monkeypatch.setattr(
        analyzers, "run_analyzer", lambda *a, **k: _big_report()
    )
    out, out_path = _invoke(proj_dir)
    assert out["artifacts"][0]["kind"] == "analyze_schematic_json"
    full = json.loads(out_path.read_text())
    # the artifact is never folded — every component, with its blob, survives
    assert len(full["bom"]) == 200
    assert full["bom"][0]["blob"] == "x" * 400
    assert len(full["findings"]) == 14
