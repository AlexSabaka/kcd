"""MCP server that wraps the `kcd` CLI for Claude Desktop and other MCP clients.

Each kcd subcommand is exposed as a typed MCP tool. The tool handlers shell out
to `python -m kcd <subcmd> ... --json` and return the parsed JSON envelope.
"""

__version__ = "0.1.0"
