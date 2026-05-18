"""`kcd inspect` subcommands — read-only views of the design."""

from __future__ import annotations

import typer

from kcd.adapters import skip_sch
from kcd.core.ipc import IpcUnavailable
from kcd.core.output import run_command
from kcd.core.project import resolve, resolve_or_active

inspect_app = typer.Typer(help="Read-only inspection of schematic and PCB.")


@inspect_app.command("sch")
def sch(
    project: str = typer.Argument(...),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """List all symbols in the schematic with reference, value, and footprint."""
    with run_command("inspect.sch", json_) as r:
        proj = resolve(project)
        r.data = {
            "project": proj.name,
            "symbols": skip_sch.list_symbols(proj.sch),
        }


@inspect_app.command("pcb")
def pcb(
    project: str = typer.Argument(
        None,
        help="Project path. Omit to auto-detect from the board open in KiCad.",
    ),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """List all footprints on the PCB. Requires KiCad to be open with the .kicad_pcb file."""
    with run_command("inspect.pcb", json_) as r:
        proj = resolve_or_active(project)
        from kcd.adapters import kipy_pcb
        r.data = {
            "project": proj.name,
            "footprints": kipy_pcb.list_footprints(),
        }


@inspect_app.command("ref")
def ref(
    project: str = typer.Argument(...),
    reference: str = typer.Argument(..., help="Reference designator, e.g. R5"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Look up a component by reference designator. Reads from schematic;
    enriches with PCB info if KiCad is open."""
    with run_command("inspect.ref", json_) as r:
        proj = resolve(project)
        sch_info = skip_sch.find_symbol(proj.sch, reference)
        payload: dict = {"reference": reference, "schematic": sch_info, "pcb": None}

        # Try to enrich with live PCB info, but degrade gracefully — IPC being
        # down is not a failure of this command, just a partial result.
        try:
            from kcd.adapters import kipy_pcb
            try:
                payload["pcb"] = kipy_pcb.find_footprint(reference)
            except LookupError:
                r.warn(f"No footprint named {reference!r} on the PCB (yet?)")
        except IpcUnavailable:
            r.warn(
                "KiCad not running with PCB open; PCB info unavailable. "
                "Open the .kicad_pcb file to enrich this query."
            )

        r.data = payload
