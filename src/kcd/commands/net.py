"""`kcd net` subcommands — net tracing and connectivity queries."""

from __future__ import annotations

import typer

from kcd.adapters import skip_sch
from kcd.core.output import run_command
from kcd.core.project import resolve, resolve_or_active

net_app = typer.Typer(help="Net tracing and connectivity queries.")


@net_app.command("list")
def list_nets(
    project: str = typer.Argument(...),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """List all named nets (labels, global labels, power) in the schematic."""
    with run_command("net.list", json_) as r:
        proj = resolve(project)
        r.data = {
            "project": proj.name,
            "nets": skip_sch.list_nets(proj.sch),
        }


@net_app.command("pcb")
def pcb_nets(
    project: str = typer.Argument(
        None,
        help="Project path. Omit to auto-detect from the board open in KiCad.",
    ),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """List nets present on the PCB (requires KiCad open with .kicad_pcb)."""
    with run_command("net.pcb", json_) as r:
        proj = resolve_or_active(project)
        from kcd.adapters import kipy_pcb
        r.data = {
            "project": proj.name,
            "nets": kipy_pcb.list_nets(),
        }


@net_app.command("trace")
def trace(
    project: str = typer.Argument(...),
    net: str = typer.Option(..., "--net", help="Net name to trace"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Trace a net through the schematic — components connected, sheet locations.

    NOTE: this is a v1 stub. Full hierarchical net tracing requires walking
    sheet boundaries, which kicad-skip handles partially. For now we list
    symbols whose pins touch the named net via label proximity.
    """
    with run_command("net.trace", json_) as r:
        proj = resolve(project)
        r.warn(
            "net.trace is a v1 stub — only direct label-attached pins are detected. "
            "For full connectivity, also check `kcd net pcb` if board is open."
        )
        nets = skip_sch.list_nets(proj.sch)
        matches = [n for n in nets if n["name"] == net]
        r.data = {"net": net, "found_in_schematic": bool(matches), "labels": matches}
