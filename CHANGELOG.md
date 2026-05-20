# Changelog

## [0.1.0] — Unreleased

Initial alpha release.

### Added
- `kcd snapshot create|list|restore|diff` — git-backed per-project snapshots
- `kcd render sch|pcb|3d` — schematic SVG/PDF/PNG, PCB SVG/PDF, 3D PNG render via kicad-cli
- `kcd inspect sch|pcb|ref` — read-only inspection of design state
- `kcd lib show|list` — symbol-library inspection: resolve a `Library:Symbol`
  to its pins/properties/source `.kicad_sym`, or list the libraries kcd can
  resolve (standard KiCad symbol dir + project `sym-lib-table`). Foundation
  for the Wave 4/5 schematic-editing surface
- `kcd edit value|ref|footprint|prop|delete` — offline schematic edits via kicad-skip
- `kcd edit wire add|delete`, `kcd edit netlabel add|delete` — structural
  schematic edits: add/remove wire segments and local/global net labels on
  the root sheet (kicad-skip)
- `kcd edit move-fp` — PCB footprint move via kipy IPC
- `kcd net list|pcb|of|trace` — net queries: `net list` names schematic
  nets, `net pcb` lists board nets with pad/track counts, `net of` returns
  the pads/tracks/vias/zones on a net (`pcb`/`of` via kipy IPC), `net trace`
  resolves a schematic label/global-label net to the component pins on it
  (root sheet; power nets list the declaring power symbols only)
- `kcd parity` — whole-board schematic ↔ PCB drift detection (reference set,
  value mismatches, footprint mismatches; degrades to schematic-only listing
  + warning when KiCad isn't open; fails with `error.code: "wrong_board_open"`
  when KiCad has a different PCB loaded than the requested project)
- `kcd sync` — schematic→PCB forward-annotation bridge: exports the schematic
  netlist and, with `--check`, diffs it against the live PCB — reporting
  components to add/remove and net-membership changes (e.g. a `+12V`→`+BATT`
  rename `parity` is blind to). Cannot push headlessly (KiCad 10 exposes no
  forward-annotation API); emits the F8 "Update PCB from Schematic" instruction
- `kcd analyze sch|pcb|gerbers` — knowledge-layer analysis via vendored
  `aklofas/kicad-happy` (v1.3.1, MIT). Wraps the upstream analyzers in the
  standard kcd JSON envelope; lifts findings with severity >= warning into
  envelope `warnings[]`; saves raw analyzer JSON as artifact. Skill body at
  `skills/kicad/SKILL.md` with reference docs under `skills/kicad/references/`.
- `kcd drc` / `kcd erc` — design and electrical rule checks via kicad-cli
- `kcd route track` — single-track routing via kipy IPC
- `kcd route freeroute` — FreeRouting orchestration via .dsn/.ses round-trip
- `kcd export gerber|drill|bom|step|pos|pdf` — manufacturing file exports
- Auto-snapshot before every mutating command
- Auto-render after every mutating command (lands in `$KCD_RENDER_CACHE`)
- Universal `--json` flag for agent-friendly output

### Fixed
- `kcd project current` schematic entries now carry a real filesystem `path`
  (the `.kicad_sch` file location). Previously the parser read kipy's
  `sheet_path.path_human_readable` field, which is the sheet-*hierarchy*
  path (`"/"`, `"/SubA/"`) — and on some setups came through empty.
  The fix reconstructs `path` from the `ProjectSpecifier` (project dir +
  project name + `.kicad_sch`), matching the board entry's shape. The
  hierarchy info is preserved in a new `sheet_path` field on schematic
  entries. Dove session-5 close.

### Known limitations
- Diff-pair length tuning: not implemented
- Specctra DSN export: not headless (manual KiCad step required)
- Schematic hierarchical net tracing: v1 stub only
- Windows: untested
- KiCad 9: not supported (use kicad-mcp or similar for v9)
