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


@net_app.command("of")
def net_of(
    project: str = typer.Argument(
        None,
        help="Project path. Omit to auto-detect from the board open in KiCad.",
    ),
    net: str = typer.Option(..., "--net", help="Net name to inspect"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """List everything on a net on the PCB — pads, tracks, vias, zones.

    Answers "what is on net X" for the board. Requires KiCad open with the
    .kicad_pcb; for the schematic-side answer use `kcd net trace`.
    """
    with run_command("net.of", json_) as r:
        proj = resolve_or_active(project)
        from kcd.adapters import kipy_pcb
        r.data = {
            "project": proj.name,
            **kipy_pcb.net_members(net),
        }


@net_app.command("trace")
def trace(
    project: str = typer.Argument(...),
    net: str = typer.Option(..., "--net", help="Net name to trace"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Trace a net through the schematic — the component pins on it.

    Resolves label and global-label nets to the actual symbol pins via
    kicad-skip's wire-graph connectivity. For the PCB-side membership of a
    net — and for power nets — use `kcd net of`.
    """
    with run_command("net.trace", json_) as r:
        proj = resolve(project)
        result = skip_sch.trace_net(proj.sch, net)
        r.data = result
        r.warn(
            "net.trace covers the root sheet's label and global-label nets; "
            "hierarchical sub-sheets and unnamed/auto-named nets are not traced."
        )
        if not result["found"]:
            r.warn(
                f"Net {net!r} not found on the root sheet — if it's a PCB "
                f"net, run `kcd net of --net {net}` with KiCad open."
            )
        elif "power" in result["kind"]:
            r.warn(
                f"{net!r} is a power net: the declaring power symbols are "
                "listed, but component pins can't be traced through them "
                "(kicad-skip single-pin limitation) — use `kcd net of`."
            )
