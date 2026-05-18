"""`kcd edit` subcommands — mutating operations on schematic and PCB.

All edits auto-snapshot before mutating (unless --no-snapshot) and auto-render
after (unless --no-render). The render output lands at:
    <render_cache_dir>/last-edit.<format>
"""

from __future__ import annotations

from pathlib import Path

import typer

from kcd.adapters import kicad_cli, skip_sch
from kcd.core import config as cfg_mod
from kcd.core.output import Result, emit
from kcd.core.project import Project, resolve
from kcd.core.snapshot import SnapshotStore

edit_app = typer.Typer(help="Mutating operations. Auto-snapshot before, auto-render after.")


def _pre_edit(project_arg: str, msg: str, no_snapshot: bool) -> tuple[Project, str | None]:
    """Resolve project + snapshot. Returns (project, snapshot_ref or None)."""
    cfg = cfg_mod.load()
    proj = resolve(project_arg)
    snap_ref: str | None = None
    if cfg.auto_snapshot and not no_snapshot:
        store = SnapshotStore(proj, dir_name=cfg.snapshot_dir_name)
        info = store.create(f"before: {msg}")
        snap_ref = info.ref
    return proj, snap_ref


def _post_edit_sch(proj: Project, result: Result) -> None:
    """Auto-render the schematic to the cache dir."""
    cfg = cfg_mod.load()
    if not cfg.auto_render:
        return
    cfg.render_cache_dir.mkdir(parents=True, exist_ok=True)
    out_dir = cfg.render_cache_dir
    try:
        kicad_cli.export_sch_svg(cfg.kicad_cli, proj.sch, out_dir)
        for svg in sorted(out_dir.glob("*.svg")):
            result.add_artifact("schematic_svg", str(svg))
    except kicad_cli.CliError as e:
        result.warn(f"Auto-render failed: {e}")


# ---------------------------------------------------------------------------
# Schematic value / ref / footprint / property edits via kicad-skip
# ---------------------------------------------------------------------------

@edit_app.command("value")
def value(
    project: str = typer.Argument(...),
    ref: str = typer.Option(..., "--ref", help="Reference designator, e.g. R5"),
    new_value: str = typer.Option(..., "--value", help="New value, e.g. 10k"),
    no_snapshot: bool = typer.Option(False, "--no-snapshot"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Change a symbol's Value field in the schematic."""
    proj, snap = _pre_edit(project, f"edit value {ref}={new_value}", no_snapshot)
    r = Result(command="edit.value")
    r.snapshot_before = snap
    try:
        r.data = {"updated": skip_sch.set_value(proj.sch, ref, new_value)}
    except skip_sch.SchEditError as e:
        r.fail("edit_failed", str(e))
        emit(r, json_)
        return
    _post_edit_sch(proj, r)
    emit(r, json_)


@edit_app.command("ref")
def ref_cmd(
    project: str = typer.Argument(...),
    old: str = typer.Option(..., "--from", help="Current reference, e.g. R5"),
    new: str = typer.Option(..., "--to", help="New reference, e.g. R10"),
    no_snapshot: bool = typer.Option(False, "--no-snapshot"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Rename a symbol's reference designator."""
    proj, snap = _pre_edit(project, f"rename {old} -> {new}", no_snapshot)
    r = Result(command="edit.ref")
    r.snapshot_before = snap
    try:
        r.data = {"updated": skip_sch.set_reference(proj.sch, old, new)}
    except skip_sch.SchEditError as e:
        r.fail("edit_failed", str(e))
        emit(r, json_)
        return
    _post_edit_sch(proj, r)
    emit(r, json_)


@edit_app.command("footprint")
def footprint(
    project: str = typer.Argument(...),
    ref: str = typer.Option(..., "--ref"),
    fp: str = typer.Option(..., "--footprint", help="lib:fp, e.g. Resistor_SMD:R_0805_2012Metric"),
    no_snapshot: bool = typer.Option(False, "--no-snapshot"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Set a symbol's Footprint property."""
    proj, snap = _pre_edit(project, f"footprint {ref}={fp}", no_snapshot)
    r = Result(command="edit.footprint")
    r.snapshot_before = snap
    try:
        r.data = {"updated": skip_sch.set_footprint(proj.sch, ref, fp)}
    except skip_sch.SchEditError as e:
        r.fail("edit_failed", str(e))
        emit(r, json_)
        return
    _post_edit_sch(proj, r)
    emit(r, json_)


@edit_app.command("prop")
def prop(
    project: str = typer.Argument(...),
    ref: str = typer.Option(..., "--ref"),
    field: str = typer.Option(..., "--field", help="Property name, e.g. MPN, Manufacturer"),
    value: str = typer.Option(..., "--value"),
    no_snapshot: bool = typer.Option(False, "--no-snapshot"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Set or create an arbitrary property on a symbol."""
    proj, snap = _pre_edit(project, f"prop {ref}.{field}={value}", no_snapshot)
    r = Result(command="edit.prop")
    r.snapshot_before = snap
    try:
        r.data = {"updated": skip_sch.set_property(proj.sch, ref, field, value)}
    except skip_sch.SchEditError as e:
        r.fail("edit_failed", str(e))
        emit(r, json_)
        return
    _post_edit_sch(proj, r)
    emit(r, json_)


@edit_app.command("delete")
def delete(
    project: str = typer.Argument(...),
    ref: str = typer.Option(..., "--ref"),
    no_snapshot: bool = typer.Option(False, "--no-snapshot"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Delete a symbol from the schematic."""
    proj, snap = _pre_edit(project, f"delete {ref}", no_snapshot)
    r = Result(command="edit.delete")
    r.snapshot_before = snap
    try:
        r.data = {"deleted": skip_sch.delete_symbol(proj.sch, ref)}
    except skip_sch.SchEditError as e:
        r.fail("edit_failed", str(e))
        emit(r, json_)
        return
    _post_edit_sch(proj, r)
    emit(r, json_)


# ---------------------------------------------------------------------------
# PCB edits via kipy IPC
# ---------------------------------------------------------------------------

@edit_app.command("move-fp")
def move_fp(
    project: str = typer.Argument(...),
    ref: str = typer.Option(..., "--ref"),
    x: float = typer.Option(..., "--x", help="X position in mm"),
    y: float = typer.Option(..., "--y", help="Y position in mm"),
    rotation: float = typer.Option(None, "--rotation", help="Optional rotation in degrees"),
    no_snapshot: bool = typer.Option(False, "--no-snapshot"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Move a footprint on the PCB. Requires KiCad open with PCB editor."""
    proj, snap = _pre_edit(project, f"move {ref} to {x},{y}mm", no_snapshot)
    r = Result(command="edit.move-fp")
    r.snapshot_before = snap
    try:
        from kcd.adapters import kipy_pcb
        from kcd.core.ipc import IpcUnavailable
        try:
            r.data = {"updated": kipy_pcb.move_footprint(ref, x, y, rotation)}
        except IpcUnavailable as e:
            r.fail("ipc_unavailable", str(e))
        except LookupError as e:
            r.fail("not_found", str(e))
    except ImportError as e:
        r.fail("import_failed", str(e))
    emit(r, json_)
