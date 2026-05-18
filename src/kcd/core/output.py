"""Output formatting: dual-mode JSON / pretty, with a consistent result envelope.

Every command returns a `Result` and emits it through `emit(result, json_mode)`.
JSON mode produces machine-parseable output; pretty mode uses Rich.

For the command layer, the `run_command` context manager wraps body execution
in a uniform exception ladder so no command can leak a Python traceback to the
JSON envelope. Commands raise `CommandError(code, message)` for expected
failures; anything else is caught generically with `code="unexpected"`.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from rich.console import Console
from rich.table import Table

_console = Console()
_err_console = Console(stderr=True, style="bold red")


@dataclass
class Result:
    """Universal result envelope returned by every command.

    The JSON form is::

        {
          "ok": bool,
          "command": "edit.value",
          "data": {...},          // command-specific payload
          "warnings": [str, ...],
          "artifacts": [{...}],   // paths to files produced (renders, exports)
          "snapshot_before": "abc1234" | null,
          "error": null | {"code": "...", "message": "..."}
        }
    """

    command: str
    ok: bool = True
    data: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    snapshot_before: str | None = None
    error: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "command": self.command,
            "data": self.data,
            "warnings": self.warnings,
            "artifacts": self.artifacts,
            "snapshot_before": self.snapshot_before,
            "error": self.error,
        }

    def add_artifact(self, kind: str, path: str, **meta: Any) -> None:
        self.artifacts.append({"kind": kind, "path": path, **meta})

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def fail(self, code: str, message: str) -> None:
        self.ok = False
        self.error = {"code": code, "message": message}


def emit(result: Result, json_mode: bool) -> None:
    """Emit a result to stdout. Exits with non-zero status if `result.ok` is False."""
    if json_mode:
        print(json.dumps(result.to_dict(), default=str, indent=2))
    else:
        _pretty(result)
    if not result.ok:
        sys.exit(1)


class CommandError(Exception):
    """Raised inside a `run_command` block to fail with a structured envelope.

    Prefer this over `r.fail(...)` + early return inside command bodies — it
    plays cleanly with the context manager's exit path and lets the caller
    centralize the emit.
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@contextmanager
def run_command(name: str, json_mode: bool) -> Iterator[Result]:
    """Wrap a command body so no exception escapes as a raw traceback.

    Usage::

        @app.command("sch")
        def sch(project: str, json_: bool = typer.Option(False, "--json")):
            with run_command("inspect.sch", json_) as r:
                proj = resolve(project)
                r.data = {"symbols": skip_sch.list_symbols(proj.sch)}

    Any exception raised inside the `with` block is mapped to a `Result.fail()`
    call and the result is emitted at exit. Recognized exception types map to
    stable error codes; unknown exceptions become `code="unexpected"` with the
    type name preserved in the message.
    """
    # Lazy imports — adapter exception types live outside `core/`, and we want
    # to keep `output.py` importable without pulling adapters at module load.
    from kcd.adapters.kicad_cli import CliError
    from kcd.adapters.skip_sch import SchEditError
    from kcd.core.ipc import IpcUnavailable

    r = Result(command=name)
    try:
        yield r
    except CommandError as e:
        r.fail(e.code, e.message)
    except FileNotFoundError as e:
        r.fail("not_found", str(e))
    except IpcUnavailable as e:
        r.fail("ipc_unavailable", str(e))
    except SchEditError as e:
        r.fail("edit_failed", str(e))
    except CliError as e:
        r.fail("cli_failed", str(e))
    except LookupError as e:
        r.fail("not_found", str(e))
    except Exception as e:  # noqa: BLE001
        r.fail("unexpected", f"{type(e).__name__}: {e}")
    emit(r, json_mode)


def _pretty(result: Result) -> None:
    status = "[green]✓[/green]" if result.ok else "[red]✗[/red]"
    _console.print(f"{status} [bold]{result.command}[/bold]")
    if result.snapshot_before:
        _console.print(f"  snapshot: [dim]{result.snapshot_before[:8]}[/dim]")
    if result.data:
        _pretty_data(result.data)
    for w in result.warnings:
        _console.print(f"  [yellow]warning:[/yellow] {w}")
    for a in result.artifacts:
        path = a.get("path", "?")
        kind = a.get("kind", "file")
        _console.print(f"  [cyan]{kind}:[/cyan] {path}")
    if result.error:
        _err_console.print(f"  {result.error['code']}: {result.error['message']}")


def _pretty_data(data: dict[str, Any]) -> None:
    """Best-effort pretty rendering of common payload shapes."""
    # If data has a single tabular field, render as a table.
    for key, value in data.items():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            _render_table(key, value)
        else:
            _console.print(f"  [dim]{key}:[/dim] {value}")


def _render_table(title: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    table = Table(title=title, show_header=True, header_style="bold magenta")
    columns = list(rows[0].keys())
    for col in columns:
        table.add_column(col)
    for row in rows:
        table.add_row(*(str(row.get(c, "")) for c in columns))
    _console.print(table)
