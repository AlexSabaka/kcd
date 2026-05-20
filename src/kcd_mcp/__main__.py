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
import tempfile
from typing import Any

from mcp.server.fastmcp import FastMCP, Image

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
    """Hard-reset the project's working tree to a snapshot ref.

    Destructive within the project directory.
    """
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
    """List all footprints on the PCB. Requires KiCad open with the .kicad_pcb.

    Needs KiCad's IPC API enabled. If `project` is omitted, kcd auto-detects
    from the currently-open board.
    """
    args = ["inspect", "pcb"]
    if project:
        args.append(project)
    return _run(args)


@mcp.tool()
def kcd_inspect_ref(project: str, ref: str) -> dict[str, Any]:
    """Look up a component by reference designator.

    Reads the schematic; enriches with PCB info if KiCad is open.
    """
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
    """Change a symbol's Value field in the schematic.

    Auto-snapshots and auto-renders by default. Set `no_snapshot=True` to skip
    the pre-edit snapshot; `no_render=True` skips the post-edit SVG re-render
    (faster batch edits).
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


@mcp.tool()
def kcd_edit_wire_add(
    project: str,
    from_xy: str,
    to_xy: str,
    no_snapshot: bool = False,
    no_render: bool = False,
) -> dict[str, Any]:
    """Add a wire segment to the root schematic sheet between two points.

    `from_xy` / `to_xy` are 'X,Y' millimetre coordinates, e.g. "100,50".
    """
    return _run([
        "edit", "wire", "add", project, "--from", from_xy, "--to", to_xy,
        *_edit_flags(no_snapshot, no_render),
    ])


@mcp.tool()
def kcd_edit_wire_delete(
    project: str,
    from_xy: str,
    to_xy: str,
    no_snapshot: bool = False,
    no_render: bool = False,
) -> dict[str, Any]:
    """Delete the wire with the given endpoints (either direction) from the root sheet.

    `from_xy` / `to_xy` are 'X,Y' millimetre coordinates.
    """
    return _run([
        "edit", "wire", "delete", project, "--from", from_xy, "--to", to_xy,
        *_edit_flags(no_snapshot, no_render),
    ])


@mcp.tool()
def kcd_edit_netlabel_add(
    project: str,
    text: str,
    at: str,
    rotation: float = 0.0,
    is_global: bool = False,
    no_snapshot: bool = False,
    no_render: bool = False,
) -> dict[str, Any]:
    """Add a local or global net label on the root schematic sheet.

    `at` is an 'X,Y' millimetre coordinate. Set `is_global=True` for a global
    label (default is a local label).
    """
    args = ["edit", "netlabel", "add", project, "--text", text, "--at", at,
            "--rotation", str(rotation)]
    if is_global:
        args.append("--global")
    return _run([*args, *_edit_flags(no_snapshot, no_render)])


@mcp.tool()
def kcd_edit_netlabel_delete(
    project: str,
    text: str,
    at: str | None = None,
    no_snapshot: bool = False,
    no_render: bool = False,
) -> dict[str, Any]:
    """Delete a net label by text from the root schematic sheet.

    Pass `at` ('X,Y' in mm) to disambiguate when several labels share the name.
    """
    args = ["edit", "netlabel", "delete", project, "--text", text]
    if at:
        args += ["--at", at]
    return _run([*args, *_edit_flags(no_snapshot, no_render)])


@mcp.tool()
def kcd_edit_add_symbol(
    project: str,
    lib_id: str,
    ref: str,
    value: str | None = None,
    at: str | None = None,
    no_snapshot: bool = False,
    no_render: bool = False,
) -> dict[str, Any]:
    """Add a component to the root schematic sheet.

    `lib_id` is Library:Symbol (e.g. "Device:C"). If the project already has
    that part type an existing instance is cloned; otherwise the symbol is
    resolved from a library and embedded. `at` is an optional 'X,Y' in mm.
    """
    args = ["edit", "add-symbol", project, "--lib-id", lib_id, "--ref", ref]
    if value is not None:
        args += ["--value", value]
    if at:
        args += ["--at", at]
    return _run([*args, *_edit_flags(no_snapshot, no_render)])


@mcp.tool()
def kcd_edit_symbol(
    project: str,
    ref: str,
    to_lib_id: str,
    pin_map: str | None = None,
    no_snapshot: bool = False,
    no_render: bool = False,
) -> dict[str, Any]:
    """Swap a placed symbol for a different library part.

    `to_lib_id` is the new Library:Symbol. When the pin sets differ, pass
    `pin_map` as "old=new,old=new" to confirm the remap. Wires the swap leaves
    dangling are reported in the result's warnings (kcd does not reroute).
    """
    args = ["edit", "symbol", project, "--ref", ref, "--to-lib-id", to_lib_id]
    if pin_map:
        args += ["--pin-map", pin_map]
    return _run([*args, *_edit_flags(no_snapshot, no_render)])


@mcp.tool()
def kcd_edit_net(
    project: str,
    old_name: str,
    new_name: str,
    no_snapshot: bool = False,
    no_render: bool = False,
) -> dict[str, Any]:
    """Rename a net across the schematic — labels, global labels, power symbols.

    Power nets are renamed lib_id-aware (the power symbol's lib_id is repointed
    to power:<new> so the rename survives a library resync). Root sheet only.
    The PCB is not renamed — KiCad 10 has no headless forward annotation; the
    result reports whether the board still carries the old net name.
    """
    return _run([
        "edit", "net", project, "--from", old_name, "--to", new_name,
        *_edit_flags(no_snapshot, no_render),
    ])


@mcp.tool()
def kcd_edit_text_titleblock(
    project: str,
    field: str,
    value: str,
    no_snapshot: bool = False,
    no_render: bool = False,
) -> dict[str, Any]:
    """Set a title-block field on the root schematic sheet.

    `field` is one of title, company, rev, date, or comment1..comment9. The
    title block is created if the sheet has none.
    """
    return _run([
        "edit", "text", "titleblock", project, "--field", field,
        "--value", value, *_edit_flags(no_snapshot, no_render),
    ])


@mcp.tool()
def kcd_edit_text_set(
    project: str,
    match: str,
    to: str,
    at: str | None = None,
    no_snapshot: bool = False,
    no_render: bool = False,
) -> dict[str, Any]:
    """Replace a free graphic text item on the root schematic sheet.

    Matches a (text ...) annotation by its current string `match`; pass `at`
    ('X,Y' in mm) to disambiguate when several share the text. Net labels are
    not affected — use kcd_edit_netlabel_* / kcd_edit_net for those.
    """
    args = ["edit", "text", "set", project, "--match", match, "--to", to]
    if at:
        args += ["--at", at]
    return _run([*args, *_edit_flags(no_snapshot, no_render)])


@mcp.tool()
def kcd_edit_designrules(
    project: str,
    rule: str,
    value: str,
    force: bool = False,
    no_snapshot: bool = False,
) -> dict[str, Any]:
    """Set a board design-rule constraint in the .kicad_pro file.

    `rule` is a board.design_settings.rules key (e.g. min_track_width,
    min_clearance, min_via_diameter); `value` is mm for distances, true/false
    for flags. Call with an unknown rule to see the valid keys.

    Refuses with `project_open_in_kicad` when KiCad has the project loaded —
    its cached settings would overwrite the edit on the next save; set
    `force=True` to write anyway.
    """
    args = ["edit", "designrules", project, "--rule", rule, "--value", value]
    if force:
        args.append("--force")
    if no_snapshot:
        args.append("--no-snapshot")
    return _run(args)


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


@mcp.tool()
def kcd_edit_delete_fp(
    ref: str,
    project: str | None = None,
    no_snapshot: bool = False,
) -> dict[str, Any]:
    """Delete a footprint from the PCB by reference designator.

    The board-side counterpart of `kcd_edit_delete` (schematic-only) — use it
    to remove orphan footprints that have no schematic backing. Deleting a
    footprint that has a schematic symbol opens schematic↔PCB drift kcd can't
    reconcile; the result warns when it detects that.

    Requires KiCad open with PCB editor only — having both editors open at
    once triggers a known KiCad 10.0.2 IPC routing segfault. If `project` is
    omitted, kcd auto-detects from the currently-open board. Calls
    board.save() — persists any unsaved PCB-editor changes too.
    """
    args = ["edit", "delete-fp"]
    if project:
        args.append(project)
    args += ["--ref", ref]
    if no_snapshot:
        args.append("--no-snapshot")
    return _run(args)


@mcp.tool()
def kcd_edit_track_delete(
    net: str | None = None,
    from_xy: str | None = None,
    to_xy: str | None = None,
    layer: str | None = None,
    project: str | None = None,
    no_snapshot: bool = False,
) -> dict[str, Any]:
    """Delete copper tracks on the PCB. Requires KiCad open with the PCB editor.

    Select a whole net with `net`, or one segment with `from_xy`/`to_xy`
    ('X,Y' in mm, either direction); `layer` (e.g. "F.Cu") narrows either.
    Calls board.save() — persists any unsaved PCB-editor changes too.
    """
    args = ["edit", "track", "delete"]
    if project:
        args.append(project)
    if net:
        args += ["--net", net]
    if from_xy:
        args += ["--from", from_xy]
    if to_xy:
        args += ["--to", to_xy]
    if layer:
        args += ["--layer", layer]
    if no_snapshot:
        args.append("--no-snapshot")
    return _run(args)


@mcp.tool()
def kcd_edit_track_modify(
    width: float | None = None,
    set_layer: str | None = None,
    set_net: str | None = None,
    net: str | None = None,
    from_xy: str | None = None,
    to_xy: str | None = None,
    layer: str | None = None,
    project: str | None = None,
    no_snapshot: bool = False,
) -> dict[str, Any]:
    """Modify copper tracks on the PCB — width, layer, or net assignment.

    Selection (`net` / `from_xy`+`to_xy` / `layer`) is separate from the
    changes (`width` in mm / `set_layer` / `set_net`); pass at least one of
    each. Requires KiCad open with the PCB editor; calls board.save().
    """
    args = ["edit", "track", "modify"]
    if project:
        args.append(project)
    if net:
        args += ["--net", net]
    if from_xy:
        args += ["--from", from_xy]
    if to_xy:
        args += ["--to", to_xy]
    if layer:
        args += ["--layer", layer]
    if width is not None:
        args += ["--width", str(width)]
    if set_layer:
        args += ["--set-layer", set_layer]
    if set_net:
        args += ["--set-net", set_net]
    if no_snapshot:
        args.append("--no-snapshot")
    return _run(args)


@mcp.tool()
def kcd_edit_via_add(
    net: str,
    at: str,
    diameter: float = 0.6,
    drill: float = 0.3,
    project: str | None = None,
    no_snapshot: bool = False,
) -> dict[str, Any]:
    """Add a through-via to the PCB. Requires KiCad open with the PCB editor.

    `at` is an 'X,Y' millimetre coordinate. `diameter` / `drill` are in mm
    (defaults 0.6 / 0.3). Blind/buried vias are not supported. Calls
    board.save() — persists any unsaved PCB-editor changes too.
    """
    args = ["edit", "via", "add"]
    if project:
        args.append(project)
    args += ["--net", net, "--at", at,
             "--diameter", str(diameter), "--drill", str(drill)]
    if no_snapshot:
        args.append("--no-snapshot")
    return _run(args)


@mcp.tool()
def kcd_edit_zone_add(
    net: str,
    layer: str,
    rect: str,
    priority: int = 0,
    clearance: float | None = None,
    project: str | None = None,
    no_snapshot: bool = False,
) -> dict[str, Any]:
    """Add a rectangular copper-pour zone to the PCB.

    `rect` is the corner rectangle 'x1,y1,x2,y2' in mm; `layer` e.g. "F.Cu".
    `clearance` (mm) is an optional local clearance. Requires KiCad open with
    the PCB editor; KiCad refills all zones. Calls board.save().
    """
    args = ["edit", "zone", "add"]
    if project:
        args.append(project)
    args += ["--net", net, "--layer", layer, "--rect", rect,
             "--priority", str(priority)]
    if clearance is not None:
        args += ["--clearance", str(clearance)]
    if no_snapshot:
        args.append("--no-snapshot")
    return _run(args)


@mcp.tool()
def kcd_edit_zone_delete(
    net: str | None = None,
    layer: str | None = None,
    project: str | None = None,
    no_snapshot: bool = False,
) -> dict[str, Any]:
    """Delete copper zones from the PCB. Requires KiCad open with the PCB editor.

    Zones have no endpoints — select by `net` and/or `layer` (at least one).
    Calls board.save() — persists any unsaved PCB-editor changes too.
    """
    args = ["edit", "zone", "delete"]
    if project:
        args.append(project)
    if net:
        args += ["--net", net]
    if layer:
        args += ["--layer", layer]
    if no_snapshot:
        args.append("--no-snapshot")
    return _run(args)


# ---------------------------------------------------------------------------
# net (connectivity queries)
# ---------------------------------------------------------------------------

@mcp.tool()
def kcd_net_list(project: str) -> dict[str, Any]:
    """List all named nets (labels, global labels, power) in the schematic. Offline."""
    return _run(["net", "list", project])


@mcp.tool()
def kcd_net_pcb(project: str | None = None) -> dict[str, Any]:
    """List nets present on the PCB. Requires KiCad open with the .kicad_pcb.

    If `project` is omitted, kcd auto-detects from the currently-open board.
    """
    args = ["net", "pcb"]
    if project:
        args.append(project)
    return _run(args)


@mcp.tool()
def kcd_net_of(net: str, project: str | None = None) -> dict[str, Any]:
    """List everything on a net on the PCB — pads, tracks, vias, zones.

    Answers "what is on net X" for the board. Requires KiCad open with the
    .kicad_pcb. For the schematic-side answer use kcd_net_trace.
    """
    args = ["net", "of"]
    if project:
        args.append(project)
    args += ["--net", net]
    return _run(args)


@mcp.tool()
def kcd_net_trace(project: str, net: str) -> dict[str, Any]:
    """Trace a net through the schematic — the component pins on it. Offline.

    Resolves label / global-label nets to symbol pins. For PCB-side membership,
    and for power nets, use kcd_net_of.
    """
    return _run(["net", "trace", project, "--net", net])


# ---------------------------------------------------------------------------
# lib (symbol-library inspection)
# ---------------------------------------------------------------------------

@mcp.tool()
def kcd_lib_show(lib_id: str, project: str | None = None) -> dict[str, Any]:
    """Resolve a symbol and show its pins, properties, and source library file.

    `lib_id` is Library:Symbol (e.g. "Device:R"). `project` is needed only for
    project-local libraries.
    """
    args = ["lib", "show", lib_id]
    if project:
        args += ["--project", project]
    return _run(args)


@mcp.tool()
def kcd_lib_list(project: str | None = None) -> dict[str, Any]:
    """List the symbol libraries kcd can resolve.

    Pass `project` to also include its sym-lib-table.
    """
    args = ["lib", "list"]
    if project:
        args += ["--project", project]
    return _run(args)


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------

# An inline preview image must stay under the 1MB MCP result cap. A PNG at the
# 150-dpi preview resolution is comfortably below this; the guard skips
# inlining (rather than hard-failing the whole tool call) on the rare overrun.
_IMAGE_CAP = 900_000


def _render_preview(args: list[str]) -> str | None:
    """Render a low-res PNG preview to a temp file; return its path or None.

    `args` is a `kcd render ...` arg list *without* `--out`. Used so the agent
    receives an inline image even when it asked for an SVG/PDF on disk.
    """
    fd, tmp = tempfile.mkstemp(suffix=".png", prefix="kcd-preview-")
    os.close(fd)
    env = _run([*args, "--out", tmp])
    if env.get("ok") and os.path.isfile(tmp) and os.path.getsize(tmp) > 0:
        return tmp
    return None


def _attach_image(env: dict[str, Any], png_path: str | None) -> Any:
    """Return `[envelope, Image]` when a usable PNG exists, else the envelope.

    In MCP-remote operation the agent never sees a render written to the
    operator's disk; returning the bytes as an `ImageContent` block is the
    only way it can see its own render (Round-3 field report B3).
    """
    if not png_path or not os.path.isfile(png_path):
        return env
    size = os.path.getsize(png_path)
    if size == 0:
        return env
    if size > _IMAGE_CAP:
        env.setdefault("warnings", []).append(
            f"render preview is {size} bytes — too large to inline; "
            "open the artifact path on the operator's disk instead."
        )
        return env
    with open(png_path, "rb") as fh:
        raw = fh.read()
    return [env, Image(data=raw, format="png")]


@mcp.tool(structured_output=False)
def kcd_render_sch(project: str, out: str, fmt: str = "svg") -> Any:
    """Render the schematic and return an inline PNG preview.

    fmt: svg | png | pdf — written to `out` on disk. An inline PNG preview is
    also returned so the agent can see the render directly. PNG rasterization
    is handled by the bundled resvg engine — no external tools needed.
    """
    env = _run(["render", "sch", project, "--out", out, "--format", fmt])
    if not env.get("ok"):
        return env
    preview = out if fmt == "png" else _render_preview(
        ["render", "sch", project, "--format", "png", "--dpi", "150"]
    )
    return _attach_image(env, preview)


@mcp.tool(structured_output=False)
def kcd_render_pcb(project: str, out: str, fmt: str = "svg") -> Any:
    """Render the PCB (flat 2D layer view) and return an inline PNG preview.

    fmt: svg | pdf | png — written to `out` on disk. An inline PNG preview is
    also returned so the agent can see the render directly.
    """
    env = _run(["render", "pcb", project, "--out", out, "--format", fmt])
    if not env.get("ok"):
        return env
    preview = out if fmt == "png" else _render_preview(
        ["render", "pcb", project, "--format", "png", "--dpi", "150"]
    )
    return _attach_image(env, preview)


@mcp.tool(structured_output=False)
def kcd_render_3d(project: str, out: str, side: str = "top") -> Any:
    """Render a photorealistic 3D image of the PCB and return it inline.

    `side`: top | bottom | front | back | left | right. The render is written
    to `out` on disk and also returned as an inline image.
    """
    env = _run(["render", "3d", project, "--out", out, "--side", side])
    if not env.get("ok"):
        return env
    return _attach_image(env, out)


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

@mcp.tool()
def kcd_drc(project: str, full: bool = False) -> dict[str, Any]:
    """Run Design Rule Check on the PCB and return a folded report.

    Violations are grouped by (type, severity) with a small per-group sample
    inline; set `full=True` to inline every occurrence. The complete report
    is always written to the artifact file regardless.
    """
    args = ["drc", project]
    if full:
        args.append("--full")
    return _run(args)


@mcp.tool()
def kcd_erc(project: str, full: bool = False) -> dict[str, Any]:
    """Run Electrical Rule Check on the schematic and return a folded report.

    Violations are grouped by (type, severity) with a small per-group sample
    inline; set `full=True` to inline every occurrence. The complete report
    is always written to the artifact file regardless.
    """
    args = ["erc", project]
    if full:
        args.append("--full")
    return _run(args)


@mcp.tool()
def kcd_parity(project: str) -> dict[str, Any]:
    """Diff the schematic against the PCB — references on one side only, plus
    value / footprint mismatches on the intersection.

    Requires KiCad open with the .kicad_pcb for PCB-side data; degrades to a
    schematic-only listing with a warning if IPC is unavailable.
    """
    return _run(["parity", project])


@mcp.tool()
def kcd_sync(project: str, check: bool = False, out: str | None = None) -> dict[str, Any]:
    """Export the schematic netlist and (with check=True) report PCB drift.

    `sync` works offline and emits the netlist plus instructions for KiCad's
    F8 "Update PCB from Schematic" (kcd cannot push headlessly). `check=True`
    additionally diffs the netlist against the live PCB — components to
    add/remove and net-membership changes — and needs KiCad open.
    """
    args = ["sync", project]
    if check:
        args.append("--check")
    if out:
        args += ["--out", out]
    return _run(args)


# ---------------------------------------------------------------------------
# analyze (knowledge-layer, read-only)
# ---------------------------------------------------------------------------

@mcp.tool()
def kcd_analyze_sch(project: str, out: str | None = None) -> dict[str, Any]:
    """Analyze the schematic — components, BOM, nets, rails, filters,
    regulators, decoupling adequacy, validation findings. Read-only, offline.

    High-severity findings surface in the envelope warnings; raw JSON is saved
    as an artifact (override the path with `out`).
    """
    args = ["analyze", "sch", project]
    if out:
        args += ["--out", out]
    return _run(args)


@mcp.tool()
def kcd_analyze_pcb(
    project: str, full: bool = False, out: str | None = None
) -> dict[str, Any]:
    """Analyze the PCB — footprints, layers, nets, tracks, vias, decoupling
    placement, ground domains, DFM summary. Read-only; does NOT need KiCad open.

    Set `full=True` for the deeper (slower) analysis pass.
    """
    args = ["analyze", "pcb", project]
    if full:
        args.append("--full")
    if out:
        args += ["--out", out]
    return _run(args)


@mcp.tool()
def kcd_analyze_gerbers(directory: str, out: str | None = None) -> dict[str, Any]:
    """Analyze a directory of gerber + drill files for manufacturability.

    `directory` is a gerber output directory (e.g. from kcd_export_gerber).
    """
    args = ["analyze", "gerbers", directory]
    if out:
        args += ["--out", out]
    return _run(args)


@mcp.tool()
def kcd_analyze_cross(project: str, out: str | None = None) -> dict[str, Any]:
    """Cross-domain schematic-to-PCB analysis — connector current, ESD gaps,
    decoupling adequacy, schematic/PCB consistency.

    Runs the schematic and PCB analyzers internally; needs both files present.
    """
    args = ["analyze", "cross", project]
    if out:
        args += ["--out", out]
    return _run(args)


@mcp.tool()
def kcd_analyze_thermal(
    project: str, ambient: float | None = None, out: str | None = None
) -> dict[str, Any]:
    """Thermal analysis — junction temperatures and thermal-via adequacy.

    Runs the schematic and PCB analyzers internally. `ambient` sets the
    ambient temperature in degrees C.
    """
    args = ["analyze", "thermal", project]
    if ambient is not None:
        args += ["--ambient", str(ambient)]
    if out:
        args += ["--out", out]
    return _run(args)


@mcp.tool()
def kcd_analyze_fab_gate(
    project: str, strict: bool = False, out: str | None = None
) -> dict[str, Any]:
    """Ready-for-fab gate — structured pass/fail checks over the whole design
    (routing, BOM, DFM, rule-check readiness).

    Runs the schematic and PCB analyzers internally. `strict=True` fails the
    gate on warnings, not just errors.
    """
    args = ["analyze", "fab-gate", project]
    if strict:
        args.append("--strict")
    if out:
        args += ["--out", out]
    return _run(args)


@mcp.tool()
def kcd_analyze_whatif(
    project: str,
    changes: list[str] | None = None,
    suggest_fixes: bool = False,
    out: str | None = None,
) -> dict[str, Any]:
    """What-if parameter sweep over the schematic.

    `changes` is a list of component-value overrides (e.g. ["R1=10k",
    "C3=100n"]). Pass at least one change or `suggest_fixes=True`.
    """
    args = ["analyze", "whatif", project, *(changes or [])]
    if suggest_fixes:
        args.append("--suggest-fixes")
    if out:
        args += ["--out", out]
    return _run(args)


@mcp.tool()
def kcd_analyze_lifecycle(
    project: str, temp_range: str | None = None, out: str | None = None
) -> dict[str, Any]:
    """Component lifecycle + temperature audit — BOM obsolescence (EOL/NRND)
    and temperature-range fit.

    Queries distributor APIs; needs DIGIKEY_CLIENT_ID / MOUSER_API_KEY / LCSC
    credentials in the environment, else degrades to offline checks. Set
    `temp_range` to a preset (commercial/industrial/extended/automotive/
    military) or "min,max".
    """
    args = ["analyze", "lifecycle", project]
    if temp_range:
        args += ["--temp-range", temp_range]
    if out:
        args += ["--out", out]
    return _run(args)


@mcp.tool()
def kcd_analyze_diff(
    base: str, head: str, out: str | None = None
) -> dict[str, Any]:
    """Diff two analyzer JSON runs — component, signal, and finding deltas.

    `base` and `head` are JSON files produced by earlier kcd_analyze_* runs
    (saved as envelope artifacts).
    """
    args = ["analyze", "diff", base, head]
    if out:
        args += ["--out", out]
    return _run(args)


# ---------------------------------------------------------------------------
# route
# ---------------------------------------------------------------------------

@mcp.tool()
def kcd_route_track(
    net: str,
    from_xy: str,
    to_xy: str,
    layer: str = "F.Cu",
    width: float = 0.25,
    project: str | None = None,
    no_snapshot: bool = False,
) -> dict[str, Any]:
    """Add a single straight copper track between two points. Requires KiCad
    open with the PCB editor.

    `from_xy` / `to_xy` are 'X,Y' millimetre coordinates; `width` is in mm.
    """
    args = ["route", "track"]
    if project:
        args.append(project)
    args += ["--net", net, "--from", from_xy, "--to", to_xy,
             "--layer", layer, "--width", str(width)]
    if no_snapshot:
        args.append("--no-snapshot")
    return _run(args)


@mcp.tool()
def kcd_route_freeroute(
    project: str,
    dsn: str | None = None,
    out_ses: str | None = None,
    passes: int = 100,
    opt_passes: int = 20,
    timeout: int = 600,
) -> dict[str, Any]:
    """Autoroute a board with FreeRouting via a .dsn -> .ses round-trip.

    Requires a FreeRouting JAR (KCD_FREEROUTING_JAR env var) and a Specctra
    .dsn exported from KiCad. `dsn` / `out_ses` default to <project>.dsn /
    <project>.ses next to the project. Import the resulting .ses back into
    KiCad manually (File -> Import -> Specctra Session).
    """
    args = ["route", "freeroute", project]
    if dsn:
        args += ["--dsn", dsn]
    if out_ses:
        args += ["--out-ses", out_ses]
    args += ["--passes", str(passes), "--opt-passes", str(opt_passes),
             "--timeout", str(timeout)]
    return _run(args)


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


@mcp.tool()
def kcd_export_drill(project: str, out: str) -> dict[str, Any]:
    """Export drill files to a directory."""
    return _run(["export", "drill", project, "--out", out])


@mcp.tool()
def kcd_export_pos(project: str, out: str) -> dict[str, Any]:
    """Export the pick-and-place position file."""
    return _run(["export", "pos", project, "--out", out])


def main() -> None:
    print(f"[kcd-mcp] starting (python={sys.executable})", file=sys.stderr)
    mcp.run()


if __name__ == "__main__":
    main()
