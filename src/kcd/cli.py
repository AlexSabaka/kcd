"""kcd top-level CLI app.

Run `kcd --help` to discover subcommands, or `kcd <subcommand> --help`.
"""

from __future__ import annotations

import typer

from kcd import __version__
from kcd.commands.analyze import analyze_app
from kcd.commands.drc import drc_cmd, erc_cmd
from kcd.commands.edit import edit_app
from kcd.commands.export import export_app
from kcd.commands.inspect import inspect_app
from kcd.commands.net import net_app
from kcd.commands.parity import parity_cmd
from kcd.commands.project import project_app
from kcd.commands.render import render_app
from kcd.commands.route import route_app
from kcd.commands.snapshot import snapshot_app

app = typer.Typer(
    name="kcd",
    help=(
        "Agentic KiCad harness for Claude Code and other agentic AI tools. "
        "All commands accept --json for machine-parseable output."
    ),
    no_args_is_help=True,
    add_completion=False,
)


@app.command()
def version() -> None:
    """Print kcd version."""
    typer.echo(f"kcd {__version__}")


# Mount subcommand groups
app.add_typer(project_app, name="project")
app.add_typer(snapshot_app, name="snapshot")
app.add_typer(render_app, name="render")
app.add_typer(inspect_app, name="inspect")
app.add_typer(edit_app, name="edit")
app.add_typer(net_app, name="net")
app.add_typer(export_app, name="export")
app.add_typer(route_app, name="route")
app.add_typer(analyze_app, name="analyze")

# Flat top-level commands (frequent enough to deserve a short path)
app.command("drc")(drc_cmd)
app.command("erc")(erc_cmd)
app.command("parity")(parity_cmd)


if __name__ == "__main__":
    app()
