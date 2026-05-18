"""`kcd render` subcommands."""

from __future__ import annotations

from pathlib import Path

import typer

from kcd.adapters import kicad_cli
from kcd.core import config as cfg_mod
from kcd.core.output import Result, emit
from kcd.core.project import resolve

render_app = typer.Typer(help="Render schematics and PCBs so the agent can SEE them.")


@render_app.command("sch")
def sch(
    project: str = typer.Argument(...),
    out: Path = typer.Option(..., "-o", "--out", help="Output path (file or dir)"),
    format_: str = typer.Option("svg", "-f", "--format", help="svg | pdf | png"),
    dpi: int = typer.Option(300, "--dpi", help="DPI for PNG rasterization"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Render the schematic. Output goes to a directory for SVG (one file per sheet),
    or a single file for PDF/PNG."""
    cfg = cfg_mod.load()
    proj = resolve(project)
    r = Result(command="render.sch")

    fmt = format_.lower()
    if fmt == "svg":
        out_dir = out if out.is_dir() or not out.suffix else out.parent
        kicad_cli.export_sch_svg(cfg.kicad_cli, proj.sch, out_dir)
        for svg in sorted(out_dir.glob("*.svg")):
            r.add_artifact("schematic_svg", str(svg))
    elif fmt == "pdf":
        kicad_cli.export_sch_pdf(cfg.kicad_cli, proj.sch, out)
        r.add_artifact("schematic_pdf", str(out))
    elif fmt == "png":
        kicad_cli.export_sch_png(cfg.kicad_cli, proj.sch, out, dpi=dpi)
        r.add_artifact("schematic_png", str(out), dpi=dpi)
    else:
        r.fail("invalid_format", f"Unknown format {format_!r}; use svg, pdf, or png")
        emit(r, json_)
        return

    r.data = {"project": proj.name, "format": fmt}
    emit(r, json_)


@render_app.command("pcb")
def pcb(
    project: str = typer.Argument(...),
    out: Path = typer.Option(..., "-o", "--out"),
    format_: str = typer.Option("svg", "-f", "--format", help="svg | pdf"),
    layers: str = typer.Option(
        "F.Cu,B.Cu,F.SilkS,B.SilkS,Edge.Cuts",
        "--layers",
        help="Comma-separated layer names",
    ),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Render PCB layers to SVG or PDF."""
    cfg = cfg_mod.load()
    proj = resolve(project)
    r = Result(command="render.pcb")

    layer_list = [s.strip() for s in layers.split(",") if s.strip()]
    fmt = format_.lower()
    if fmt == "svg":
        kicad_cli.export_pcb_svg(cfg.kicad_cli, proj.pcb, out, layers=layer_list)
        r.add_artifact("pcb_svg", str(out), layers=layer_list)
    elif fmt == "pdf":
        kicad_cli.export_pcb_pdf(cfg.kicad_cli, proj.pcb, out, layers=layer_list)
        r.add_artifact("pcb_pdf", str(out), layers=layer_list)
    else:
        r.fail("invalid_format", f"Unknown format {format_!r}; use svg or pdf")
        emit(r, json_)
        return

    r.data = {"project": proj.name, "format": fmt, "layers": layer_list}
    emit(r, json_)


@render_app.command("3d")
def three_d(
    project: str = typer.Argument(...),
    out: Path = typer.Option(..., "-o", "--out"),
    side: str = typer.Option("top", "--side", help="top | bottom | front | back | left | right"),
    quality: str = typer.Option("high", "--quality", help="basic | high | user"),
    background: str = typer.Option("default", "--background"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Render a photorealistic 3D image of the PCB."""
    cfg = cfg_mod.load()
    proj = resolve(project)
    r = Result(command="render.3d")
    kicad_cli.render_pcb_png(
        cfg.kicad_cli, proj.pcb, out, side=side, background=background, quality=quality
    )
    r.add_artifact("pcb_render", str(out), side=side, quality=quality)
    r.data = {"project": proj.name, "side": side}
    emit(r, json_)
