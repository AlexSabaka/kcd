"""`kcd snapshot` subcommands."""

from __future__ import annotations

import typer

from kcd.core import config as cfg_mod
from kcd.core.output import run_command
from kcd.core.project import resolve
from kcd.core.snapshot import SnapshotStore

snapshot_app = typer.Typer(help="Git-backed snapshots for safe agentic editing.")

# A unified diff at or below this many chars rides inline; a larger one (a
# filled-zone .kicad_pcb diff is thousands of polygon points) spills to the
# artifact so the envelope never overruns the 1MB MCP result cap.
_DIFF_INLINE_BUDGET = 16_000


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
        payload: dict[str, object] = {
            "ref": info.ref,
            "short": info.short,
            "message": info.message,
        }
        # Force KiCad to reload from the just-restored disk file. Without this,
        # the editor keeps its pre-restore memory state and the next mutating
        # IPC call (`move_footprint`, ...) saves that stale memory on top of
        # the revert — silent corruption of the user's restore (Dove #18).
        # IpcUnavailable just means no editor is open → nothing to sync.
        from kcd.adapters import kipy_pcb
        from kcd.core.ipc import IpcUnavailable
        try:
            kipy_pcb.revert_board()
            payload["kicad_reverted"] = True
        except IpcUnavailable:
            # File reverted, but KiCad isn't reachable to sync its memory.
            # This is the silent-corruption path: an agent that runs a
            # mutating IPC command next (`move-fp`) will write stale KiCad
            # memory on top of the just-restored file. Surface it as a
            # warning so the agent sees the hazard even without inspecting
            # `data.kicad_reverted` (Dove session-4 #21).
            r.warn(
                "Snapshot file reverted but KiCad's in-memory board was not "
                "synced (KiCad not running with PCB open). The next mutating "
                "IPC command may overwrite the restored file with stale "
                "KiCad memory. Reload the .kicad_pcb in KiCad before "
                "continuing, or close the editor entirely."
            )
            payload["kicad_reverted"] = False
        except Exception as e:  # noqa: BLE001
            r.warn(
                f"Snapshot file restored but KiCad's in-memory board may be "
                f"stale: {e}. Run File → Revert in KiCad to sync, or close "
                "and reopen the .kicad_pcb."
            )
            payload["kicad_reverted"] = False
        r.data = payload


@snapshot_app.command("diff")
def diff(
    project: str = typer.Argument(...),
    ref_a: str = typer.Argument(..., help="First ref (or only ref to diff vs working tree)"),
    ref_b: str = typer.Argument(None, help="Second ref (optional)"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Show diff between snapshots (or one snapshot vs current state).

    The inline envelope carries a per-file summary (files changed, lines
    added/removed). A small diff body also rides inline; a large one — a
    filled-zone `.kicad_pcb` diff is thousands of polygon points — spills to
    the artifact. The artifact always holds the complete unified diff.
    """
    with run_command("snapshot.diff", json_) as r:
        cfg = cfg_mod.load()
        proj = resolve(project)
        store = SnapshotStore(proj, dir_name=cfg.snapshot_dir_name)
        text = store.diff(ref_a, ref_b)
        summary = store.diff_summary(ref_a, ref_b)

        diff_path = cfg.render_cache_dir / f"{proj.name}-diff.patch"
        diff_path.parent.mkdir(parents=True, exist_ok=True)
        diff_path.write_text(text)
        r.add_artifact("snapshot_diff", str(diff_path))

        data: dict[str, object] = {"ref_a": ref_a, "ref_b": ref_b, **summary}
        if len(text) <= _DIFF_INLINE_BUDGET:
            data["diff"] = text
        else:
            data["diff_inlined"] = False
            r.warn(
                f"diff is {len(text)} chars — too large to inline; the "
                "complete unified diff is in the artifact"
            )
        r.data = data
