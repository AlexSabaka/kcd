# Using kcd from an AI agent

This guide is written for Claude Code (and other agentic tools) reading the kcd repo to figure out how to use it. If you're a human, [README.md](../README.md) is friendlier.

## Mental model

`kcd` is a CLI. Every subcommand:
- Reads a KiCad project (via path to `.kicad_pro` file or its directory).
- Either inspects (read-only) or edits (mutating).
- Returns one of two output shapes depending on `--json`.

Mutating commands automatically:
1. Snapshot the project before running.
2. Render the affected sheet/board after running.
3. Return `snapshot_before` so you can roll back if needed.

## The JSON envelope

Every `--json` response has this shape:

```json
{
  "ok": true,
  "command": "edit.value",
  "data": { ... },
  "warnings": ["..."],
  "artifacts": [
    {"kind": "schematic_svg", "path": "/tmp/kcd/board.svg"}
  ],
  "snapshot_before": "abc123...",
  "error": null
}
```

If `ok` is false, `error` will be `{"code": "...", "message": "..."}` and the process exits with status 1.

## Standard agentic loop for an edit

```bash
# 1. Snapshot with a meaningful message so you can find this rollback point later
kcd snapshot create ./proj -m "user asked to swap R5 to 10k" --json

# 2. Read current state so you know what you're changing FROM
kcd inspect ref ./proj R5 --json

# 3. Make the edit (auto-snapshots, auto-renders)
kcd edit value ./proj --ref R5 --value 10k --json

# 4. Read the result image(s) listed in `artifacts` to verify
#    The render lands at /tmp/kcd/<sheet>.svg by default
```

The artifact at `/tmp/kcd/<sheet>.svg` is your visual confirmation that the edit landed. SVG is preferred over PNG because you can grep it for the new value to confirm.

## Reading SVG schematics

KiCad SVGs are self-contained. You can `grep` them for text:

```bash
grep -A1 '>R5<' /tmp/kcd/proj.svg | grep -oP '>\K[^<]+' | head -5
```

For visual inspection, request the PNG variant if your client supports image reading:

```bash
kcd render sch ./proj --out /tmp/r5-check.png --format png --json
```

## When IPC fails

If KiCad isn't running with the PCB open, any `inspect pcb` / `edit move-fp` / `route track` command returns:

```json
{"ok": false, "error": {"code": "ipc_unavailable", "message": "..."}}
```

When you see this, either:
1. Tell the user to open the PCB file in KiCad, then retry.
2. Fall back to schematic-only operations (most `edit *` commands work offline via kicad-skip).

## When edits go wrong

```bash
# List recent snapshots
kcd snapshot list ./proj --json

# Roll back to the snapshot just before your edit
kcd snapshot restore ./proj <ref> --yes --json
```

The `--yes` flag skips the interactive confirmation (necessary for agentic use).

## Anti-patterns to avoid

- **Don't skip the snapshot.** Every mutating command auto-snapshots, but if you're doing a multi-step plan, also create a *named* snapshot at the start with a good message.
- **Don't trust `data.updated` without re-rendering.** kicad-skip writes to disk, but the way KiCad renders the result can surprise you. Always check the artifact.
- **Don't loop on `inspect pcb` to detect when KiCad opens** — that's a polling antipattern. If IPC fails once, ask the user to open KiCad.
- **Don't manually edit `.kicad_pro`, `.kicad_sch`, or `.kicad_pcb` files** outside kcd — you'll bypass snapshots.

## External-edit caveats

kcd writes to project files via two different paths — `kicad-skip` for schematic edits (works offline, no KiCad IPC needed) and `kipy` IPC for PCB edits (needs KiCad open). Both interact with the running KiCad app in ways the user should be primed for:

- **Schematic edits while KiCad's schematic editor is open** trigger a *"file modified externally — reload?"* prompt in KiCad on next focus. Expected behavior: kcd writes the `.kicad_sch` directly, KiCad's in-editor copy doesn't know. Tell the user to accept the reload. If the user wants to avoid the prompt entirely, ask them to close the schematic editor before agentic schematic-edit sessions (the PCB editor staying open is fine).

- **`edit move-fp` calls `board.save()` unconditionally.** kipy 0.7.1 exposes no `is_dirty` / `has_unsaved_changes` API, so kcd can't tell whether the user has unsaved changes in the PCB editor before saving. Any unsaved edits the user has open *will* be persisted along with the agent's footprint move. The `move-fp` envelope always carries a warning to that effect — surface it to the user. Practical guidance: tell the user to save (Ctrl/Cmd-S) or revert their in-editor changes before kicking off an agent that runs `edit move-fp`.

- **Don't have both the schematic editor and PCB editor open at the same time** while running IPC commands. KiCad 10.0.2 has a known IPC-routing segfault when multiple editors are loaded. Keep PCB-only for `inspect pcb` / `edit move-fp` / `route track` work; close the schematic editor first.

## Subcommand cheat sheet for agents

```
# Foundation
kcd snapshot create|list|restore|diff <proj> [--json]

# See
kcd render sch <proj> --out <file> [--format svg|png|pdf] [--json]
kcd render pcb <proj> --out <file> [--format svg|pdf] [--json]
kcd render 3d  <proj> --out <file> [--side top|bottom] [--json]

# Read
kcd inspect sch <proj> [--json]
kcd inspect pcb <proj> [--json]                  # needs KiCad open
kcd inspect ref <proj> <REF> [--json]

# Net
kcd net list <proj> [--json]                     # named nets in the schematic
kcd net pcb  [<proj>] [--json]                   # board nets + pad/track counts; needs KiCad open
kcd net of   [<proj>] --net <NET> [--json]       # pads/tracks/vias/zones on a net; needs KiCad open
kcd net trace <proj> --net <NET> [--json]        # schematic label/global net -> component pins

# Library
kcd lib show <Library:Symbol> [--project <proj>] [--json]   # pins, properties, source file
kcd lib list [--project <proj>] [--json]                    # symbol libraries kcd can resolve

# Change (schematic - works offline)
kcd edit value     <proj> --ref R5 --value 10k [--json]
kcd edit ref       <proj> --from R5 --to R10 [--json]
kcd edit footprint <proj> --ref U1 --footprint <lib:fp> [--json]
kcd edit prop      <proj> --ref U1 --field MPN --value LM358 [--json]
kcd edit delete    <proj> --ref C3 [--json]

# Change (PCB - needs KiCad open via IPC)
kcd edit move-fp <proj> --ref R5 --x 100 --y 50 [--rotation 90] [--json]

# Validate
kcd drc    <proj> [--json]
kcd erc    <proj> [--json]
kcd parity <proj> [--json]                       # schematic ↔ PCB ref drift
kcd sync   <proj> [--check] [--json]             # export netlist; --check diffs vs live PCB

# Analyze (knowledge-layer; vendored kicad-happy, read-only)
kcd analyze sch     <proj>        [--out <file>] [--json]
kcd analyze pcb     <proj>        [--out <file>] [--json]
kcd analyze gerbers <gerber-dir>  [--out <file>] [--json]

# Route
kcd route track <proj> --net VCC --from 100,50 --to 110,50 --layer F.Cu --width 0.25
kcd route freeroute <proj> --dsn proj.dsn --out-ses proj.ses --passes 100

# Export
kcd export gerber <proj> --out ./gerbers/
kcd export bom    <proj> --out bom.csv
kcd export step   <proj> --out board.step
kcd export pdf    <proj> --out board.pdf --target pcb|sch
```
