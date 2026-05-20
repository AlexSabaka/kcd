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
- `kcd edit add-symbol` — place a component on the root sheet: clones an
  existing instance when the project already has the part type, otherwise
  embeds the symbol definition from a library (Wave 3 resolution)
- `kcd edit symbol` — swap a placed symbol for a different library part:
  changes the `lib_id`, embeds the new definition, rewrites the pin
  entries. Requires `--pin-map` when the pin sets differ, and warns about
  wires the swap leaves dangling (kcd does not reroute)
- `kcd edit net` — rename a net across the schematic: relabels local and
  global labels and, for a power net, repoints the power symbol's `lib_id`
  to `power:<new>` alongside its `Value` so the rename survives a library
  resync (field-report friction #4 — a Value-only rename is silently
  reverted by "Update Symbols from Library"). Root sheet only; after the
  rename it checks the live PCB for the stale old net name and instructs
  F8 / `kcd sync` (KiCad 10 exposes no headless forward annotation)
- `kcd edit text` — edit schematic text: `edit text titleblock` sets a
  title-block field (title / company / rev / date / comment1..9), creating
  the title block when the sheet lacks one; `edit text set` replaces a free
  graphic text item, matched by its current string with `--at` to
  disambiguate when several share it. Root sheet only; offline S-expr edits
  via kicad-skip — net labels are untouched (use `edit netlabel` / `edit net`)
- `kcd edit designrules` — set a board design-rule constraint in the
  `.kicad_pro` file: mutates a `board.design_settings.rules` key (the DRC
  constraint minimums — clearance, track width, via/hole sizes). Validates the
  rule name against the KiCad 10 constraint set and coerces the value to the
  rule's type (mm float, int, or flag); creates the nested settings path when
  a freshly-templated project lacks it. Offline JSON edit — warns that KiCad,
  if it has the project open, may overwrite the change on its next save
- `kcd edit move-fp` — PCB footprint move via kipy IPC
- `kcd edit track delete|modify` — PCB copper track editing via kipy IPC:
  delete tracks, or change their width / layer / net assignment. Tracks
  are selected by whole net (`--net`) or a single segment (`--from`/`--to`,
  either direction), optionally narrowed by `--layer`. Requires KiCad open
  with the PCB editor; persists via `board.save()` (move-fp caveat applies)
- `kcd edit via add` — add a through-via on the PCB via kipy IPC: placed on
  a net at a given point with configurable copper and drill diameter
  (defaults 0.6 / 0.3 mm). Blind/buried vias are out of scope. Requires
  KiCad open with the PCB editor; `board.save()` caveat applies
- `kcd edit zone add|delete` — PCB copper-zone editing via kipy IPC: add a
  rectangular copper pour (net + layer + corner rectangle, optional
  priority and local clearance) or delete zones selected by net and/or
  layer. Both trigger a zone refill. Arbitrary (non-rectangular) outlines
  are out of scope. Requires KiCad open; `board.save()` caveat applies
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
- `kcd route track` now accepts the canonical `F.Cu` layer form. `add_track`
  assigned the raw layer string straight to kipy's `BoardLayer` enum field,
  so the documented default `F.Cu` — the form every read command (`net of`,
  `edit track delete`) emits — failed with `unknown enum label`; only kipy's
  internal `BL_F_Cu` spelling worked. `_layer_enum` now normalizes all three
  forms (`F.Cu`, `F_Cu`, `BL_F_Cu`) and `add_track` routes through it, so a
  layer read off one command feeds straight into another. Round-2 field
  report bug #1.
- `kcd parity` (and PCB footprint readouts in `inspect`) now report the
  board-side footprint library id. It was read from `fp.library_id`, an
  attribute kipy's `FootprintInstance` does not have — the resulting
  `AttributeError` was swallowed, so `library_id` came back `""` for every
  footprint and `parity` flagged all 60+ components as footprint
  mismatches. The id lives on the footprint *definition*
  (`fp.definition.id.library` / `.name`). Round-2 field report bug #2.
- `kcd parity` no longer reports `#PWR` / `#FLG` power-flag symbols as
  `schematic_only` drift. KiCad's `#`-prefixed symbols carry no footprint
  and never appear on a PCB by design; listing them buried the genuine
  un-placed components under dozens of false positives. Round-2 field
  report bug #4.
- `kcd project current` schematic entries now carry a real filesystem `path`
  (the `.kicad_sch` file location). Previously the parser read kipy's
  `sheet_path.path_human_readable` field, which is the sheet-*hierarchy*
  path (`"/"`, `"/SubA/"`) — and on some setups came through empty.
  The fix reconstructs `path` from the `ProjectSpecifier` (project dir +
  project name + `.kicad_sch`), matching the board entry's shape. The
  hierarchy info is preserved in a new `sheet_path` field on schematic
  entries. Dove session-5 close.
- `kcd net list` now reports power nets. `skip_sch.list_nets` scanned a
  non-existent `sch.power` collection; kicad-skip keeps power symbols in
  `sch.symbol` with a `power:` lib_id, so power nets were silently omitted
  despite the command's docstring promising them.
- `kcd_mcp` MCP server now exposes the full CLI surface. The hand-written
  server had drifted to a pre-roadmap 22-tool subset — every command from
  Waves 1-7 (net queries, `sync`, `lib`, structural/copper/text edits,
  design rules) plus `parity`, `analyze`, `route`, `render 3d` and
  `export drill|pos` shipped in the CLI but was never wired into the MCP
  layer, so MCP clients saw a frozen toolset. All 53 leaf commands are now
  exposed; a new `tests/test_mcp_parity.py` drift guard fails the build if
  the CLI and MCP tool sets ever diverge again.

### Known limitations
- Diff-pair length tuning: not implemented
- Specctra DSN export: not headless (manual KiCad step required)
- Schematic hierarchical net tracing: v1 stub only
- Windows: untested
- KiCad 9: not supported (use kicad-mcp or similar for v9)
