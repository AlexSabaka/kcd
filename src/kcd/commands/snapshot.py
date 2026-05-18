"""`kcd snapshot` subcommands."""

from __future__ import annotations

import typer

from kcd.core import config as cfg_mod
from kcd.core.output import Result, emit
from kcd.core.project import resolve
from kcd.core.snapshot import SnapshotStore

snapshot_app = typer.Typer(help="Git-backed snapshots for safe agentic editing.")


@snapshot_app.command("create")
def create(
    project: str = typer.Argument(..., help="Path to .kicad_pro file or project directory"),
    message: str = typer.Option("manual snapshot", "-m", "--message", help="Snapshot message"),
    json_: bool = typer.Option(False, "--json", help="Emit JSON"),
) -> None:
    """Create a new snapshot of the project's current state."""
    cfg = cfg_mod.load()
    proj = resolve(project)
    store = SnapshotStore(proj, dir_name=cfg.snapshot_dir_name)
    info = store.create(message)
    r = Result(command="snapshot.create")
    r.data = {
        "ref": info.ref,
        "short": info.short,
        "message": info.message,
        "timestamp": info.timestamp,
    }
    r.snapshot_before = info.ref
    emit(r, json_)


@snapshot_app.command("list")
def list_(
    project: str = typer.Argument(...),
    limit: int = typer.Option(20, "-n", "--limit"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """List recent snapshots, newest first."""
    cfg = cfg_mod.load()
    proj = resolve(project)
    store = SnapshotStore(proj, dir_name=cfg.snapshot_dir_name)
    items = store.list(limit=limit)
    r = Result(command="snapshot.list")
    r.data = {
        "snapshots": [
            {"ref": i.ref, "short": i.short, "message": i.message, "timestamp": i.timestamp}
            for i in items
        ]
    }
    emit(r, json_)


@snapshot_app.command("restore")
def restore(
    project: str = typer.Argument(...),
    ref: str = typer.Argument(..., help="Snapshot ref (short SHA, HEAD~1, etc.)"),
    json_: bool = typer.Option(False, "--json"),
    confirm: bool = typer.Option(False, "--yes", help="Skip confirmation"),
) -> None:
    """Restore the project to a previous snapshot. DESTRUCTIVE within the project dir."""
    cfg = cfg_mod.load()
    proj = resolve(project)
    store = SnapshotStore(proj, dir_name=cfg.snapshot_dir_name)
    if not confirm and not json_:
        typer.confirm(
            f"This will hard-reset {proj.root} to snapshot {ref}. "
            "Uncommitted changes will be lost. Continue?",
            abort=True,
        )
    info = store.restore(ref)
    r = Result(command="snapshot.restore")
    r.data = {"ref": info.ref, "short": info.short, "message": info.message}
    emit(r, json_)


@snapshot_app.command("diff")
def diff(
    project: str = typer.Argument(...),
    ref_a: str = typer.Argument(..., help="First ref (or only ref to diff vs working tree)"),
    ref_b: str = typer.Argument(None, help="Second ref (optional)"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Show diff between snapshots (or one snapshot vs current state)."""
    cfg = cfg_mod.load()
    proj = resolve(project)
    store = SnapshotStore(proj, dir_name=cfg.snapshot_dir_name)
    text = store.diff(ref_a, ref_b)
    r = Result(command="snapshot.diff")
    r.data = {"diff": text, "ref_a": ref_a, "ref_b": ref_b}
    emit(r, json_)
