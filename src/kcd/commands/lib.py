"""`kcd lib` — symbol-library inspection.

Read-only window onto the symbol libraries kcd can resolve (`symbol_lib`
adapter). `lib show` lets an agent inspect a part — pins, properties, source
file — before Wave 4's `edit add-symbol` places it.
"""

from __future__ import annotations

import typer

from kcd.adapters import symbol_lib
from kcd.core.output import run_command
from kcd.core.project import resolve

lib_app = typer.Typer(help="Inspect KiCad symbol libraries.")


@lib_app.command("show")
def show(
    lib_id: str = typer.Argument(..., help="Library:Symbol, e.g. Device:R"),
    project: str = typer.Option(
        None, "--project", help="Project path — needed only for project-local libraries."
    ),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Resolve a symbol and show its pins, properties, and source library file."""
    with run_command("lib.show", json_) as r:
        proj = resolve(project) if project else None
        info = symbol_lib.find_symbol(lib_id, proj)
        r.data = {
            "lib_id": info["lib_id"],
            "library": info["library"],
            "name": info["name"],
            "source_file": info["source_file"],
            "pins": info["pins"],
            "properties": info["properties"],
        }


@lib_app.command("list")
def list_libs(
    project: str = typer.Option(
        None, "--project", help="Project path — to also include its sym-lib-table."
    ),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """List the symbol libraries kcd can resolve."""
    with run_command("lib.list", json_) as r:
        proj = resolve(project) if project else None
        libs = symbol_lib.list_libraries(proj)
        r.data = {"count": len(libs), "libraries": libs}
