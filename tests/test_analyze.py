"""Unit tests for `kcd analyze sch|pcb|gerbers`.

These exercise the envelope wrapping (warning lifting, artifact registration,
error classification) by monkeypatching `analyzers.run_analyzer` with canned
data. They do NOT run the actual vendored analyzers — those are exercised
by the gated integration test (see `test_analyze_integration.py`).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from kcd.adapters import analyzers
from kcd.adapters.kicad_cli import CliError
from kcd.commands.analyze import (
    analyze_cross_cmd,
    analyze_diff_cmd,
    analyze_fab_gate_cmd,
    analyze_gerbers_cmd,
    analyze_lifecycle_cmd,
    analyze_pcb_cmd,
    analyze_sch_cmd,
    analyze_thermal_cmd,
    analyze_whatif_cmd,
)

# Wrap each command in its own Typer so CliRunner can invoke it directly. The
# real CLI mounts them under `kcd analyze sch|pcb|gerbers`; for tests we hit
# the underlying functions and pass `--json` for parseable output.
_sch_app = typer.Typer()
_sch_app.command()(analyze_sch_cmd)
_pcb_app = typer.Typer()
_pcb_app.command()(analyze_pcb_cmd)
_gerbers_app = typer.Typer()
_gerbers_app.command()(analyze_gerbers_cmd)
_cross_app = typer.Typer()
_cross_app.command()(analyze_cross_cmd)
_thermal_app = typer.Typer()
_thermal_app.command()(analyze_thermal_cmd)
_fab_gate_app = typer.Typer()
_fab_gate_app.command()(analyze_fab_gate_cmd)
_whatif_app = typer.Typer()
_whatif_app.command()(analyze_whatif_cmd)
_lifecycle_app = typer.Typer()
_lifecycle_app.command()(analyze_lifecycle_cmd)
_diff_app = typer.Typer()
_diff_app.command()(analyze_diff_cmd)


@pytest.fixture
def proj_dir(tmp_path: Path) -> Path:
    """A minimal one-symbol fixture project (no schematic content needed — the
    schematic and pcb files just need to *exist* for `resolve()` to succeed;
    the analyzer is mocked anyway)."""
    (tmp_path / "demo.kicad_pro").write_text("{}")
    (tmp_path / "demo.kicad_sch").write_text(
        '(kicad_sch (version 20231120) (generator "test"))'
    )
    (tmp_path / "demo.kicad_pcb").write_text(
        '(kicad_pcb (version 20231120) (generator "test"))'
    )
    return tmp_path


def _stub_analyzer(monkeypatch, data: dict) -> None:
    """Monkeypatch `analyzers.run_analyzer` to return canned data."""
    monkeypatch.setattr(
        analyzers, "run_analyzer",
        lambda script, target, **kw: data,
    )


def _stub_argv(monkeypatch, data: dict) -> None:
    """Monkeypatch `analyzers.run_analyzer_argv` to return canned data."""
    monkeypatch.setattr(
        analyzers, "run_analyzer_argv",
        lambda script, argv, **kw: data,
    )


# ---------------------------------------------------------------------------
# analyze sch
# ---------------------------------------------------------------------------

def test_analyze_sch_envelope_shape(monkeypatch, proj_dir: Path, tmp_path: Path) -> None:
    """Happy path: analyzer returns a dict → envelope wraps with ok=true."""
    _stub_analyzer(monkeypatch, {
        "analyzer_type": "schematic",
        "schema_version": "1.3.0",
        "summary": {"total_findings": 0},
        "findings": [],
    })
    runner = CliRunner()
    result = runner.invoke(
        _sch_app,
        [str(proj_dir), "--out", str(tmp_path / "out.json"), "--json"],
    )
    assert result.exit_code == 0, result.stdout
    out = json.loads(result.stdout)
    assert out["ok"] is True
    assert out["command"] == "analyze.sch"
    assert out["data"]["analyzer_type"] == "schematic"
    assert out["warnings"] == []
    assert out["error"] is None


def test_analyze_sch_lifts_warning_and_error_findings(monkeypatch, proj_dir: Path, tmp_path: Path) -> None:
    """Findings with severity in (warning, error, critical) become envelope warnings."""
    _stub_analyzer(monkeypatch, {
        "findings": [
            {"severity": "error", "rule_id": "RS-001", "detail": "no source declared"},
            {"severity": "warning", "rule_id": "SJ-DET", "detail": "JP1 open by default"},
            {"severity": "info", "rule_id": "CG-AUD", "detail": "ground distribution ok"},
            {"severity": "critical", "rule_id": "DR-FAIL", "summary": "DRC failed"},
        ],
    })
    runner = CliRunner()
    result = runner.invoke(
        _sch_app,
        [str(proj_dir), "--out", str(tmp_path / "out.json"), "--json"],
    )
    assert result.exit_code == 0, result.stdout
    out = json.loads(result.stdout)
    # 3 lifted (error + warning + critical); the info-level one stays in data only.
    assert len(out["warnings"]) == 3
    assert any("[error][RS-001]" in w and "no source" in w for w in out["warnings"])
    assert any("[warning][SJ-DET]" in w for w in out["warnings"])
    assert any("[critical][DR-FAIL]" in w and "DRC failed" in w for w in out["warnings"])
    # Info-level should NOT be lifted.
    assert not any("[info]" in w for w in out["warnings"])


def test_analyze_sch_writes_artifact(monkeypatch, proj_dir: Path, tmp_path: Path) -> None:
    """Raw analyzer JSON saved as artifact at the requested path."""
    _stub_analyzer(monkeypatch, {"schema_version": "1.3.0", "findings": []})
    out_path = tmp_path / "out.json"
    runner = CliRunner()
    result = runner.invoke(
        _sch_app,
        [str(proj_dir), "--out", str(out_path), "--json"],
    )
    assert result.exit_code == 0, result.stdout
    out = json.loads(result.stdout)
    assert len(out["artifacts"]) == 1
    assert out["artifacts"][0]["kind"] == "analyze_schematic_json"
    assert out["artifacts"][0]["path"] == str(out_path)
    # Artifact actually exists on disk.
    assert out_path.is_file()
    assert json.loads(out_path.read_text())["schema_version"] == "1.3.0"


def test_analyze_sch_classifies_analyzer_failure_as_cli_failed(
    monkeypatch, proj_dir: Path, tmp_path: Path,
) -> None:
    """CliError from the analyzer subprocess maps to error.code='cli_failed'."""
    def raise_cli(*args, **kw):
        raise CliError(
            ["python3", "analyze_schematic.py"],
            1, "", "schematic parse failed: malformed s-expression",
        )
    monkeypatch.setattr(analyzers, "run_analyzer", raise_cli)
    runner = CliRunner()
    result = runner.invoke(
        _sch_app,
        [str(proj_dir), "--out", str(tmp_path / "out.json"), "--json"],
    )
    assert result.exit_code == 1
    out = json.loads(result.stdout)
    assert out["ok"] is False
    assert out["error"]["code"] == "cli_failed"
    assert "schematic parse failed" in out["error"]["message"]


# ---------------------------------------------------------------------------
# analyze pcb
# ---------------------------------------------------------------------------

def test_analyze_pcb_envelope_shape(monkeypatch, proj_dir: Path, tmp_path: Path) -> None:
    """Happy path for pcb subcommand."""
    _stub_analyzer(monkeypatch, {
        "analyzer_type": "pcb",
        "kicad_version": "10.0",
        "footprints": [{"reference": "R1"}, {"reference": "C1"}],
        "findings": [],
    })
    runner = CliRunner()
    result = runner.invoke(
        _pcb_app,
        [str(proj_dir), "--out", str(tmp_path / "out.json"), "--json"],
    )
    assert result.exit_code == 0, result.stdout
    out = json.loads(result.stdout)
    assert out["ok"] is True
    assert out["command"] == "analyze.pcb"
    assert out["data"]["analyzer_type"] == "pcb"
    assert out["data"]["kicad_version"] == "10.0"
    assert len(out["data"]["footprints"]) == 2


def test_analyze_pcb_lifts_findings(monkeypatch, proj_dir: Path, tmp_path: Path) -> None:
    """PCB analyzer findings get the same lifting treatment as schematic."""
    _stub_analyzer(monkeypatch, {
        "findings": [
            {"severity": "warning", "rule_id": "TP-VIA", "detail": "thermal pad has 4 vias, recommended >=8"},
        ],
    })
    runner = CliRunner()
    result = runner.invoke(
        _pcb_app,
        [str(proj_dir), "--out", str(tmp_path / "out.json"), "--json"],
    )
    out = json.loads(result.stdout)
    assert any("[warning][TP-VIA]" in w for w in out["warnings"])


# ---------------------------------------------------------------------------
# analyze gerbers
# ---------------------------------------------------------------------------

def test_analyze_gerbers_envelope_shape(monkeypatch, tmp_path: Path) -> None:
    """Happy path: pass a directory, get analyzer JSON wrapped in envelope."""
    gerber_dir = tmp_path / "gerbers"
    gerber_dir.mkdir()
    _stub_analyzer(monkeypatch, {
        "analyzer_type": "gerbers",
        "layers": ["F.Cu", "B.Cu"],
        "findings": [],
    })
    runner = CliRunner()
    result = runner.invoke(
        _gerbers_app,
        [str(gerber_dir), "--out", str(tmp_path / "out.json"), "--json"],
    )
    assert result.exit_code == 0, result.stdout
    out = json.loads(result.stdout)
    assert out["ok"] is True
    assert out["command"] == "analyze.gerbers"
    assert out["data"]["layers"] == ["F.Cu", "B.Cu"]


def test_analyze_gerbers_requires_directory_not_file(monkeypatch, tmp_path: Path) -> None:
    """Passing a file path (not a directory) → error.code='not_found'."""
    file_path = tmp_path / "fake.gbr"
    file_path.write_text("garbage")
    # Mock should never be reached, but safety-net it.
    _stub_analyzer(monkeypatch, {"unreachable": True})
    runner = CliRunner()
    result = runner.invoke(
        _gerbers_app,
        [str(file_path), "--out", str(tmp_path / "out.json"), "--json"],
    )
    assert result.exit_code == 1
    out = json.loads(result.stdout)
    assert out["ok"] is False
    assert out["error"]["code"] == "not_found"
    assert "Not a directory" in out["error"]["message"]


def test_analyze_gerbers_requires_existing_directory(monkeypatch, tmp_path: Path) -> None:
    """Passing a nonexistent directory → error.code='not_found'."""
    runner = CliRunner()
    result = runner.invoke(
        _gerbers_app,
        [str(tmp_path / "does_not_exist"), "--json"],
    )
    assert result.exit_code == 1
    out = json.loads(result.stdout)
    assert out["ok"] is False
    assert out["error"]["code"] == "not_found"


# ---------------------------------------------------------------------------
# analyze pcb --full
# ---------------------------------------------------------------------------

def test_analyze_pcb_full_flag_forwarded(monkeypatch, proj_dir: Path, tmp_path: Path) -> None:
    """--full reaches the analyzer as an extra subprocess arg."""
    captured: dict = {}

    def fake(script, target, **kw):
        captured.update(kw)
        return {"findings": []}

    monkeypatch.setattr(analyzers, "run_analyzer", fake)
    result = CliRunner().invoke(
        _pcb_app, [str(proj_dir), "--full", "--out", str(tmp_path / "o.json"), "--json"]
    )
    assert result.exit_code == 0, result.stdout
    assert captured.get("extra_args") == ["--full"]


# ---------------------------------------------------------------------------
# analyze cross / thermal / fab-gate (derived from sch + pcb analyzer JSON)
# ---------------------------------------------------------------------------

def test_analyze_cross_envelope(monkeypatch, proj_dir: Path, tmp_path: Path) -> None:
    _stub_analyzer(monkeypatch, {"findings": []})
    _stub_argv(monkeypatch, {"analysis": "cross", "findings": [
        {"severity": "warning", "rule_id": "XD-001", "detail": "decoupling thin"},
    ]})
    result = CliRunner().invoke(
        _cross_app, [str(proj_dir), "--out", str(tmp_path / "o.json"), "--json"]
    )
    assert result.exit_code == 0, result.stdout
    out = json.loads(result.stdout)
    assert out["ok"] is True
    assert out["command"] == "analyze.cross"
    assert out["data"]["analysis"] == "cross"
    assert any("[warning][XD-001]" in w for w in out["warnings"])


def test_analyze_cross_missing_pcb(monkeypatch, tmp_path: Path) -> None:
    """A schematic-only project → clean not_found, not a deep analyzer crash."""
    (tmp_path / "demo.kicad_pro").write_text("{}")
    (tmp_path / "demo.kicad_sch").write_text("(kicad_sch)")
    _stub_analyzer(monkeypatch, {"findings": []})
    _stub_argv(monkeypatch, {"unreachable": True})
    result = CliRunner().invoke(_cross_app, [str(tmp_path), "--json"])
    assert result.exit_code == 1
    out = json.loads(result.stdout)
    assert out["error"]["code"] == "not_found"
    assert "PCB" in out["error"]["message"]


def test_analyze_thermal_envelope(monkeypatch, proj_dir: Path, tmp_path: Path) -> None:
    _stub_analyzer(monkeypatch, {"findings": []})
    _stub_argv(monkeypatch, {"analysis": "thermal", "findings": []})
    result = CliRunner().invoke(
        _thermal_app,
        [str(proj_dir), "--ambient", "40", "--out", str(tmp_path / "o.json"), "--json"],
    )
    assert result.exit_code == 0, result.stdout
    out = json.loads(result.stdout)
    assert out["command"] == "analyze.thermal"
    assert out["data"]["analysis"] == "thermal"


def test_analyze_fab_gate_envelope(monkeypatch, proj_dir: Path, tmp_path: Path) -> None:
    _stub_analyzer(monkeypatch, {"findings": []})
    _stub_argv(monkeypatch, {"gate": "pass", "findings": []})
    result = CliRunner().invoke(
        _fab_gate_app,
        [str(proj_dir), "--strict", "--out", str(tmp_path / "o.json"), "--json"],
    )
    assert result.exit_code == 0, result.stdout
    out = json.loads(result.stdout)
    assert out["command"] == "analyze.fab-gate"
    assert out["data"]["gate"] == "pass"


# ---------------------------------------------------------------------------
# analyze whatif / lifecycle (derived from sch analyzer JSON)
# ---------------------------------------------------------------------------

def test_analyze_whatif_requires_changes(proj_dir: Path) -> None:
    """No changes and no --suggest-fixes → bad_args before any analyzer runs."""
    result = CliRunner().invoke(_whatif_app, [str(proj_dir), "--json"])
    assert result.exit_code == 1
    out = json.loads(result.stdout)
    assert out["error"]["code"] == "bad_args"


def test_analyze_whatif_envelope(monkeypatch, proj_dir: Path, tmp_path: Path) -> None:
    _stub_analyzer(monkeypatch, {"findings": []})
    _stub_argv(monkeypatch, {"analysis": "whatif", "findings": []})
    result = CliRunner().invoke(
        _whatif_app,
        [str(proj_dir), "R1=10k", "--out", str(tmp_path / "o.json"), "--json"],
    )
    assert result.exit_code == 0, result.stdout
    out = json.loads(result.stdout)
    assert out["command"] == "analyze.whatif"
    assert out["data"]["analysis"] == "whatif"


def test_analyze_lifecycle_envelope(monkeypatch, proj_dir: Path, tmp_path: Path) -> None:
    _stub_analyzer(monkeypatch, {"findings": []})
    _stub_argv(monkeypatch, {"analysis": "lifecycle", "findings": []})
    result = CliRunner().invoke(
        _lifecycle_app, [str(proj_dir), "--out", str(tmp_path / "o.json"), "--json"]
    )
    assert result.exit_code == 0, result.stdout
    out = json.loads(result.stdout)
    assert out["command"] == "analyze.lifecycle"
    assert out["data"]["analysis"] == "lifecycle"


# ---------------------------------------------------------------------------
# analyze diff (two analyzer JSON files in)
# ---------------------------------------------------------------------------

def test_analyze_diff_envelope(monkeypatch, tmp_path: Path) -> None:
    base = tmp_path / "base.json"
    base.write_text("{}")
    head = tmp_path / "head.json"
    head.write_text("{}")
    _stub_argv(monkeypatch, {"analysis": "diff", "findings": []})
    result = CliRunner().invoke(
        _diff_app, [str(base), str(head), "--out", str(tmp_path / "o.json"), "--json"]
    )
    assert result.exit_code == 0, result.stdout
    out = json.loads(result.stdout)
    assert out["command"] == "analyze.diff"
    assert out["data"]["analysis"] == "diff"


def test_analyze_diff_missing_file(monkeypatch, tmp_path: Path) -> None:
    """A nonexistent input file → error.code='not_found'."""
    base = tmp_path / "base.json"
    base.write_text("{}")
    _stub_argv(monkeypatch, {"unreachable": True})
    result = CliRunner().invoke(
        _diff_app, [str(base), str(tmp_path / "nope.json"), "--json"]
    )
    assert result.exit_code == 1
    out = json.loads(result.stdout)
    assert out["error"]["code"] == "not_found"
