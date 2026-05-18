# Brief: stand up `kcd` from Dove's PoC

## Why we're here

reflow-mcp turned out to be hollow scaffolding under a clean manifest — even after the naming-compliance + schema-honesty pass we just landed, Dove probed it and confirmed: the dispatch shell exists, but every tool's handler is a no-op echo (returns `"accepted by the reflow dispatch layer"` with the input mirrored back), and most "real" parameter schemas are still uninformative. Decision: stop sinking time there, build our own KiCad harness narrowly tailored to the agent-driven workflow.

Dove → Sabaka brainstorm → Dove scaffolded a complete PoC. Your job: stand it up, verify it works against real KiCad, then iterate.

## What you're inheriting

A tarball `kcd-0.1.0.tar.gz` (~2260 LOC, 9/9 smoke tests passing per Dove). Sabaka has it in his downloads / desktop; ask if you can't find it.

Layout:

```
kcd/
├── LICENSE, README.md, CHANGELOG.md
├── pyproject.toml         hatchling, deps, ruff/pytest
├── docs/{agents.md,routing.md}
├── src/kcd/
│   ├── cli.py             typer app, mounts subcommand groups
│   ├── core/              config, output envelope, project resolve,
│   │                      kipy IPC helper, git-backed snapshots
│   ├── adapters/          kicad_cli (subprocess), kipy_pcb (live IPC),
│   │                      skip_sch (offline S-expr), freerouting
│   └── commands/          one module per subcommand group
└── tests/test_smoke.py    no-KiCad-required scaffolding tests
```

**Working & tested (no KiCad needed):** snapshot lifecycle (create/list/restore/diff with real file restoration), CLI argv + `--json` envelope, exit codes, config + project resolution, result envelope with artifacts/warnings/snapshot_before/errors.

**Code complete, needs KiCad 10 + kipy to exercise:** all `kicad-cli` wrappers (render sch/pcb/3d, DRC, ERC, gerber/drill/bom/step/pos/pdf), kicad-skip edits (value/ref/footprint/prop/delete), kipy PCB inspect + move_footprint + add_track, FreeRouting orchestration.

**Explicitly v2:** diff-pair length tuning (kipy doesn't expose), full hierarchical net tracing (v1 ships a label-match stub that emits a warning), headless DSN export (KiCad 10 `kicad-cli` coverage uneven — manual step documented in `docs/routing.md`).

## First moves

```bash
tar xzf kcd-0.1.0.tar.gz
cd kcd
sed -i '' 's|YOUR-USERNAME|oaslananka|g' pyproject.toml   # darwin sed: -i ''
pip install -e ".[dev]"
pytest                                                     # expect 9/9
```

Then the real moment of truth — open KiCad 10, open any board file, in a separate terminal:

```bash
PYTHONPATH=src python -m kcd inspect pcb /path/to/some.kicad_pro --json
```

Footprints come back → IPC path works on this machine, Sabaka can iterate.
`ipc_unavailable` → the error tells you whether kipy isn't installed or KiCad isn't reachable; fix that before doing anything else.

After that lands, the headline demo to validate the abstraction:

```bash
kcd inspect ref ./proj R5 --json
kcd edit value ./proj --ref R5 --value 10k --json     # auto-snapshots + re-renders SVG
# response: snapshot_before id + artifacts pointing at /tmp/kcd/*.svg
# read the SVG, confirm the value swap
kcd snapshot restore ./proj <snapshot_before> --yes   # rollback path
```

## Edges Dove flagged

| Thing | Where it bites |
|---|---|
| `kipy_pcb.add_track` uses kipy ≥0.5 shape (`Track()`, `Vector2.from_xy()`, `board.create_items()`). API drifts. | First thing to fix if a real `add_track` errors. Smoke tests don't cover it. |
| `kicad-cli sch export bom --group-by` field names drift between KiCad 10 point releases. | If `kcd export bom` complains, this is the spot. |
| `kcd render sch --format png` needs `rsvg-convert` **or** `inkscape` on PATH. | Error message tells the user. PDF and SVG don't need rasterizers. |
| `KCD_FREEROUTING_JAR` env var required before `kcd route freeroute` works. | Documented in `docs/routing.md`. |
| `pyproject.toml` ships with `YOUR-USERNAME` placeholder. | First-moves sed fixes it. |

## Out of scope

- **reflow-mcp.** Dead. Don't try to integrate, don't reference, don't borrow code. The naming/schema pass we did there will sit in the repo as a tombstone; not our problem anymore.
- **Polishing the v2 items** (diff-pair tuning, full net tracing, headless DSN). v1 ships the stubs; expand only if a real workflow demands it.
- **MCP server wrapping.** `kcd` is a CLI-first tool. Claude Code drives it via Bash. If we later want an MCP face for it, that's a separate session — don't pre-build it.
