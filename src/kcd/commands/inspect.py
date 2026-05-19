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
    """List all symbols across every sheet of the schematic.

    Each symbol carries a `sheet` field with its home sheet's display name —
    `"root"` for page 1, or the `.kicad_pro` sheet name for sub-sheets. Was
    previously root-sheet-only; hierarchical designs lost everything below.
    """
    with run_command("inspect.sch", json_) as r:
        proj = resolve(project)
        r.data = {
            "project": proj.name,
            "symbols": skip_sch.list_symbols_all(proj),
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


def _check_consistency(sch_info: dict, pcb_info: dict | None) -> dict:
    """Compare schematic and PCB views of the same reference.

    Schematic has `value` + `footprint` (lib:fp form). PCB has `value` +
    `library_id` (also lib:fp form, populated by KiCad on PCB import).
    KiCad's `Update PCB from Schematic` is a *manual* step, so the two can
    drift; an agent looking at both sides without a divergence flag will
    silently treat them as equivalent and reason wrong. This block makes
    that drift loud.

    Returns a dict that is *always* present in the payload — the
    `pcb_available` field tells the agent whether comparison was possible.
    """
    if pcb_info is None:
        return {
            "pcb_available": False,
            "notes": [
                "PCB info unavailable (KiCad not open with PCB, or footprint "
                "missing from board) — schematic↔PCB consistency not checked."
            ],
        }
    value_matches = sch_info.get("value") == pcb_info.get("value")
    fp_matches = sch_info.get("footprint") == pcb_info.get("library_id")
    notes: list[str] = []
    if not value_matches:
        notes.append(
            f"value differs: schematic={sch_info.get('value')!r} vs "
            f"PCB={pcb_info.get('value')!r}. Run 'Update PCB from Schematic' "
            "in KiCad to sync."
        )
    if not fp_matches:
        notes.append(
            f"footprint differs: schematic={sch_info.get('footprint')!r} vs "
            f"PCB={pcb_info.get('library_id')!r}."
        )
    return {
        "pcb_available": True,
        "value_matches": value_matches,
        "footprint_matches": fp_matches,
        "notes": notes,
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
        sheet_path, sheet_name = skip_sch.locate(proj, reference)
        sch_info = skip_sch.find_symbol(sheet_path, reference)
        sch_info["sheet"] = sheet_name
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

        consistency = _check_consistency(sch_info, payload["pcb"])
        payload["consistency"] = consistency
        # Mirror divergence notes into envelope `warnings` so clients that
        # don't unpack `data.consistency.notes` still see them.
        for note in consistency.get("notes", []):
            if consistency.get("pcb_available"):  # don't double-warn for "PCB unavailable"
                r.warn(f"sch↔pcb: {note}")

        r.data = payload
