"""Drift guard: every kcd CLI leaf command must have a matching MCP tool.

The MCP server (`kcd_mcp`) hand-wraps each CLI subcommand as an `@mcp.tool()`.
That mapping silently drifted once already — the entire Waves 1-7 surface
shipped in the CLI without ever reaching the MCP layer, so an MCP client saw a
frozen, pre-roadmap toolset. This test fails the moment a CLI command is added
(or removed) without the matching MCP tool, on either side.

The MCP tooling lives behind the optional `mcp` extra; the test skips cleanly
when that package isn't installed.
"""

from __future__ import annotations

import asyncio

import pytest
import typer

from kcd.cli import app as cli_app

pytest.importorskip("mcp")

# Imported after the optional-dep guard above, so it stays below importorskip.
from kcd_mcp.__main__ import mcp

# CLI commands deliberately not exposed over MCP. `version` prints a string,
# not a JSON envelope — it has no place in the agent toolset.
_CLI_ONLY: set[tuple[str, ...]] = {("version",)}


def _leaf_commands(
    app: typer.Typer, prefix: tuple[str, ...] = ()
) -> list[tuple[str, ...]]:
    """Every leaf command path in a Typer app, as tuples of path parts."""
    leaves: list[tuple[str, ...]] = []
    for cmd in app.registered_commands:
        name = cmd.name or cmd.callback.__name__.replace("_", "-")
        leaves.append((*prefix, name))
    for grp in app.registered_groups:
        leaves.extend(_leaf_commands(grp.typer_instance, (*prefix, grp.name)))
    return leaves


def _expected_tool(path: tuple[str, ...]) -> str:
    """The MCP tool name a CLI command path maps to: `net of` -> `kcd_net_of`."""
    return "kcd_" + "_".join(path).replace("-", "_")


def _registered_tools() -> set[str]:
    return {t.name for t in asyncio.run(mcp.list_tools())}


def test_every_cli_command_has_an_mcp_tool() -> None:
    tools = _registered_tools()
    missing = sorted(
        f"  {' '.join(path)}  ->  {_expected_tool(path)}"
        for path in _leaf_commands(cli_app)
        if path not in _CLI_ONLY and _expected_tool(path) not in tools
    )
    assert not missing, "CLI commands with no MCP tool:\n" + "\n".join(missing)


def test_no_orphan_mcp_tools() -> None:
    expected = {
        _expected_tool(path)
        for path in _leaf_commands(cli_app)
        if path not in _CLI_ONLY
    }
    orphans = sorted(_registered_tools() - expected)
    assert not orphans, "MCP tools with no CLI command:\n" + "\n".join(orphans)
