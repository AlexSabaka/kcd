"""`kcd parity` — whole-board schematic↔PCB drift detection.

`inspect ref` already compares one symbol against its PCB-side footprint via
`_check_consistency` in `inspect.py`. `parity` generalizes that to the whole
design: it diffs the full set of schematic symbols against the full set of
PCB footprints and reports four flavors of drift:

- ``schematic_only`` — refs present in the schematic, no footprint placed.
- ``pcb_only``       — refs present on the PCB, no schematic backing
                       (classic legacy-board hazard for the BOM).
- ``value_mismatches`` — refs on both sides whose Value differs.
- ``footprint_mismatches`` — refs on both sides whose schematic Footprint
                             (lib:fp) differs from the PCB's library_id.

Needs KiCad open with the .kicad_pcb file to pull PCB data via kipy. If IPC
is unavailable the command degrades to a schematic-only listing rather than
failing — agents can still see what's on the schematic, just with a warning
that drift can't be detected from the available data.

Foundation for the EE/PCB-review skill Dove flagged in session 4 (#22).
"""

from __future__ import annotations

import typer

from kcd.adapters import skip_sch
from kcd.core.ipc import IpcUnavailable
from kcd.core.output import run_command
from kcd.core.project import resolve


def parity_cmd(
    project: str = typer.Argument(...),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Diff the schematic against the PCB and report references on one side
    only plus value/footprint mismatches on the intersection.

    Requires KiCad open with the .kicad_pcb file for PCB-side data; degrades
    to schematic-only listing with a warning if IPC is unavailable.
    """
    with run_command("parity", json_) as r:
        proj = resolve(project)
        sch_symbols = skip_sch.list_symbols_all(proj)
        sch_by_ref = {s["reference"]: s for s in sch_symbols if s.get("reference")}
        payload: dict = {
            "project": proj.name,
            "pcb_available": False,
            "schematic_only": [],
            "pcb_only": [],
            "value_mismatches": [],
            "footprint_mismatches": [],
        }

        try:
            from kcd.adapters import kipy_pcb
            # Verify KiCad has *this* board open, not a different one, before
            # trusting `list_footprints()` (Dove session-4 #25).
            kipy_pcb.assert_board_is(proj.pcb)
            pcb_fps = kipy_pcb.list_footprints()
        except IpcUnavailable:
            # No PCB available — return a partial result rather than fail.
            # We still list everything on the schematic side so the user gets
            # *some* useful output, and warn loudly that drift can't be
            # detected without KiCad running.
            r.warn(
                "KiCad not running with PCB open; parity check needs both "
                "schematic and PCB to detect drift. Open the .kicad_pcb "
                "file and retry. Returning schematic-only listing."
            )
            payload["schematic_only"] = sorted(sch_by_ref.keys())
            r.data = payload
            return

        pcb_by_ref = {fp["reference"]: fp for fp in pcb_fps if fp.get("reference")}
        sch_refs = set(sch_by_ref)
        pcb_refs = set(pcb_by_ref)
        payload["pcb_available"] = True
        payload["schematic_only"] = sorted(sch_refs - pcb_refs)
        payload["pcb_only"] = sorted(pcb_refs - sch_refs)

        for ref in sorted(sch_refs & pcb_refs):
            sch = sch_by_ref[ref]
            pcb = pcb_by_ref[ref]
            if sch.get("value") != pcb.get("value"):
                payload["value_mismatches"].append({
                    "reference": ref,
                    "schematic": sch.get("value"),
                    "pcb": pcb.get("value"),
                })
            if sch.get("footprint") != pcb.get("library_id"):
                payload["footprint_mismatches"].append({
                    "reference": ref,
                    "schematic": sch.get("footprint"),
                    "pcb": pcb.get("library_id"),
                })

        # Mirror the most important drift into envelope warnings so agents
        # that don't unpack `data` still see them. PCB-only items are the
        # BOM hazard (you'll fab a board with parts that don't appear in
        # any costing/sourcing pass that reads the schematic). Schematic-only
        # items are usually mid-design state — flag them too so a board layout
        # that's missing components shows up before the next routing pass.
        if payload["pcb_only"]:
            r.warn(
                f"PCB has {len(payload['pcb_only'])} footprint(s) with no "
                "schematic backing — BOM hazard. See data.pcb_only."
            )
        if payload["schematic_only"]:
            r.warn(
                f"Schematic has {len(payload['schematic_only'])} symbol(s) "
                "not placed on the PCB. See data.schematic_only."
            )

        r.data = payload
