"""kcd_mcp stdio server.

Run with: `python -m kcd_mcp`

Configure in Claude Desktop's claude_desktop_config.json::

    {
      "mcpServers": {
        "kcd": {
          "command": "/path/to/.venv/bin/python",
          "args": ["-m", "kcd_mcp"]
        }
      }
    }
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("kcd")

# How many bytes of stderr to surface on hard crash (empty/non-JSON stdout).
# Generous because this is the agent's only debugging channel when kcd
# couldn't emit an envelope — clipping at ~500 (the previous default) lost
# whole tracebacks mid-frame.
_STDERR_CAP = 4000


def _run(args: list[str]) -> dict[str, Any]:
    """Invoke `python -m kcd <args> --json` and return the parsed envelope.

    kcd always writes a structured envelope to stdout (envelope-everywhere
    wrapper in core/output.py), so non-zero exit + clean JSON is the normal
    error case. The fallback branches below only fire if kcd somehow died
    before emit() ran — in which case full stderr is the diagnostic.

    We pass `env=os.environ.copy()` explicitly so $HOME and $PATH propagate
    into the kcd subprocess — without it, the MCP-spawned child can end up
    with a stripped env and tilde-paths fail to expand.
    """
    cmd = [sys.executable, "-m", "kcd", *args, "--json"]
    print(f"[kcd-mcp] exec: {' '.join(cmd)}", file=sys.stderr)
    proc = subprocess.run(cmd, capture_output=True, text=True, env=os.environ.copy())
    if not proc.stdout.strip():
        return {
            "ok": False,
            "error": {
                "code": "no_output",
                "message": (
                    f"kcd produced no stdout (exit {proc.returncode}). "
                    f"stderr: {proc.stderr.strip()[:_STDERR_CAP]}"
                ),
            },
        }
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        return {
            "ok": False,
            "error": {
                "code": "bad_json",
                "message": (
                    f"kcd stdout was not valid JSON: {e}. "
                    f"raw: {proc.stdout[:_STDERR_CAP]}"
                ),
            },
        }


# ---------------------------------------------------------------------------
# project (discovery)
# ---------------------------------------------------------------------------

@mcp.tool()
def kcd_project_current() -> dict[str, Any]:
    """List documents currently open in KiCad — boards, schematics, projects.

    Use this as the FIRST call in an agentic session to find out what to drive.
    Returns ipc_unavailable if KiCad isn't running or no editor is loaded.
    """
    return _run(["project", "current"])


# ---------------------------------------------------------------------------
# snapshot
# ---------------------------------------------------------------------------

@mcp.tool()
def kcd_snapshot_create(project: str, message: str) -> dict[str, Any]:
    """Create a named snapshot of the KiCad project. Returns the new commit SHA."""
    return _run(["snapshot", "create", project, "-m", message])


@mcp.tool()
def kcd_snapshot_list(project: str) -> dict[str, Any]:
    """List recent snapshots for the project, newest first."""
    return _run(["snapshot", "list", project])


@mcp.tool()
def kcd_snapshot_restore(project: str, ref: str) -> dict[str, Any]:
    """Hard-reset the project's working tree to a snapshot ref. Destructive within the project dir."""
    return _run(["snapshot", "restore", project, ref, "--yes"])


@mcp.tool()
def kcd_snapshot_diff(project: str, ref_a: str, ref_b: str | None = None) -> dict[str, Any]:
    """Unified diff between two snapshots, or between ref_a and the working tree."""
    args = ["snapshot", "diff", project, ref_a]
    if ref_b:
        args.append(ref_b)
    return _run(args)


# ---------------------------------------------------------------------------
# inspect
# ---------------------------------------------------------------------------

@mcp.tool()
def kcd_inspect_sch(project: str) -> dict[str, Any]:
    """List all symbols in the schematic (offline, via kicad-skip)."""
    return _run(["inspect", "sch", project])


@mcp.tool()
def kcd_inspect_pcb(project: str | None = None) -> dict[str, Any]:
    """List all footprints on the PCB. Requires KiCad open with the .kicad_pcb file and IPC API enabled.

    If `project` is omitted, kcd auto-detects from the currently-open board.
    """
    args = ["inspect", "pcb"]
    if project:
        args.append(project)
    return _run(args)


@mcp.tool()
def kcd_inspect_ref(project: str, ref: str) -> dict[str, Any]:
    """Look up a component by reference designator. Reads schematic; enriches with PCB info if KiCad is open."""
    return _run(["inspect", "ref", project, ref])


# ---------------------------------------------------------------------------
# edit (schematic — offline)
# ---------------------------------------------------------------------------

def _edit_flags(no_snapshot: bool, no_render: bool) -> list[str]:
    """Translate the optional skip flags to CLI args."""
    out: list[str] = []
    if no_snapshot:
        out.append("--no-snapshot")
    if no_render:
        out.append("--no-render")
    return out


@mcp.tool()
def kcd_edit_value(
    project: str,
    ref: str,
    new_value: str,
    no_snapshot: bool = False,
    no_render: bool = False,
) -> dict[str, Any]:
    """Change a symbol's Value field in the schematic. Auto-snapshots and auto-renders by default.

    Set `no_snapshot=True` to skip the pre-edit snapshot (useful when the snapshot store is misbehaving).
    Set `no_render=True` to skip the post-edit SVG re-render (faster batch edits).
    """
    return _run([
        "edit", "value", project, "--ref", ref, "--value", new_value,
        *_edit_flags(no_snapshot, no_render),
    ])


@mcp.tool()
def kcd_edit_ref(
    project: str,
    old_ref: str,
    new_ref: str,
    no_snapshot: bool = False,
    no_render: bool = False,
) -> dict[str, Any]:
    """Rename a symbol's reference designator. Auto-snapshots and auto-renders by default."""
    return _run([
        "edit", "ref", project, "--from", old_ref, "--to", new_ref,
        *_edit_flags(no_snapshot, no_render),
    ])


@mcp.tool()
def kcd_edit_footprint(
    project: str,
    ref: str,
    footprint: str,
    no_snapshot: bool = False,
    no_render: bool = False,
) -> dict[str, Any]:
    """Set a symbol's Footprint property (lib:fp form, e.g. Resistor_SMD:R_0805_2012Metric)."""
    return _run([
        "edit", "footprint", project, "--ref", ref, "--footprint", footprint,
        *_edit_flags(no_snapshot, no_render),
    ])


@mcp.tool()
def kcd_edit_prop(
    project: str,
    ref: str,
    field: str,
    value: str,
    no_snapshot: bool = False,
    no_render: bool = False,
) -> dict[str, Any]:
    """Set or create an arbitrary property on a symbol (e.g. MPN, Manufacturer)."""
    return _run([
        "edit", "prop", project, "--ref", ref, "--field", field, "--value", value,
        *_edit_flags(no_snapshot, no_render),
    ])


@mcp.tool()
def kcd_edit_delete(
    project: str,
    ref: str,
    no_snapshot: bool = False,
    no_render: bool = False,
) -> dict[str, Any]:
    """Delete a symbol from the schematic. Auto-snapshots and auto-renders by default."""
    return _run([
        "edit", "delete", project, "--ref", ref,
        *_edit_flags(no_snapshot, no_render),
    ])


# ---------------------------------------------------------------------------
# edit (PCB — requires KiCad open via IPC)
# ---------------------------------------------------------------------------

@mcp.tool()
def kcd_edit_move_fp(
    ref: str,
    x: float,
    y: float,
    rotation: float | None = None,
    project: str | None = None,
    no_snapshot: bool = False,
) -> dict[str, Any]:
    """Move a footprint on the PCB to (x, y) in mm, optionally rotating.

    Requires KiCad open with PCB editor only — having both editors open at
    once triggers a known KiCad 10.0.2 IPC routing segfault. If `project` is
    omitted, kcd auto-detects from the currently-open board (call
    `kcd_project_current` first to confirm which board that is).
    """
    args = ["edit", "move-fp"]
    if project:
        args.append(project)
    args += ["--ref", ref, "--x", str(x), "--y", str(y)]
    if rotation is not None:
        args += ["--rotation", str(rotation)]
    if no_snapshot:
        args.append("--no-snapshot")
    return _run(args)


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------

@mcp.tool()
def kcd_render_sch(project: str, out: str, fmt: str = "svg") -> dict[str, Any]:
    """Render the schematic to a file. fmt: svg | png | pdf. PNG needs rsvg-convert or inkscape on PATH."""
    return _run(["render", "sch", project, "--out", out, "--format", fmt])


@mcp.tool()
def kcd_render_pcb(project: str, out: str, fmt: str = "svg") -> dict[str, Any]:
    """Render the PCB to a file. fmt: svg | pdf."""
    return _run(["render", "pcb", project, "--out", out, "--format", fmt])


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

@mcp.tool()
def kcd_drc(project: str) -> dict[str, Any]:
    """Run Design Rule Check on the PCB and return the report."""
    return _run(["drc", project])


@mcp.tool()
def kcd_erc(project: str) -> dict[str, Any]:
    """Run Electrical Rule Check on the schematic and return the report."""
    return _run(["erc", project])


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

@mcp.tool()
def kcd_export_bom(project: str, out: str) -> dict[str, Any]:
    """Export bill of materials to CSV."""
    return _run(["export", "bom", project, "--out", out])


@mcp.tool()
def kcd_export_gerber(project: str, out: str) -> dict[str, Any]:
    """Export Gerber manufacturing files to a directory."""
    return _run(["export", "gerber", project, "--out", out])


@mcp.tool()
def kcd_export_step(project: str, out: str) -> dict[str, Any]:
    """Export 3D STEP model of the assembled board."""
    return _run(["export", "step", project, "--out", out])


@mcp.tool()
def kcd_export_pdf(project: str, out: str, target: str = "pcb") -> dict[str, Any]:
    """Export PDF. target: pcb | sch."""
    return _run(["export", "pdf", project, "--out", out, "--target", target])


def main() -> None:
    print(f"[kcd-mcp] starting (python={sys.executable})", file=sys.stderr)
    mcp.run()


if __name__ == "__main__":
    main()
