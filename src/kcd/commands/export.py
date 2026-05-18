"""`kcd export` subcommands — Gerber, drill, BOM, STEP, pick-and-place."""

from __future__ import annotations

from pathlib import Path

import typer

from kcd.adapters import kicad_cli
from kcd.core import config as cfg_mod
from kcd.core.output import Result, emit
from kcd.core.project import resolve

export_app = typer.Typer(help="Manufacturing file exports.")


@export_app.command("gerber")
def gerber(
    project: str = typer.Argument(...),
    out: Path = typer.Option(..., "-o", "--out", help="Output directory"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Export Gerber files."""
    cfg = cfg_mod.load()
    proj = resolve(project)
    r = Result(command="export.gerber")
    try:
        kicad_cli.export_gerber(cfg.kicad_cli, proj.pcb, out)
    except kicad_cli.CliError as e:
        r.fail("export_failed", str(e))
        emit(r, json_)
        return
    r.add_artifact("gerber_dir", str(out))
    r.data = {"project": proj.name, "out_dir": str(out)}
    emit(r, json_)


@export_app.command("drill")
def drill(
    project: str = typer.Argument(...),
    out: Path = typer.Option(..., "-o", "--out"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Export drill files."""
    cfg = cfg_mod.load()
    proj = resolve(project)
    r = Result(command="export.drill")
    try:
        kicad_cli.export_drill(cfg.kicad_cli, proj.pcb, out)
    except kicad_cli.CliError as e:
        r.fail("export_failed", str(e))
        emit(r, json_)
        return
    r.add_artifact("drill_dir", str(out))
    r.data = {"project": proj.name, "out_dir": str(out)}
    emit(r, json_)


@export_app.command("bom")
def bom(
    project: str = typer.Argument(...),
    out: Path = typer.Option(..., "-o", "--out", help="Output CSV path"),
    grouped: bool = typer.Option(True, "--grouped/--flat", help="Group by Value+Footprint"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Export BOM as CSV."""
    cfg = cfg_mod.load()
    proj = resolve(project)
    r = Result(command="export.bom")
    try:
        kicad_cli.export_sch_bom(cfg.kicad_cli, proj.sch, out, grouped=grouped)
    except kicad_cli.CliError as e:
        r.fail("export_failed", str(e))
        emit(r, json_)
        return
    r.add_artifact("bom_csv", str(out), grouped=grouped)
    r.data = {"project": proj.name}
    emit(r, json_)


@export_app.command("step")
def step(
    project: str = typer.Argument(...),
    out: Path = typer.Option(..., "-o", "--out"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Export 3D STEP model of the board."""
    cfg = cfg_mod.load()
    proj = resolve(project)
    r = Result(command="export.step")
    try:
        kicad_cli.export_step(cfg.kicad_cli, proj.pcb, out)
    except kicad_cli.CliError as e:
        r.fail("export_failed", str(e))
        emit(r, json_)
        return
    r.add_artifact("step", str(out))
    r.data = {"project": proj.name}
    emit(r, json_)


@export_app.command("pos")
def pos(
    project: str = typer.Argument(...),
    out: Path = typer.Option(..., "-o", "--out"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Export pick-and-place position file."""
    cfg = cfg_mod.load()
    proj = resolve(project)
    r = Result(command="export.pos")
    try:
        kicad_cli.export_pos(cfg.kicad_cli, proj.pcb, out)
    except kicad_cli.CliError as e:
        r.fail("export_failed", str(e))
        emit(r, json_)
        return
    r.add_artifact("pos", str(out))
    r.data = {"project": proj.name}
    emit(r, json_)


@export_app.command("pdf")
def pdf(
    project: str = typer.Argument(...),
    out: Path = typer.Option(..., "-o", "--out"),
    target: str = typer.Option("sch", "--target", help="sch | pcb"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Export schematic or PCB as PDF."""
    cfg = cfg_mod.load()
    proj = resolve(project)
    r = Result(command="export.pdf")
    try:
        if target == "sch":
            kicad_cli.export_sch_pdf(cfg.kicad_cli, proj.sch, out)
            r.add_artifact("sch_pdf", str(out))
        else:
            kicad_cli.export_pcb_pdf(cfg.kicad_cli, proj.pcb, out)
            r.add_artifact("pcb_pdf", str(out))
    except kicad_cli.CliError as e:
        r.fail("export_failed", str(e))
        emit(r, json_)
        return
    r.data = {"project": proj.name, "target": target}
    emit(r, json_)
