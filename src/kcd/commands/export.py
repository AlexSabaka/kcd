"""`kcd export` subcommands — Gerber, drill, BOM, STEP, pick-and-place."""

from __future__ import annotations

from pathlib import Path

import typer

from kcd.adapters import kicad_cli
from kcd.core import config as cfg_mod
from kcd.core.output import CommandError, run_command
from kcd.core.project import resolve

export_app = typer.Typer(help="Manufacturing file exports.")


@export_app.command("gerber")
def gerber(
    project: str = typer.Argument(...),
    out: Path = typer.Option(..., "-o", "--out", help="Output directory"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Export a complete fab package — Gerber layers plus drill files.

    Drill files go into the same directory: a fab house rejects a gerber set
    with no drills, so `export gerber` ships the whole package. Use the
    standalone `export drill` only when you want drills on their own.
    """
    with run_command("export.gerber", json_) as r:
        cfg = cfg_mod.load()
        proj = resolve(project)
        kicad_cli.export_gerber(cfg.kicad_cli, proj.pcb, out)
        kicad_cli.export_drill(cfg.kicad_cli, proj.pcb, out)
        r.add_artifact("gerber_dir", str(out))
        r.data = {"project": proj.name, "out_dir": str(out), "drill_included": True}


@export_app.command("drill")
def drill(
    project: str = typer.Argument(...),
    out: Path = typer.Option(..., "-o", "--out"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Export drill files."""
    with run_command("export.drill", json_) as r:
        cfg = cfg_mod.load()
        proj = resolve(project)
        kicad_cli.export_drill(cfg.kicad_cli, proj.pcb, out)
        r.add_artifact("drill_dir", str(out))
        r.data = {"project": proj.name, "out_dir": str(out)}


@export_app.command("bom")
def bom(
    project: str = typer.Argument(...),
    out: Path = typer.Option(..., "-o", "--out", help="Output CSV path"),
    grouped: bool = typer.Option(True, "--grouped/--flat", help="Group by Value+Footprint"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Export BOM as CSV."""
    with run_command("export.bom", json_) as r:
        cfg = cfg_mod.load()
        proj = resolve(project)
        kicad_cli.export_sch_bom(cfg.kicad_cli, proj.sch, out, grouped=grouped)
        r.add_artifact("bom_csv", str(out), grouped=grouped)
        r.data = {"project": proj.name}


@export_app.command("step")
def step(
    project: str = typer.Argument(...),
    out: Path = typer.Option(..., "-o", "--out"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Export 3D STEP model of the board."""
    with run_command("export.step", json_) as r:
        cfg = cfg_mod.load()
        proj = resolve(project)
        kicad_cli.export_step(cfg.kicad_cli, proj.pcb, out)
        r.add_artifact("step", str(out))
        r.data = {"project": proj.name}


@export_app.command("pos")
def pos(
    project: str = typer.Argument(...),
    out: Path = typer.Option(..., "-o", "--out"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Export pick-and-place position file."""
    with run_command("export.pos", json_) as r:
        cfg = cfg_mod.load()
        proj = resolve(project)
        kicad_cli.export_pos(cfg.kicad_cli, proj.pcb, out)
        r.add_artifact("pos", str(out))
        r.data = {"project": proj.name}


@export_app.command("pdf")
def pdf(
    project: str = typer.Argument(...),
    out: Path = typer.Option(..., "-o", "--out"),
    target: str = typer.Option("sch", "--target", help="sch | pcb"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Export schematic or PCB as PDF."""
    with run_command("export.pdf", json_) as r:
        cfg = cfg_mod.load()
        proj = resolve(project)
        if target == "sch":
            kicad_cli.export_sch_pdf(cfg.kicad_cli, proj.sch, out)
            r.add_artifact("sch_pdf", str(out))
        elif target == "pcb":
            kicad_cli.export_pcb_pdf(cfg.kicad_cli, proj.pcb, out)
            r.add_artifact("pcb_pdf", str(out))
        else:
            raise CommandError("invalid_target", f"target must be 'sch' or 'pcb', got {target!r}")
        r.data = {"project": proj.name, "target": target}
