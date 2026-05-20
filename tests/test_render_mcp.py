"""Tests for the MCP render wrappers' inline-image return (Round-3 B3).

In MCP-remote operation a render written to the operator's disk never reaches
the agent. The `kcd_render_*` wrappers now return the PNG as an inline
`Image` content block. `_attach_image` is the pure decision point — tested
here without a live kicad-cli.
"""

from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import Image

import kcd_mcp.__main__ as srv
from kcd_mcp.__main__ import _attach_image

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def test_attach_image_none_returns_envelope() -> None:
    env = {"ok": True, "warnings": []}
    assert _attach_image(env, None) is env


def test_attach_image_missing_file_returns_envelope() -> None:
    env = {"ok": True, "warnings": []}
    assert _attach_image(env, "/no/such/render.png") is env


def test_attach_image_empty_file_returns_envelope(tmp_path: Path) -> None:
    png = tmp_path / "empty.png"
    png.write_bytes(b"")
    env = {"ok": True, "warnings": []}
    assert _attach_image(env, str(png)) is env


def test_attach_image_small_png_returns_image_block(tmp_path: Path) -> None:
    png = tmp_path / "render.png"
    png.write_bytes(_PNG_MAGIC + b"x" * 128)
    env = {"ok": True, "warnings": []}
    result = _attach_image(env, str(png))
    assert isinstance(result, list)
    assert result[0] is env
    assert isinstance(result[1], Image)


def test_attach_image_oversized_skips_and_warns(
    tmp_path: Path, monkeypatch,
) -> None:
    """An image over the inline cap is skipped with a warning, not inlined —
    inlining it would blow the whole tool response past the 1MB MCP cap."""
    monkeypatch.setattr(srv, "_IMAGE_CAP", 32)
    png = tmp_path / "huge.png"
    png.write_bytes(_PNG_MAGIC + b"x" * 512)
    env = {"ok": True, "warnings": []}
    result = _attach_image(env, str(png))
    assert result is env
    assert any("too large to inline" in w for w in env["warnings"])
