"""`kcd sync` — schematic -> PCB forward-annotation bridge.

KiCad 10 has no headless "Update PCB from Schematic": kipy exposes no
update-from-schematic call and pcbnew's netlist import is GUI-only. `kcd sync`
therefore can't *push* the schematic onto the board — it does the next best
thing:

  - `kcd sync <proj>` exports the schematic netlist (an artifact) and tells
    the human exactly how to apply it. Works offline — no KiCad needed.
  - `kcd sync <proj> --check` additionally diffs that netlist against the live
    PCB and reports the drift: components the schematic has that the board
    doesn't (and vice versa), plus pins whose net assignment differs. Needs
    KiCad open with the .kicad_pcb.

`kcd parity` already catches component-level drift (refs, values, footprint
assignments); `sync --check` adds the piece parity is blind to —
net-membership drift, e.g. a `+12V`->`+BATT` rename that moves no component
but leaves every pad on the old net.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import typer

from kcd.adapters import kicad_cli
from kcd.core import config as cfg_mod
from kcd.core.ipc import IpcUnavailable
from kcd.core.output import run_command
from kcd.core.project import resolve

# F8 is the modern, correct path; the exported netlist also supports the
# legacy pcbnew File -> Import Netlist route.
_PUSH_HINT = (
    "To push the schematic to the PCB, open the .kicad_pcb in KiCad and run "
    "Tools -> Update PCB from Schematic (F8). kcd cannot do this headless — "
    "KiCad 10 exposes no API for forward annotation."
)


def sync_cmd(
    project: str = typer.Argument(...),
    check: bool = typer.Option(
        False, "--check", help="Also diff the netlist against the live PCB."
    ),
    out: Path = typer.Option(
        None, "-o", "--out", help="Path for the exported netlist (default: cache)."
    ),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Export the schematic netlist and (with --check) report PCB drift.

    `sync` works offline. `sync --check` needs KiCad open with the .kicad_pcb;
    it degrades to an export-only result with a warning if IPC is unavailable.
    """
    with run_command("sync", json_) as r:
        cfg = cfg_mod.load()
        proj = resolve(project)
        netlist_path = out or cfg.render_cache_dir / f"{proj.name}-netlist.xml"
        kicad_cli.export_sch_netlist(cfg.kicad_cli, proj.sch, netlist_path)
        r.add_artifact("schematic_netlist", str(netlist_path))

        sch_comps, sch_pins = _parse_netlist_xml(netlist_path)
        payload: dict = {
            "project": proj.name,
            "netlist": str(netlist_path),
            "schematic_components": len(sch_comps),
            "schematic_nets": len({n for n in sch_pins.values() if n}),
        }

        if not check:
            payload["mode"] = "export"
            r.data = payload
            r.warn(f"Netlist exported. {_PUSH_HINT}")
            return

        payload["mode"] = "check"
        try:
            from kcd.adapters import kipy_pcb
            # Verify KiCad has *this* board open before trusting its data.
            kipy_pcb.assert_board_is(proj.pcb)
            pcb_fps = kipy_pcb.list_footprints()
            pcb_pad_list = kipy_pcb.list_pad_nets()
        except IpcUnavailable:
            r.warn(
                "KiCad not running with the PCB open; sync --check needs the "
                "live board to detect drift. Open the .kicad_pcb and retry. "
                "The netlist was exported anyway — see the artifact."
            )
            payload["pcb_available"] = False
            r.data = payload
            return

        pcb_comps = {fp["reference"] for fp in pcb_fps if fp.get("reference")}
        pcb_pins = {
            (p["footprint"], str(p["pad"])): _normalize_net(p.get("net"))
            for p in pcb_pad_list
        }
        drift = _compute_drift(sch_comps, sch_pins, pcb_comps, pcb_pins)
        payload["pcb_available"] = True
        payload.update(drift)
        r.data = payload

        if not drift["in_sync"]:
            r.warn(
                "PCB is out of sync with the schematic: "
                f"{len(drift['components_added'])} component(s) to add, "
                f"{len(drift['components_removed'])} to remove, "
                f"{len(drift['net_changes'])} net change(s). {_PUSH_HINT}"
            )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize_net(name: str | None) -> str | None:
    """Collapse 'no real net' forms to None.

    KiCad gives floating pins bookkeeping net names (`unconnected-(R1-Pad1)`),
    and a PCB pad with no net comes through as "". Neither is a real net —
    map both to None so an unconnected pin never reads as drift against
    another unconnected pin.
    """
    if not name or name.startswith("unconnected-"):
        return None
    return name


def _parse_netlist_xml(
    path: Path,
) -> tuple[set[str], dict[tuple[str, str], str | None]]:
    """Parse a `kicad-cli sch export netlist --format kicadxml` file.

    Returns ``(components, pins)`` — `components` is the set of component
    references, `pins` maps ``(ref, pin)`` to the normalized net name (or
    None for an unconnected pin). Power symbols (`#PWR*`) never appear in a
    KiCad netlist, so they need no special handling here.
    """
    root = ET.parse(path).getroot()
    components: set[str] = {
        ref for comp in root.findall("./components/comp")
        if (ref := comp.get("ref"))
    }
    pins: dict[tuple[str, str], str | None] = {}
    for net in root.findall("./nets/net"):
        net_name = _normalize_net(net.get("name"))
        for node in net.findall("./node"):
            ref = node.get("ref")
            pin = node.get("pin")
            if ref and pin is not None:
                pins[(ref, pin)] = net_name
    return components, pins


def _compute_drift(
    sch_comps: set[str],
    sch_pins: dict[tuple[str, str], str | None],
    pcb_comps: set[str],
    pcb_pins: dict[tuple[str, str], str | None],
) -> dict:
    """Diff schematic intent against PCB state. Pure — no I/O.

    `net_changes` is restricted to pins whose component exists on *both*
    sides; a pin belonging to an added/removed component is component-level
    drift already reported, not a separate net change.
    """
    components_added = sorted(sch_comps - pcb_comps)
    components_removed = sorted(pcb_comps - sch_comps)
    net_changes: list[dict] = []
    for key in sorted(sch_pins.keys() & pcb_pins.keys()):
        ref, pin = key
        if ref not in sch_comps or ref not in pcb_comps:
            continue
        if sch_pins[key] != pcb_pins[key]:
            net_changes.append({
                "reference": ref,
                "pin": pin,
                "schematic": sch_pins[key],
                "pcb": pcb_pins[key],
            })
    return {
        "in_sync": not (components_added or components_removed or net_changes),
        "components_added": components_added,
        "components_removed": components_removed,
        "net_changes": net_changes,
    }
