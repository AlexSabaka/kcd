"""`kcd edit` subcommands — mutating operations on schematic and PCB.

All edits auto-snapshot before mutating (unless --no-snapshot) and auto-render
after (unless --no-render). The render output lands at:
    <render_cache_dir>/<sheet>.svg
"""

from __future__ import annotations

from pathlib import Path

import typer

from kcd.adapters import kicad_cli, skip_sch
from kcd.core import config as cfg_mod
from kcd.core.output import Result, run_command
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
