"""`kcd drc` and `kcd erc` — design rule and electrical rule checking."""

from __future__ import annotations

from pathlib import Path

import typer

from kcd.adapters import kicad_cli
from kcd.core import config as cfg_mod
from kcd.core.output import Result, emit
from kcd.core.project import resolve


def drc_cmd(
    project: str = typer.Argument(...),
    report: Path = typer.Option(
        None, "-o", "--out", help="Path for DRC report JSON (default: tempfile)"
    ),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Run DRC on the PCB and return the report."""
    cfg = cfg_mod.load()
    proj = resolve(project)
    if report is None:
        report = cfg.render_cache_dir / f"{proj.name}-drc.json"
    r = Result(command="drc")
    try:
        report_data = kicad_cli.run_drc(cfg.kicad_cli, proj.pcb, report)
    except kicad_cli.CliError as e:
        r.fail("drc_failed", str(e))
        emit(r, json_)
        return
    violations = report_data.get("violations", []) or []
    unconnected = report_data.get("unconnected_items", []) or []
    schematic_parity = report_data.get("schematic_parity", []) or []
    r.data = {
        "project": proj.name,
        "violation_count": len(violations),
        "unconnected_count": len(unconnected),
        "parity_issues": len(schematic_parity),
        "violations": violations,
        "unconnected_items": unconnected,
        "schematic_parity": schematic_parity,
    }
    r.add_artifact("drc_report", str(report))
    if violations or unconnected:
        r.warn(
            f"{len(violations)} violations, {len(unconnected)} unconnected items"
        )
    emit(r, json_)


def erc_cmd(
    project: str = typer.Argument(...),
    report: Path = typer.Option(None, "-o", "--out"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Run ERC on the schematic and return the report."""
    cfg = cfg_mod.load()
    proj = resolve(project)
    if report is None:
        report = cfg.render_cache_dir / f"{proj.name}-erc.json"
    r = Result(command="erc")
    try:
        report_data = kicad_cli.run_erc(cfg.kicad_cli, proj.sch, report)
    except kicad_cli.CliError as e:
        r.fail("erc_failed", str(e))
        emit(r, json_)
        return
    violations = report_data.get("violations", []) or []
    sheets = report_data.get("sheets", []) or []
    r.data = {
        "project": proj.name,
        "violation_count": len(violations),
        "sheet_count": len(sheets),
        "violations": violations,
    }
    r.add_artifact("erc_report", str(report))
    if violations:
        r.warn(f"{len(violations)} violations")
    emit(r, json_)
