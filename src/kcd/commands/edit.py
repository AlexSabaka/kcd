"""`kcd edit` subcommands — mutating operations on schematic and PCB.

All edits auto-snapshot before mutating (unless --no-snapshot) and auto-render
after (unless --no-render). The render output lands at:
    <render_cache_dir>/<sheet>.svg
"""

from __future__ import annotations

from pathlib import Path

import typer

from kcd.adapters import kicad_cli, skip_sch, symbol_lib
from kcd.core import config as cfg_mod
from kcd.core.output import CommandError, Result, run_command
from kcd.core.project import Project, resolve, resolve_or_active
from kcd.core.snapshot import SnapshotStore

edit_app = typer.Typer(help="Mutating operations. Auto-snapshot before, auto-render after.")


def _pre_edit(
    project_arg: str | None,
    msg: str,
    no_snapshot: bool,
    auto: bool = False,
) -> tuple[Project, str | None]:
    """Resolve project + take a pre-edit snapshot. Returns (project, snapshot ref or None).

    `auto=True` lets the caller omit `project_arg` and have us derive the
    active project from KiCad's open board (for IPC-only commands).

    Any exception (FileNotFoundError from resolve, subprocess errors from git)
    propagates so the surrounding `run_command` envelope-wraps it.
    """
    cfg = cfg_mod.load()
    proj = resolve_or_active(project_arg) if auto else resolve(project_arg)
    snap_ref: str | None = None
    if cfg.auto_snapshot and not no_snapshot:
        store = SnapshotStore(proj, dir_name=cfg.snapshot_dir_name)
        info = store.create(f"before: {msg}")
        snap_ref = info.ref
    return proj, snap_ref


def _post_edit_sch(
    proj: Project,
    result: Result,
    sheet_mtimes_before: dict[Path, int],
    no_render: bool = False,
) -> None:
    """Auto-render the schematic to the cache dir. Failures degrade to warnings.

    Attribution is filtered two ways:

    - SVG mtime (Dove #12): stale files from prior sessions in the shared
      `/tmp/kcd` cache stay invisible — we only attribute SVGs whose mtime
      bumped during this kicad-cli call.

    - Sheet-of-symbol (Dove #13): we know which `.kicad_sch` files the edit
      *actually* touched (`sheet_mtimes_before` captures their pre-edit
      mtimes). `sheet_index` maps those files to the SVG filenames
      kicad-cli will produce, and we attribute only the renders for the
      modified sheet(s). Today every kcd schematic edit goes through
      `proj.sch` (the root), so this typically resolves to one SVG —
      future multi-sheet editing plugs in for free.

    Note: kicad-cli 10.0.2's `sch export svg --pages` is broken (always
    renders only page 1 even when others are requested), so we render
    everything and filter on the attribution side rather than telling
    kicad-cli which pages to skip. When upstream fixes that, we can also
    pass `--pages` to save render time.
    """
    cfg = cfg_mod.load()
    if not cfg.auto_render or no_render:
        return
    out_dir = cfg.render_cache_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    changed_sheets: set[Path] = set()
    for sch_file in proj.root.glob("*.kicad_sch"):
        try:
            now_ns = sch_file.stat().st_mtime_ns
        except OSError:
            continue
        before_ns = sheet_mtimes_before.get(sch_file)
        if before_ns is None or now_ns > before_ns:
            changed_sheets.add(sch_file)

    # sheet_index can fail (no .kicad_pro, malformed JSON, orphan UUIDs);
    # treat any failure as "attribute every changed SVG" — degrades to
    # Phase-ζ behavior, never worse.
    try:
        index = skip_sch.sheet_index(proj)
    except Exception as e:  # noqa: BLE001
        result.warn(f"sheet_index failed; rendering all changed SVGs: {e}")
        index = []

    relevant_svgs: set[str] = set()
    if index and changed_sheets:
        for entry in index:
            if entry["file"] is not None and entry["file"] in changed_sheets:
                relevant_svgs.add(entry["svg_filename"])

    before = {p: p.stat().st_mtime_ns for p in out_dir.glob("*.svg")}
    try:
        kicad_cli.export_sch_svg(cfg.kicad_cli, proj.sch, out_dir)
    except kicad_cli.CliError as e:
        result.warn(f"Auto-render failed: {e}")
        return

    for svg in sorted(out_dir.glob("*.svg")):
        if svg in before and svg.stat().st_mtime_ns == before[svg]:
            continue
        if relevant_svgs and svg.name not in relevant_svgs:
            continue
        result.add_artifact("schematic_svg", str(svg))


# ---------------------------------------------------------------------------
# Schematic value / ref / footprint / property edits via kicad-skip
# ---------------------------------------------------------------------------

@edit_app.command("value")
def value(
    project: str = typer.Argument(...),
    ref: str = typer.Option(..., "--ref", help="Reference designator, e.g. R5"),
    new_value: str = typer.Option(..., "--value", help="New value, e.g. 10k"),
    no_snapshot: bool = typer.Option(False, "--no-snapshot"),
    no_render: bool = typer.Option(False, "--no-render"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Change a symbol's Value field in the schematic."""
    with run_command("edit.value", json_) as r:
        proj, r.snapshot_before = _pre_edit(project, f"edit value {ref}={new_value}", no_snapshot)
        mtimes = skip_sch.snapshot_sheet_mtimes(proj)
        sheet_path, sheet_name = skip_sch.locate(proj, ref)
        updated = skip_sch.set_value(sheet_path, ref, new_value)
        updated["sheet"] = sheet_name
        r.data = {"updated": updated}
        _post_edit_sch(proj, r, mtimes, no_render=no_render)


@edit_app.command("ref")
def ref_cmd(
    project: str = typer.Argument(...),
    old: str = typer.Option(..., "--from", help="Current reference, e.g. R5"),
    new: str = typer.Option(..., "--to", help="New reference, e.g. R10"),
    no_snapshot: bool = typer.Option(False, "--no-snapshot"),
    no_render: bool = typer.Option(False, "--no-render"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Rename a symbol's reference designator."""
    with run_command("edit.ref", json_) as r:
        proj, r.snapshot_before = _pre_edit(project, f"rename {old} -> {new}", no_snapshot)
        mtimes = skip_sch.snapshot_sheet_mtimes(proj)
        sheet_path, sheet_name = skip_sch.locate(proj, old)
        updated = skip_sch.set_reference(sheet_path, old, new)
        updated["sheet"] = sheet_name
        r.data = {"updated": updated}
        _post_edit_sch(proj, r, mtimes, no_render=no_render)


@edit_app.command("footprint")
def footprint(
    project: str = typer.Argument(...),
    ref: str = typer.Option(..., "--ref"),
    fp: str = typer.Option(..., "--footprint", help="lib:fp, e.g. Resistor_SMD:R_0805_2012Metric"),
    no_snapshot: bool = typer.Option(False, "--no-snapshot"),
    no_render: bool = typer.Option(False, "--no-render"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Set a symbol's Footprint property."""
    with run_command("edit.footprint", json_) as r:
        proj, r.snapshot_before = _pre_edit(project, f"footprint {ref}={fp}", no_snapshot)
        mtimes = skip_sch.snapshot_sheet_mtimes(proj)
        sheet_path, sheet_name = skip_sch.locate(proj, ref)
        updated = skip_sch.set_footprint(sheet_path, ref, fp)
        updated["sheet"] = sheet_name
        r.data = {"updated": updated}
        _post_edit_sch(proj, r, mtimes, no_render=no_render)


@edit_app.command("prop")
def prop(
    project: str = typer.Argument(...),
    ref: str = typer.Option(..., "--ref"),
    field: str = typer.Option(..., "--field", help="Property name, e.g. MPN, Manufacturer"),
    value: str = typer.Option(..., "--value"),
    no_snapshot: bool = typer.Option(False, "--no-snapshot"),
    no_render: bool = typer.Option(False, "--no-render"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Set or create an arbitrary property on a symbol."""
    with run_command("edit.prop", json_) as r:
        proj, r.snapshot_before = _pre_edit(project, f"prop {ref}.{field}={value}", no_snapshot)
        mtimes = skip_sch.snapshot_sheet_mtimes(proj)
        sheet_path, sheet_name = skip_sch.locate(proj, ref)
        updated = skip_sch.set_property(sheet_path, ref, field, value)
        updated["sheet"] = sheet_name
        r.data = {
            "updated": updated,
            "field": field,
            "value": value,
        }
        _post_edit_sch(proj, r, mtimes, no_render=no_render)


@edit_app.command("delete")
def delete(
    project: str = typer.Argument(...),
    ref: str = typer.Option(..., "--ref"),
    no_snapshot: bool = typer.Option(False, "--no-snapshot"),
    no_render: bool = typer.Option(False, "--no-render"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Delete a symbol from the schematic."""
    with run_command("edit.delete", json_) as r:
        proj, r.snapshot_before = _pre_edit(project, f"delete {ref}", no_snapshot)
        mtimes = skip_sch.snapshot_sheet_mtimes(proj)
        sheet_path, sheet_name = skip_sch.locate(proj, ref)
        deleted = skip_sch.delete_symbol(sheet_path, ref)
        deleted["sheet"] = sheet_name
        r.data = {"deleted": deleted}
        _post_edit_sch(proj, r, mtimes, no_render=no_render)


# ---------------------------------------------------------------------------
# Schematic structural edits — wires and net labels
# ---------------------------------------------------------------------------

wire_app = typer.Typer(help="Add or delete wire segments on the root sheet.")
netlabel_app = typer.Typer(help="Add or delete net labels on the root sheet.")


def _parse_xy(text: str) -> tuple[float, float]:
    """Parse an `'X,Y'` coordinate option into a float pair (millimetres)."""
    parts = text.split(",")
    if len(parts) != 2:
        raise CommandError("bad_coordinate", f"Expected 'X,Y', got {text!r}.")
    try:
        return float(parts[0]), float(parts[1])
    except ValueError:
        raise CommandError(
            "bad_coordinate", f"Expected numeric 'X,Y', got {text!r}."
        ) from None


@wire_app.command("add")
def wire_add(
    project: str = typer.Argument(...),
    from_: str = typer.Option(..., "--from", help="Start point 'X,Y' in mm"),
    to: str = typer.Option(..., "--to", help="End point 'X,Y' in mm"),
    no_snapshot: bool = typer.Option(False, "--no-snapshot"),
    no_render: bool = typer.Option(False, "--no-render"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Add a wire segment between two points on the root schematic sheet."""
    with run_command("edit.wire.add", json_) as r:
        start, end = _parse_xy(from_), _parse_xy(to)
        proj, r.snapshot_before = _pre_edit(
            project, f"add wire {from_} -> {to}", no_snapshot
        )
        mtimes = skip_sch.snapshot_sheet_mtimes(proj)
        r.data = {"added": skip_sch.add_wire(proj.sch, start, end)}
        _post_edit_sch(proj, r, mtimes, no_render=no_render)


@wire_app.command("delete")
def wire_delete(
    project: str = typer.Argument(...),
    from_: str = typer.Option(..., "--from", help="Start point 'X,Y' in mm"),
    to: str = typer.Option(..., "--to", help="End point 'X,Y' in mm"),
    no_snapshot: bool = typer.Option(False, "--no-snapshot"),
    no_render: bool = typer.Option(False, "--no-render"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Delete the wire with the given endpoints (either direction)."""
    with run_command("edit.wire.delete", json_) as r:
        start, end = _parse_xy(from_), _parse_xy(to)
        proj, r.snapshot_before = _pre_edit(
            project, f"delete wire {from_} -> {to}", no_snapshot
        )
        mtimes = skip_sch.snapshot_sheet_mtimes(proj)
        r.data = {"deleted": skip_sch.delete_wire(proj.sch, start, end)}
        _post_edit_sch(proj, r, mtimes, no_render=no_render)


@netlabel_app.command("add")
def netlabel_add(
    project: str = typer.Argument(...),
    text: str = typer.Option(..., "--text", help="Net label text"),
    at: str = typer.Option(..., "--at", help="Position 'X,Y' in mm"),
    rotation: float = typer.Option(0.0, "--rotation", help="Rotation in degrees"),
    is_global: bool = typer.Option(False, "--global", help="Global label (default: local)"),
    no_snapshot: bool = typer.Option(False, "--no-snapshot"),
    no_render: bool = typer.Option(False, "--no-render"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Add a local or global net label on the root schematic sheet."""
    with run_command("edit.netlabel.add", json_) as r:
        pos = _parse_xy(at)
        proj, r.snapshot_before = _pre_edit(
            project, f"add label {text}", no_snapshot
        )
        mtimes = skip_sch.snapshot_sheet_mtimes(proj)
        r.data = {"added": skip_sch.add_label(proj.sch, text, pos, rotation, is_global)}
        _post_edit_sch(proj, r, mtimes, no_render=no_render)


@netlabel_app.command("delete")
def netlabel_delete(
    project: str = typer.Argument(...),
    text: str = typer.Option(..., "--text", help="Net label text"),
    at: str = typer.Option(None, "--at", help="Position 'X,Y' to disambiguate"),
    no_snapshot: bool = typer.Option(False, "--no-snapshot"),
    no_render: bool = typer.Option(False, "--no-render"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Delete a net label by text (use --at when several share the name)."""
    with run_command("edit.netlabel.delete", json_) as r:
        pos = _parse_xy(at) if at else None
        proj, r.snapshot_before = _pre_edit(
            project, f"delete label {text}", no_snapshot
        )
        mtimes = skip_sch.snapshot_sheet_mtimes(proj)
        r.data = skip_sch.delete_label(proj.sch, text, pos)
        _post_edit_sch(proj, r, mtimes, no_render=no_render)


edit_app.add_typer(wire_app, name="wire")
edit_app.add_typer(netlabel_app, name="netlabel")


@edit_app.command("add-symbol")
def add_symbol(
    project: str = typer.Argument(...),
    lib_id: str = typer.Option(..., "--lib-id", help="Library:Symbol, e.g. Device:C"),
    ref: str = typer.Option(..., "--ref", help="Reference for the new symbol, e.g. C5"),
    value: str = typer.Option(None, "--value", help="Value (default: the library symbol's)"),
    at: str = typer.Option(None, "--at", help="Position 'X,Y' in mm (default: 100,100)"),
    no_snapshot: bool = typer.Option(False, "--no-snapshot"),
    no_render: bool = typer.Option(False, "--no-render"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Add a component to the root schematic sheet.

    If the project already has the part type, an existing instance is cloned;
    otherwise the symbol is resolved from a library and embedded.
    """
    with run_command("edit.add-symbol", json_) as r:
        pos = _parse_xy(at) if at else (100.0, 100.0)
        proj = resolve(project)
        symbols = skip_sch.list_symbols(proj.sch)
        if any(s.get("reference") == ref for s in symbols):
            raise CommandError(
                "duplicate_ref", f"Reference {ref!r} already exists in the schematic."
            )
        like = next((s["reference"] for s in symbols if s.get("lib_id") == lib_id), None)

        _, r.snapshot_before = _pre_edit(
            project, f"add symbol {ref} ({lib_id})", no_snapshot
        )
        mtimes = skip_sch.snapshot_sheet_mtimes(proj)
        if like is not None:
            added = skip_sch.add_symbol_from_clone(
                proj.sch, like, ref, value, pos if at else None
            )
        else:
            info = symbol_lib.find_symbol(lib_id, proj)
            added = skip_sch.add_symbol_from_library(
                proj.sch, proj.name, lib_id, info["definition"], info["pins"],
                ref, value or info["properties"].get("Value", ""), pos,
            )
        r.data = {"added": added}
        _post_edit_sch(proj, r, mtimes, no_render=no_render)


def _parse_pin_map(text: str) -> dict[str, str]:
    """Parse a `'old=new,old=new'` pin map into a dict."""
    result: dict[str, str] = {}
    for entry in text.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if "=" not in entry:
            raise CommandError(
                "bad_pin_map", f"Expected 'old=new' pairs, got {entry!r}."
            )
        old, new = entry.split("=", 1)
        result[old.strip()] = new.strip()
    return result


@edit_app.command("symbol")
def swap_symbol(
    project: str = typer.Argument(...),
    ref: str = typer.Option(..., "--ref", help="Reference of the symbol to swap"),
    to_lib_id: str = typer.Option(..., "--to-lib-id", help="New Library:Symbol"),
    pin_map: str = typer.Option(
        None, "--pin-map", help="old=new,... — required when the pin sets differ"
    ),
    no_snapshot: bool = typer.Option(False, "--no-snapshot"),
    no_render: bool = typer.Option(False, "--no-render"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Swap a symbol for a different library part.

    When the new part's pin set differs from the old, --pin-map is required
    so the change is explicit. Pin geometry changes, so wires may be left
    dangling — those are reported in warnings (kcd does not reroute).
    """
    with run_command("edit.symbol", json_) as r:
        proj = resolve(project)
        if not any(
            s.get("reference") == ref for s in skip_sch.list_symbols(proj.sch)
        ):
            raise CommandError("not_found", f"Symbol {ref!r} not found in the schematic.")

        info = symbol_lib.find_symbol(to_lib_id, proj)
        before = skip_sch.symbol_pin_geometry(proj.sch, ref)
        old_pins = set(before["numbers"])
        new_pins = {p["number"] for p in info["pins"]}

        if old_pins != new_pins and not pin_map:
            raise CommandError(
                "pin_set_mismatch",
                f"{ref}'s pins {sorted(old_pins)} differ from {to_lib_id}'s "
                f"{sorted(new_pins)} — pass --pin-map (e.g. \"1=2,2=3\") to "
                "confirm the swap.",
            )
        parsed_map: dict[str, str] = {}
        if pin_map:
            parsed_map = _parse_pin_map(pin_map)
            bad_old = set(parsed_map) - old_pins
            bad_new = set(parsed_map.values()) - new_pins
            if bad_old or bad_new:
                raise CommandError(
                    "bad_pin_map",
                    f"--pin-map references unknown pins (old: {sorted(bad_old)}, "
                    f"new: {sorted(bad_new)}).",
                )

        wired_before = {tuple(p) for p in before["wired_positions"]}
        _, r.snapshot_before = _pre_edit(
            project, f"swap {ref} -> {to_lib_id}", no_snapshot
        )
        mtimes = skip_sch.snapshot_sheet_mtimes(proj)
        result = skip_sch.swap_symbol(
            proj.sch, ref, to_lib_id, info["definition"], info["pins"]
        )

        after = skip_sch.symbol_pin_geometry(proj.sch, ref)
        dangling = sorted(wired_before - {tuple(p) for p in after["positions"]})
        result["dangling_wires"] = [list(p) for p in dangling]
        if parsed_map:
            result["pin_map"] = parsed_map
        r.data = {"swapped": result}
        if dangling:
            spots = ", ".join(f"{p[0]},{p[1]}" for p in dangling)
            r.warn(
                f"{len(dangling)} wire end(s) previously on {ref}'s pins no "
                f"longer meet a pin after the swap — reconnect them (kcd does "
                f"not reroute). At: {spots}"
            )
        _post_edit_sch(proj, r, mtimes, no_render=no_render)


# ---------------------------------------------------------------------------
# Net rename — labels + global labels + power symbols (lib_id-aware)
# ---------------------------------------------------------------------------

@edit_app.command("net")
def rename_net(
    project: str = typer.Argument(...),
    old: str = typer.Option(..., "--from", help="Current net name"),
    new: str = typer.Option(..., "--to", help="New net name"),
    no_snapshot: bool = typer.Option(False, "--no-snapshot"),
    no_render: bool = typer.Option(False, "--no-render"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Rename a net across the schematic — labels, global labels, power symbols.

    A power net is renamed lib_id-aware: the power symbol's `lib_id` is
    repointed to `power:<new>` alongside its `Value`, so the rename survives a
    library resync. Without this, KiCad's "Update Symbols from Library"
    silently reverts a Value-only rename.

    Scope: the root sheet only. A net carried by global labels on sub-sheets
    is renamed on the root only — a warning flags any sub-sheet carriers.

    The PCB is not renamed: KiCad 10 exposes no headless forward annotation.
    After the rename the command checks the live board (when KiCad is open)
    and reports whether the old net name is still there — run F8 (Update PCB
    from Schematic), or `kcd sync`, to push the change to the board.
    """
    with run_command("edit.net", json_) as r:
        proj = resolve(project)
        nets = skip_sch.list_nets(proj.sch)
        names = {n["name"] for n in nets}
        if old not in names:
            raise CommandError(
                "not_found",
                f"No net named {old!r} on the root sheet of {proj.name}.",
            )
        merges = new in names

        # Sub-sheet carriers — the rename is root-only, so flag them precisely.
        offsheet: list[str] = []
        for entry in skip_sch.sheet_index(proj):
            path = entry["file"]
            if path is None or path == proj.sch:
                continue
            try:
                if any(n["name"] == old for n in skip_sch.list_nets(path)):
                    offsheet.append(entry["name"] or path.name)
            except Exception:
                continue

        is_power = any(
            n["name"] == old and n["kind"] == "power" for n in nets
        )
        power_def = None
        if is_power:
            try:
                power_def = symbol_lib.find_symbol(f"power:{new}", proj)["definition"]
            except (CommandError, FileNotFoundError, LookupError):
                power_def = None

        _, r.snapshot_before = _pre_edit(
            project, f"rename net {old} -> {new}", no_snapshot
        )
        mtimes = skip_sch.snapshot_sheet_mtimes(proj)
        renamed = skip_sch.rename_net(proj.sch, old, new, power_def)
        r.data = {"renamed": renamed}

        if merges:
            r.warn(
                f"{new!r} already names a net — this rename merges {old!r} "
                "into it."
            )
        if renamed["power_definition_source"] == "derived":
            r.warn(
                f"power:{new} is not a stock library symbol; embedded a "
                "derived definition — KiCad may flag it as out-of-sync with "
                "the library on the next 'Update Symbols from Library'."
            )
        if offsheet:
            r.warn(
                f"{old!r} also appears on sub-sheet(s) {', '.join(offsheet)} "
                "— only the root sheet was renamed; rename those carriers "
                "manually or the net splits."
            )

        # PCB drift check — read-only and fully defensive: the schematic
        # rename already succeeded and is snapshotted, so nothing here may
        # fail the command. kipy 0.7.1 cannot rename a PCB net; we only
        # detect whether the old name still lives on the board.
        from kcd.core.ipc import IpcUnavailable
        try:
            from kcd.adapters import kipy_pcb
            kipy_pcb.assert_board_is(proj.pcb)
            board_nets = kipy_pcb.board_net_names()
            stale = old in board_nets
            r.data["pcb"] = {
                "checked": True,
                "stale": stale,
                "old_net_present": stale,
                "new_net_present": new in board_nets,
            }
            if stale:
                r.warn(
                    f"The PCB still carries net {old!r} — kcd cannot "
                    "forward-annotate headlessly. Run F8 (Update PCB from "
                    "Schematic) in KiCad, or `kcd sync`, to push the rename."
                )
        except IpcUnavailable:
            r.data["pcb"] = {"checked": False, "reason": "KiCad not open"}
            r.warn(
                "PCB drift check skipped — KiCad is not open. The board may "
                "still carry the old net name; run `kcd sync` after opening it."
            )
        except Exception as e:
            r.data["pcb"] = {"checked": False, "reason": str(e)}
            r.warn(f"PCB drift check skipped: {e}")

        _post_edit_sch(proj, r, mtimes, no_render=no_render)


# ---------------------------------------------------------------------------
# PCB edits via kipy IPC
# ---------------------------------------------------------------------------

@edit_app.command("move-fp")
def move_fp(
    project: str = typer.Argument(
        None,
        help="Project path. Omit to auto-detect from the board open in KiCad.",
    ),
    ref: str = typer.Option(..., "--ref"),
    x: float = typer.Option(..., "--x", help="X position in mm"),
    y: float = typer.Option(..., "--y", help="Y position in mm"),
    rotation: float = typer.Option(None, "--rotation", help="Optional rotation in degrees"),
    no_snapshot: bool = typer.Option(False, "--no-snapshot"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Move a footprint on the PCB. Requires KiCad open with PCB editor.

    Note: this calls `board.save()` after mutating, which persists *any*
    unsaved changes the user has open in the PCB editor along with the
    footprint move. kipy 0.7.1 has no dirty-check API so kcd can't avoid
    or warn about specific edits — the warning emitted on every call is
    a blanket advisory. Save or revert in the editor before running.
    """
    with run_command("edit.move-fp", json_) as r:
        _proj, r.snapshot_before = _pre_edit(
            project, f"move {ref} to {x},{y}mm", no_snapshot, auto=True
        )
        r.warn(
            "move-fp calls board.save() — any unsaved changes you have open "
            "in KiCad's PCB editor are persisted along with this edit. "
            "kipy 0.7.1 has no API to detect or skip this; save or revert in "
            "the editor before running mutating IPC commands."
        )
        from kcd.adapters import kipy_pcb
        r.data = {"updated": kipy_pcb.move_footprint(ref, x, y, rotation)}


# ---------------------------------------------------------------------------
# PCB copper edits — tracks, vias, zones (kipy IPC)
# ---------------------------------------------------------------------------

_BOARD_SAVE_WARNING = (
    "This command calls board.save() — any unsaved changes you have open in "
    "KiCad's PCB editor are persisted along with this edit. kipy 0.7.1 has no "
    "dirty-check API; save or revert in the editor before running mutating "
    "IPC commands."
)

track_app = typer.Typer(help="Delete or modify copper tracks on the PCB (kipy IPC).")


@track_app.command("delete")
def track_delete(
    project: str = typer.Argument(
        None,
        help="Project path. Omit to auto-detect from the board open in KiCad.",
    ),
    net: str = typer.Option(None, "--net", help="Select every track on this net"),
    from_: str = typer.Option(None, "--from", help="Segment start 'x,y' in mm"),
    to: str = typer.Option(None, "--to", help="Segment end 'x,y' in mm"),
    layer: str = typer.Option(None, "--layer", help="Narrow selection to a layer, e.g. F.Cu"),
    no_snapshot: bool = typer.Option(False, "--no-snapshot"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Delete copper tracks. Requires KiCad open with the PCB editor.

    Select a whole net with --net, or one segment with --from/--to; --layer
    narrows either. Use `kcd net of` to discover segment coordinates first.

    Note: calls board.save() — see the warning emitted on every run.
    """
    with run_command("edit.track.delete", json_) as r:
        start = _parse_xy(from_) if from_ else None
        end = _parse_xy(to) if to else None
        proj, r.snapshot_before = _pre_edit(
            project, "delete track(s)", no_snapshot, auto=True
        )
        r.warn(_BOARD_SAVE_WARNING)
        from kcd.adapters import kipy_pcb
        r.data = kipy_pcb.delete_tracks(proj.pcb, net, start, end, layer)


@track_app.command("modify")
def track_modify(
    project: str = typer.Argument(
        None,
        help="Project path. Omit to auto-detect from the board open in KiCad.",
    ),
    net: str = typer.Option(None, "--net", help="Select every track on this net"),
    from_: str = typer.Option(None, "--from", help="Segment start 'x,y' in mm"),
    to: str = typer.Option(None, "--to", help="Segment end 'x,y' in mm"),
    layer: str = typer.Option(None, "--layer", help="Narrow selection to a layer"),
    width: float = typer.Option(None, "--width", help="New track width in mm"),
    set_layer: str = typer.Option(None, "--set-layer", help="Move tracks to this layer"),
    set_net: str = typer.Option(None, "--set-net", help="Reassign tracks to this net"),
    no_snapshot: bool = typer.Option(False, "--no-snapshot"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Modify copper tracks — width, layer, or net. Requires KiCad open.

    Selection (--net / --from/--to / --layer) is separate from the changes
    (--width / --set-layer / --set-net); pass at least one of each.

    Note: calls board.save() — see the warning emitted on every run.
    """
    with run_command("edit.track.modify", json_) as r:
        start = _parse_xy(from_) if from_ else None
        end = _parse_xy(to) if to else None
        proj, r.snapshot_before = _pre_edit(
            project, "modify track(s)", no_snapshot, auto=True
        )
        r.warn(_BOARD_SAVE_WARNING)
        from kcd.adapters import kipy_pcb
        r.data = kipy_pcb.modify_tracks(
            proj.pcb, net, start, end, layer,
            width_mm=width, set_layer=set_layer, set_net=set_net,
        )


edit_app.add_typer(track_app, name="track")
