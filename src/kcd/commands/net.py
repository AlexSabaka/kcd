"""`kcd net` subcommands — net tracing and connectivity queries."""

from __future__ import annotations

import typer

from kcd.adapters import skip_sch
from kcd.core.ipc import IpcUnavailable
from kcd.core.output import Result, emit
from kcd.core.project import resolve

net_app = typer.Typer(help="Net tracing and connectivity queries.")


@net_app.command("list")
def list_nets(
    project: str = typer.Argument(...),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """List all named nets (labels, global labels, power) in the schematic."""
    proj = resolve(project)
    r = Result(command="net.list")
    r.data = {
        "project": proj.name,
        "nets": skip_sch.list_nets(proj.sch),
    }
    emit(r, json_)


@net_app.command("pcb")
def pcb_nets(
    project: str = typer.Argument(...),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """List nets present on the PCB (requires KiCad open with .kicad_pcb)."""
    proj = resolve(project)
    r = Result(command="net.pcb")
    try:
        from kcd.adapters import kipy_pcb
        r.data = {
            "project": proj.name,
            "nets": kipy_pcb.list_nets(),
        }
    except IpcUnavailable as e:
        r.fail("ipc_unavailable", str(e))
    emit(r, json_)


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
    proj = resolve(project)
    r = Result(command="net.trace")
    r.warn(
        "net.trace is a v1 stub — only direct label-attached pins are detected. "
        "For full connectivity, also check `kcd net pcb` if board is open."
    )
    # In v1, we just confirm the net exists in the label set.
    nets = skip_sch.list_nets(proj.sch)
    matches = [n for n in nets if n["name"] == net]
    r.data = {"net": net, "found_in_schematic": bool(matches), "labels": matches}
    emit(r, json_)
