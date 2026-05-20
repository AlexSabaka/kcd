"""`kcd inspect` subcommands — read-only views of the design."""

from __future__ import annotations

import re

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


def _part_family(text: str | None) -> str | None:
    """The 'letters then digits' core of a part number — its stable family.

    `"AP2112K-3.3"` -> `"ap2112"`, `"NCP1117-3.3_SOT223"` -> `"ncp1117"`.
    Returns None for anything not part-number-shaped (`"10k"`, `"100nF"`,
    `"1N4148"` — digit-leading), so passives never trip the coherence check.
    """
    m = re.match(r"\s*([A-Za-z]{2,}\d{2,})", text or "")
    return m.group(1).lower() if m else None


def _check_part_identity_coherence(sch_info: dict) -> dict:
    """Flag a component whose value, symbol, and datasheet disagree.

    `_check_consistency` only compares schematic vs PCB. This catches a
    *single-side* contradiction — e.g. value "AP2112K-3.3" on a symbol whose
    lib_id is "NCP1117-3.3_SOT223" with an NCP1117 datasheet (Round-3 B8).

    Deliberately conservative: it fires only when the value AND the symbol
    name both carry a real part-number family and those families differ — so
    a generic `Device:` symbol or a passive never produces a false positive.
    """
    value = sch_info.get("value") or ""
    lib_id = sch_info.get("lib_id") or ""
    datasheet = (sch_info.get("datasheet") or "").lower()
    symbol_name = lib_id.split(":")[-1]

    value_family = _part_family(value)
    symbol_family = _part_family(symbol_name)
    issues: list[str] = []

    if value_family and symbol_family and value_family != symbol_family:
        issues.append(
            f"value {value!r} (family {value_family}) does not match the "
            f"symbol {symbol_name!r} (family {symbol_family}) — the placed "
            "part may be mislabeled or the wrong symbol"
        )
        # Datasheet corroboration: if it names the symbol's family but not
        # the value's, the value is the odd one out.
        if (datasheet and symbol_family in datasheet
                and value_family not in datasheet):
            issues.append(
                f"datasheet corroborates the symbol family ({symbol_family}), "
                f"not the value family ({value_family})"
            )

    return {"coherent": not issues, "issues": issues}


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
        consistency["part_identity"] = _check_part_identity_coherence(sch_info)
        payload["consistency"] = consistency
        # Mirror divergence notes into envelope `warnings` so clients that
        # don't unpack `data.consistency.notes` still see them.
        for note in consistency.get("notes", []):
            if consistency.get("pcb_available"):  # don't double-warn for "PCB unavailable"
                r.warn(f"sch↔pcb: {note}")
        for issue in consistency["part_identity"]["issues"]:
            r.warn(f"part-identity: {issue}")

        r.data = payload
