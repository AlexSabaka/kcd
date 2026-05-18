"""`kcd snapshot` subcommands."""

from __future__ import annotations

import typer

from kcd.core import config as cfg_mod
from kcd.core.output import run_command
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
    with run_command("snapshot.create", json_) as r:
        cfg = cfg_mod.load()
        proj = resolve(project)
        store = SnapshotStore(proj, dir_name=cfg.snapshot_dir_name)
        info = store.create(message)
        r.data = {
            "ref": info.ref,
            "short": info.short,
            "message": info.message,
            "timestamp": info.timestamp,
        }
        r.snapshot_before = info.ref


@snapshot_app.command("list")
def list_(
    project: str = typer.Argument(...),
    limit: int = typer.Option(20, "-n", "--limit"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """List recent snapshots, newest first."""
    with run_command("snapshot.list", json_) as r:
        cfg = cfg_mod.load()
        proj = resolve(project)
        store = SnapshotStore(proj, dir_name=cfg.snapshot_dir_name)
        items = store.list(limit=limit)
        r.data = {
            "snapshots": [
                {"ref": i.ref, "short": i.short, "message": i.message, "timestamp": i.timestamp}
                for i in items
            ]
        }


@snapshot_app.command("restore")
def restore(
    project: str = typer.Argument(...),
    ref: str = typer.Argument(..., help="Snapshot ref (short SHA, HEAD~1, etc.)"),
    json_: bool = typer.Option(False, "--json"),
    confirm: bool = typer.Option(False, "--yes", help="Skip confirmation"),
) -> None:
    """Restore the project to a previous snapshot. DESTRUCTIVE within the project dir."""
    # Interactive confirm lives outside the envelope wrapper: typer.Abort is a
    # CLI-level signal, not a command error, and should propagate cleanly.
    if not confirm and not json_:
        # We need the project root for the prompt message, but resolve() may
        # itself fail — wrap that step alone in a mini-try so the prompt is
        # informative even on partial state.
        try:
            preview = resolve(project).root
        except FileNotFoundError:
            preview = project
        typer.confirm(
            f"This will hard-reset {preview} to snapshot {ref}. "
            "Uncommitted changes will be lost. Continue?",
            abort=True,
        )

    with run_command("snapshot.restore", json_) as r:
        cfg = cfg_mod.load()
        proj = resolve(project)
        store = SnapshotStore(proj, dir_name=cfg.snapshot_dir_name)
        info = store.restore(ref)
        r.data = {"ref": info.ref, "short": info.short, "message": info.message}


@snapshot_app.command("diff")
def diff(
    project: str = typer.Argument(...),
    ref_a: str = typer.Argument(..., help="First ref (or only ref to diff vs working tree)"),
    ref_b: str = typer.Argument(None, help="Second ref (optional)"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Show diff between snapshots (or one snapshot vs current state)."""
    with run_command("snapshot.diff", json_) as r:
        cfg = cfg_mod.load()
        proj = resolve(project)
        store = SnapshotStore(proj, dir_name=cfg.snapshot_dir_name)
        text = store.diff(ref_a, ref_b)
        r.data = {"diff": text, "ref_a": ref_a, "ref_b": ref_b}
