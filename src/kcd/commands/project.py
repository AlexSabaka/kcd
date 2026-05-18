"""`kcd project` subcommands — discovery and inspection of the active project."""

from __future__ import annotations

import typer

from kcd.core.output import run_command

project_app = typer.Typer(
    help="Discover what KiCad is currently working on — the agentic bootstrap step."
)


@project_app.command("current")
def current(
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """List all documents currently open in KiCad (boards, schematics, projects).

    Use this as the first call in a session to find out what to drive next —
    most IPC commands accept the discovered board path as their --project
    argument, or you can omit --project and they'll auto-detect.
    """
    with run_command("project.current", json_) as r:
        from kcd.adapters.kipy_pcb import list_open_documents
        r.data = {"open_documents": list_open_documents()}
