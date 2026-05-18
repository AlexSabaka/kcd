"""`kcd route` subcommands — single-track routing and FreeRouting orchestration."""

from __future__ import annotations

from pathlib import Path

import typer

from kcd.adapters import freerouting
from kcd.core import config as cfg_mod
from kcd.core.output import CommandError, run_command
from kcd.core.project import resolve, resolve_or_active
from kcd.core.snapshot import SnapshotStore

route_app = typer.Typer(help="Routing helpers — single tracks and FreeRouting handoff.")


@route_app.command("track")
def track(
    project: str = typer.Argument(
        None,
        help="Project path. Omit to auto-detect from the board open in KiCad.",
    ),
    net: str = typer.Option(..., "--net"),
    start: str = typer.Option(..., "--from", help="Start point as `x,y` in mm"),
    end: str = typer.Option(..., "--to", help="End point as `x,y` in mm"),
    layer: str = typer.Option("F.Cu", "--layer"),
    width: float = typer.Option(0.25, "--width", help="Track width in mm"),
    no_snapshot: bool = typer.Option(False, "--no-snapshot"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Add a single straight track between two coordinates. Requires KiCad with PCB open."""
    with run_command("route.track", json_) as r:
        cfg = cfg_mod.load()
        proj = resolve_or_active(project)

        try:
            sx, sy = (float(x) for x in start.split(","))
            ex, ey = (float(x) for x in end.split(","))
        except ValueError as e:
            raise CommandError(
                "invalid_coord",
                f"--from/--to must be 'x,y' in mm; got {start!r} / {end!r}: {e}",
            ) from e

        if cfg.auto_snapshot and not no_snapshot:
            store = SnapshotStore(proj, dir_name=cfg.snapshot_dir_name)
            info = store.create(f"before: route track {net} {start}->{end}")
            r.snapshot_before = info.ref

        from kcd.adapters import kipy_pcb
        r.data = {"track": kipy_pcb.add_track(
            net_name=net,
            start_mm=(sx, sy),
            end_mm=(ex, ey),
            layer=layer,
            width_mm=width,
        )}


@route_app.command("freeroute")
def freeroute(
    project: str = typer.Argument(...),
    dsn: Path = typer.Option(
        None,
        "--dsn",
        help="Path to .dsn file (export from KiCad: File→Export→Specctra DSN)",
    ),
    out_ses: Path = typer.Option(None, "--out-ses", help="Output .ses path"),
    passes: int = typer.Option(100, "--passes"),
    opt_passes: int = typer.Option(20, "--opt-passes"),
    timeout: int = typer.Option(600, "--timeout", help="Timeout in seconds"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Run FreeRouting on a .dsn file to autoroute the board.

    Workflow:
        1. In KiCad PCB editor: File → Export → Specctra DSN → save as <name>.dsn
        2. `kcd route freeroute <project> --dsn <name>.dsn`
        3. In KiCad PCB editor: File → Import → Specctra Session → select <name>.ses
    """
    with run_command("route.freeroute", json_) as r:
        cfg = cfg_mod.load()
        proj = resolve(project)

        if not cfg.freerouting_jar:
            raise CommandError(
                "no_jar",
                "FreeRouting JAR not configured. Set KCD_FREEROUTING_JAR env var to the JAR path. "
                "Download from https://github.com/freerouting/freerouting/releases",
            )

        if dsn is None:
            dsn = proj.root / f"{proj.name}.dsn"
            if not dsn.exists():
                raise CommandError(
                    "no_dsn",
                    f"No --dsn provided and {dsn} not found. "
                    "Export from KiCad: File → Export → Specctra DSN.",
                )

        if out_ses is None:
            out_ses = proj.root / f"{proj.name}.ses"

        try:
            result = freerouting.autoroute(
                jar_path=cfg.freerouting_jar,
                dsn_path=dsn,
                out_ses=out_ses,
                optimization_passes=opt_passes,
                routing_passes=passes,
                timeout_seconds=timeout,
            )
        except freerouting.FreeroutingError as e:
            raise CommandError("freeroute_failed", str(e)) from e

        r.add_artifact("specctra_session", str(result.ses))
        r.data = {
            "dsn": str(result.dsn),
            "ses": str(result.ses),
            "routing_passes": result.passes,
        }
        r.warn(
            "Open KiCad's PCB editor and run File → Import → Specctra Session "
            f"to apply the routed result from {result.ses}."
        )
