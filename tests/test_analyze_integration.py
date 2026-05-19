"""Integration tests for `kcd analyze` — runs the real vendored analyzers.

Gated on `KCD_INTEGRATION=1` because the analyzers need a real `.kicad_sch`
or `.kicad_pcb` to consume. The fixture is KiCad's bundled `pic_programmer`
demo at `$KCD_TEST_PIC_PROGRAMMER` (defaults to
`/Volumes/2TB/_electronics/demos/pic_programmer`).

Skip rules:
- `KCD_INTEGRATION` env var not set → skip the whole module.
- Demo project doesn't exist on disk → individual tests skip with a clear
  reason rather than fail (different machines have different demo locations).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from kcd.commands.analyze import (
    analyze_pcb_cmd,
    analyze_sch_cmd,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("KCD_INTEGRATION") != "1",
    reason="Set KCD_INTEGRATION=1 to enable (runs vendored analyzers).",
)


def _pic_programmer_dir() -> Path:
    """Locate the pic_programmer demo project."""
    return Path(
        os.environ.get(
            "KCD_TEST_PIC_PROGRAMMER",
            "/Volumes/2TB/_electronics/demos/pic_programmer",
        )
    )


_sch_app = typer.Typer()
_sch_app.command()(analyze_sch_cmd)
_pcb_app = typer.Typer()
_pcb_app.command()(analyze_pcb_cmd)


def test_analyze_sch_e2e_pic_programmer(tmp_path: Path) -> None:
    """End-to-end: real analyze_schematic.py on a real KiCad 10 project.

    Confirms the subprocess plumbing works against a non-trivial input
    (66 components, 2 sheets, LT1373 regulator). Assertions are
    deliberately broad — exact key sets evolve with kicad-happy.
    """
    proj = _pic_programmer_dir()
    if not (proj / "pic_programmer.kicad_sch").is_file():
        pytest.skip(f"pic_programmer demo not found at {proj}")
    runner = CliRunner()
    result = runner.invoke(
        _sch_app,
        [str(proj), "--out", str(tmp_path / "out.json"), "--json"],
    )
    assert result.exit_code == 0, result.stdout
    out = json.loads(result.stdout)
    assert out["ok"] is True
    assert out["command"] == "analyze.sch"
    # Sanity-check the shape — analyzer should at least produce these top-levels.
    data = out["data"]
    assert "components" in data
    assert "findings" in data
    assert isinstance(data["findings"], list)
    # pic_programmer specifics: ≥ 50 components, multi-sheet, LT1373 present.
    assert len(data["components"]) >= 50
    comps = data["components"]
    refs_with_lt = [c for c in comps if "LT" in str(c.get("value", ""))]
    assert refs_with_lt, "expected LT1373 in pic_programmer components"


def test_analyze_pcb_e2e_pic_programmer(tmp_path: Path) -> None:
    """End-to-end: real analyze_pcb.py on a real KiCad 10 PCB."""
    proj = _pic_programmer_dir()
    if not (proj / "pic_programmer.kicad_pcb").is_file():
        pytest.skip(f"pic_programmer demo not found at {proj}")
    runner = CliRunner()
    result = runner.invoke(
        _pcb_app,
        [str(proj), "--out", str(tmp_path / "out.json"), "--json"],
    )
    assert result.exit_code == 0, result.stdout
    out = json.loads(result.stdout)
    assert out["ok"] is True
    assert out["command"] == "analyze.pcb"
    data = out["data"]
    assert "footprints" in data
    # pic_programmer has 63 footprints.
    assert len(data["footprints"]) >= 50
    assert data.get("kicad_version") == "10.0"
