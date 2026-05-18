"""`kcd inspect` subcommands — read-only views of the design."""

from __future__ import annotations

import typer

from kcd.adapters import skip_sch
from kcd.core.ipc import IpcUnavailable
from kcd.core.output import Result, emit
from kcd.core.project import resolve

inspect_app = typer.Typer(help="Read-only inspection of schematic and PCB.")


@inspect_app.command("sch")
def sch(
    project: str = typer.Argument(...),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """List all symbols in the schematic with reference, value, and footprint."""
    proj = resolve(project)
    r = Result(command="inspect.sch")
    try:
        r.data = {
            "project": proj.name,
            "symbols": skip_sch.list_symbols(proj.sch),
        }
    except skip_sch.SchEditError as e:
        r.fail("inspect_failed", str(e))
    emit(r, json_)


@inspect_app.command("pcb")
def pcb(
    project: str = typer.Argument(...),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """List all footprints on the PCB. Requires KiCad to be open with the .kicad_pcb file."""
    proj = resolve(project)
    r = Result(command="inspect.pcb")
    try:
        from kcd.adapters import kipy_pcb
        r.data = {
            "project": proj.name,
            "footprints": kipy_pcb.list_footprints(),
        }
    except IpcUnavailable as e:
        r.fail("ipc_unavailable", str(e))
    emit(r, json_)


@inspect_app.command("ref")
def ref(
    project: str = typer.Argument(...),
    reference: str = typer.Argument(..., help="Reference designator, e.g. R5"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Look up a component by reference designator. Reads from schematic;
    enriches with PCB info if KiCad is open."""
    proj = resolve(project)
    r = Result(command="inspect.ref")
    try:
        sch_info = skip_sch.find_symbol(proj.sch, reference)
    except skip_sch.SchEditError as e:
        r.fail("not_found", str(e))
        emit(r, json_)
        return

    payload: dict = {"reference": reference, "schematic": sch_info}

    # Try to enrich with live PCB info, but degrade gracefully.
    try:
        from kcd.adapters import kipy_pcb
        try:
            payload["pcb"] = kipy_pcb.find_footprint(reference)
        except LookupError:
            payload["pcb"] = None
            r.warn(f"No footprint named {reference!r} on the PCB (yet?)")
    except IpcUnavailable:
        payload["pcb"] = None
        r.warn(
            "KiCad not running with PCB open; PCB info unavailable. "
            "Open the .kicad_pcb file to enrich this query."
        )

    r.data = payload
    emit(r, json_)
