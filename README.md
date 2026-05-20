# kcd — agentic KiCad harness

A small Python CLI that lets [Claude Code](https://docs.claude.com/en/docs/claude-code/overview) (or any agentic AI tool) drive [KiCad 10](https://www.kicad.org/) end-to-end: read schematics, render them so the agent can *see* them, edit values and footprints, run DRC/ERC, route tracks, and export manufacturing files. All commands emit structured JSON for agent consumption and pretty output for humans.

**Status:** alpha. PCB ops work via KiCad 10's IPC (kipy). Schematic ops use [kicad-skip](https://github.com/psychogenic/kicad-skip) for offline edits. Routing is single-track + FreeRouting orchestration; no diff-pair length tuning yet.

## Why this exists

The MCP servers in the wild for KiCad are either read-only (lamaalrajih/kicad-mcp), unfinished scaffolding (oaslananka/reflow-mcp), or proprietary/dead. `kcd` is a thin shim over the tools that already work — `kicad-cli`, `kicad-python` (kipy), `kicad-skip`, `FreeRouting` — exposing them as a single CLI an agent can drive without protocol drama.

Why not an MCP server? Because Claude Code already has a bash tool. MCP adds a protocol layer; a CLI doesn't. If you want MCP, wrap `kcd` in one — the JSON output is designed for it.

## The agentic loop

Every mutating command auto-snapshots first and auto-renders after. So Claude can verify changes happened:

```bash
kcd snapshot create -m "before R5 swap"
kcd render sch ./proj --sheet root --out /tmp/before.png
kcd inspect ref ./proj R5 --json                    # current value
kcd edit value ./proj --ref R5 --value 10k          # snapshots + re-renders
kcd render sch ./proj --sheet root --out /tmp/after.png
# Claude diffs before.png vs after.png to confirm
```

If anything goes wrong: `kcd snapshot restore HEAD~1`.

## Install

```bash
# Prerequisites: KiCad 10 installed, Python 3.11+, git on PATH
pip install kcd
# or, from source:
pip install git+https://github.com/YOUR-USERNAME/kcd.git
```

Optional extras:
- `pip install "kcd[freerouting]"` — adds FreeRouting orchestration support (still requires the FreeRouting JAR on disk; see [docs/routing.md](docs/routing.md))

## Quick reference

```
kcd snapshot create|list|restore|diff
kcd render   sch|pcb|3d
kcd inspect  sch|pcb|ref
kcd lib      show|list                       # symbol-library inspection
kcd edit     value|ref|footprint|prop|delete|wire|netlabel|add-symbol|symbol|net|designrules|track|via|zone
kcd net      list|pcb|of|trace
kcd analyze  sch|pcb|gerbers                # knowledge-layer (vendored kicad-happy)
kcd parity   <proj>                          # schematic ↔ PCB reference drift
kcd sync     <proj> [--check]                # export netlist; --check diffs vs live PCB
kcd drc      [--json]
kcd erc      [--json]
kcd route    track|freeroute|diff-pair|unroute
kcd export   gerber|drill|bom|step|pdf
```

Run `kcd <command> --help` for details on any subcommand.

## For agents (read this if you're Claude Code)

Three rules:

1. **Always pass `--json` when you need to parse output.** Without it, output is pretty-printed for humans.
2. **Snapshot before edits, even though they auto-snapshot.** Use `-m "what you're about to try"`. If you make 3 edits and the last one is wrong, you want the named snapshot from before edit 1.
3. **Re-render after edits and read the image.** The image is your ground truth, not the JSON. Schematic edits land in `.kicad_sch` files but how they *display* depends on KiCad's renderer.

The full agent guide lives in [docs/agents.md](docs/agents.md).

## Caveats (read this before reporting bugs)

- KiCad 10's IPC schematic API is still rough. We use kipy for live ops where it works (especially PCB), and fall back to kicad-skip for offline S-expression edits. Some schematic write operations will warn "via S-expression fallback — reload schematic in KiCad to see changes."
- "Auto-routing" via FreeRouting is a `.dsn` → JAR → `.ses` round trip. Results are deterministic but the export/import dance on KiCad 10 occasionally needs manual confirmation. See [docs/routing.md](docs/routing.md).
- Snapshot uses a git repo `.kcd/` inside the project dir (separate from any project git, so it doesn't pollute your real history). Restore is destructive within the project dir; *that's the point*.
- Tested against KiCad 10.0.x on Linux. macOS likely works. Windows untested.

## Development

```bash
git clone https://github.com/YOUR-USERNAME/kcd
cd kcd
pip install -e ".[dev]"
pytest
```

## License

MIT. See [LICENSE](LICENSE).
