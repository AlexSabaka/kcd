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
  a freshly-templated project lacks it. Offline JSON edit — refuses with
  `project_open_in_kicad` when KiCad has the project loaded (its cached
  settings would silently overwrite the file on the next save); `--force`
  writes anyway. Round-2 field report bug #3 hardened the original
  warn-only behaviour into a hard guard
- `kcd edit move-fp` — PCB footprint move via kipy IPC
- `kcd edit delete-fp` — delete a footprint from the PCB by reference via
  kipy IPC: the board-side counterpart of `edit delete` (which is
  schematic-only), for clearing orphan footprints with no schematic
  backing. Warns when the footprint has an associated schematic symbol —
  deleting it board-side opens schematic↔PCB drift kcd cannot
  forward-annotate. Round-2 field report gap
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
- `kcd analyze sch|pcb|gerbers|cross|thermal|fab-gate|whatif|lifecycle|diff`
  — knowledge-layer analysis via the vendored `aklofas/kicad-happy` engine
  (MIT). Every analyzer is wrapped in the standard kcd JSON envelope (and so
  is an MCP tool): findings with severity >= warning lift into envelope
  `warnings[]`, raw analyzer JSON saves as an artifact. `cross` / `thermal` /
  `fab-gate` / `whatif` / `lifecycle` take a project and run the prerequisite
  schematic/PCB analyzers internally; `diff` compares two saved runs;
  `analyze pcb --full` runs the deep PCB pass. The analyzer engine lives at
  `src/kcd/analyzers/` (shipped in the wheel as part of the `kcd` package);
  the skill body is `skills/kicad/SKILL.md` — rewritten so the skill drives
  entirely through `kcd` commands and runs in MCP-only environments — with
  reference docs under `skills/kicad/references/`.
- `kcd drc` / `kcd erc` — design and electrical rule checks via kicad-cli.
  The report is folded for token efficiency: violations group by
  `(type, severity)` into `data.violations[]`, each group carrying a true
  `count` and a 3-occurrence `shown` sample; item positions compact to
  `at:[x,y]` and uuids drop from the inline envelope. `--full` inlines every
  occurrence; the artifact file always holds the complete report (uuids
  retained). A ~200-violation board drops from ~45K tokens inline to ~6K
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
- Mutating commands no longer leave a snapshot behind when the edit fails.
  The pre-edit snapshot is still taken before the mutation runs (so it
  captures a real rollback point), but if the command then errors,
  `run_command` discards that snapshot via the new `SnapshotStore.drop`
  rather than leaving a commit for an edit that never landed. Round-2 field
  report bug #5.
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
- `kcd edit move-fp --rotation` no longer crashes. The rotation path
  imported `Angle` from `kipy.common_types`, but kipy 0.7.1 relocated the
  class to `kipy.geometry` — every rotate-during-move died with an
  `ImportError` (position-only moves were unaffected). Round-3 field
  report B1.
- Mutating PCB commands no longer emit the `board.save()` advisory on a
  no-op. The warning fired *before* the mutation, so a `track delete` /
  `track modify` that matched nothing still told the user their unsaved
  editor changes had been persisted — when nothing was written. The warning
  now fires only after a real write, and `delete_tracks` / `modify_tracks`
  skip `board.save()` entirely when the selection is empty. Round-3 field
  report B14.
- `kcd analyze *` no longer overruns the 1MB MCP result cap. Every
  `analyze` subcommand inlined the entire analyzer JSON (full BOM, every
  net, every track, dependency graphs) into `data` — a 58-component
  board's `analyze sch` was hard-rejected as too large. The inline
  envelope is now folded: `findings` group by `(rule_id, severity)` with a
  3-occurrence sample, the headline `summary` / `trust_summary` ride
  verbatim, and bulk sections spill (named in `data.spilled.sections`).
  The artifact always holds the complete analyzer JSON. Round-3 field
  report B2.
- `kcd snapshot diff` no longer overruns the 1MB MCP result cap. The full
  unified diff was inlined into `data.diff` — a filled-zone `.kicad_pcb`
  diff is thousands of polygon points and was hard-rejected. The inline
  envelope now carries a per-file summary (files changed, lines
  added/removed via `git diff --numstat`); a small diff body still rides
  inline, a large one spills to the artifact, which always holds the
  complete unified diff. Round-3 field report B4.
- `kcd_render_sch` / `kcd_render_pcb` / `kcd_render_3d` MCP tools now return
  the render as an inline image. They previously returned only an artifact
  *path* on the operator's filesystem — in MCP-remote operation the agent
  could never see its own render. Each wrapper now returns a PNG image
  content block alongside the JSON envelope (capped to stay under the 1MB
  MCP result limit; an oversize preview is skipped with a warning rather
  than failing the call). `kcd render pcb` gains a `png` format — a flat 2D
  layer view rasterized from SVG — so the PCB preview shows copper, not a
  soldermask-covered 3D view. Round-3 field report B3.
- `kcd analyze fab-gate` reconciles its routing verdict against DRC. The
  vendored gate's routing check trusts net-level `routing_complete` and is
  blind to pad-level gaps — it reported "all nets routed" while DRC found
  unconnected pads. kcd now runs DRC after the gate and downgrades a
  falsely-passing `routing_completeness` check to FAIL, recomputing the
  gate summary and overall status. Round-3 field report B5.
- `kcd analyze thermal` no longer reports a confident score from an empty
  assessment. The vendored scorer returns 100 when there are no findings —
  even when `components_assessed` is 0, i.e. nothing was evaluated. kcd now
  nulls `thermal_score` and sets `thermal_score_status: insufficient_data`
  when zero components were assessed. Round-3 field report B6.
- MPN-coverage checks recognize the SnapEDA `MP` field. The schematic
  analyzer's `_MPN_KEYS` alias set was blind to `MP` and `Mfr_Part_No`, so
  SnapEDA-sourced parts undercounted MPN coverage to zero. Both aliases
  added (a local patch to the vendored analyzer engine). Round-3 field
  report B7.
- `kcd inspect ref` flags part-identity incoherence. The `consistency`
  block only compared schematic vs PCB; it now also carries
  `consistency.part_identity` — a conservative check that a component's own
  value, symbol lib_id, and datasheet agree (it catches a part labeled
  "AP2112K-3.3" on an NCP1117 symbol with an NCP1117 datasheet). It fires
  only when the value and the symbol name both carry a real part-number
  family that differ, so passives and generic symbols never
  false-positive. Round-3 field report B8.
- `kcd lib list` surfaces project-embedded symbol libraries. It listed only
  the standard symbol directory and `sym-lib-table` entries; a library used
  only via the schematic's in-file `lib_symbols` block (e.g. an embedded
  vendor library) was invisible. Such libraries now appear with
  `location: embedded`, and every entry gains a `location` field
  (standard | project | embedded). Round-3 field report B10.
- `kcd render *` PNG output no longer depends on an external rasterizer
  app. PNG export — and the MCP inline-image previews for schematics and
  flat 2D PCB layer views — was rasterized via `rsvg-convert` / `inkscape`;
  hosts with neither got a hard `cli_failed`. SVG→PNG now goes through the
  bundled `resvg-py` (MIT; a self-contained wheel of the Rust resvg
  engine), so the PNG path works on every install with no system setup.
  If resvg ever fails on a specific SVG, `render sch|pcb --format png`
  degrades to emitting the SVG with a warning instead of failing the
  command. Round-4 field report B3-B.
- `kcd export gerber` now ships a complete fab package. It exported only the
  copper/silk gerbers; drill files were a separate `export drill` call, so an
  agent running `export gerber` to "make the fab package" produced a set the
  fab rejects — with no warning. `export gerber` now also writes the drill
  files into the same directory (`data.drill_included: true`); the standalone
  `export drill` stays for drill-only exports. Round-5 field report R5-4.
- `kcd analyze *` inline envelopes are now genuinely small. The fold from
  Round-3 B2 was budget-driven but the budgets were too loose
  (`_TOTAL_BUDGET` 96 KB, `_VALUE_BUDGET` 24 KB), so an `analyze pcb` with
  several mid-size sections still came back enormous inline. The budgets are
  retuned (40 KB total, 8 KB per section) so bulk sections actually spill,
  and a spilled list now keeps a 3-entry `sample` (when it fits 2 KB) so the
  inline envelope still shows representative rows. Round-5 field report B2.
- `kcd analyze pcb` reconciles its `connectivity` block against DRC. The
  Round-3 B5 fix downgraded a falsely-passing routing verdict on `fab-gate`
  but not on `analyze pcb` itself, which kept reporting
  `connectivity.routing_complete: true` while DRC found unconnected pads.
  `analyze pcb` now runs the same DRC cross-check and sets
  `routing_complete: false` + `drc_unconnected: N` when pad-level gaps
  exist. Round-5 field report R5-3.
- `kcd analyze cross` no longer reads a zero-finding run as a clean bill of
  health. Its cross-checks (connector current vs trace, ESD, decoupling)
  need load-current / datasheet inputs; without them it runs nothing and
  returns 0 findings. A zero-finding cross report now carries
  `summary.assessment_status: insufficient_data` with a warning. Round-5
  field report R5-6.
- `kcd analyze diff` no longer crashes on gerber (or other unsupported)
  analyzer JSONs. The vendored differ KeyErrored when handed a JSON whose
  `analyzer_type` was outside schematic/pcb/emc/spice. `analyze diff` now
  reads the `analyzer_type` of both inputs and returns a clean
  `unsupported_diff` error — also catching a base/head type mismatch.
  Round-5 field report R5-5.
- `kcd render pcb` SVG/PNG output is cropped to the board. kicad-cli plotted
  the board on the full A4 worksheet frame, so a ~48 mm board occupied ~15%
  of the pixels and was unreadable. `export_pcb_svg` now passes
  `--page-size-mode 2` (board area only) + `--exclude-drawing-sheet`, so the
  board fills the render. `export pdf --target pcb` keeps the framed sheet.
  Round-5 field report R5-1.
- `kcd analyze pcb` inline envelope is now genuinely small on net-heavy
  boards. The Round-5 B2 fold only spilled *list*-typed sections, so dict
  sections (the `nets` / `net_name_to_id` maps, `layers`, `silkscreen`) and
  mid-size per-domain lists each fit the per-section budget and stayed fully
  inline. `_compact` now spills dict sections too — with a `{count, sample}`
  stub — and an always-spill set (`_BULKY_SECTIONS`) covers the sections that
  are bulky by nature regardless of size. `analyze pcb` additionally drops
  `net_name_to_id` (the exact inverse of `nets`) from both the artifact and
  the envelope. Round-6 field report.
- `kcd analyze pcb` reconciles the `statistics.routing_complete` sibling.
  The Round-5 R5-3 fix downgraded `connectivity.routing_complete` against
  DRC but left `statistics.routing_complete` — computed the same net-level
  way — reading a stale `true` in the same payload. Both are now downgraded
  together. Round-6 field report.

### Added (continued)
- `kcd edit pcb-text add|set` — add or edit free text on the PCB over live
  IPC. `add` places a text item (silkscreen by default — `--layer`, `--size`,
  `--thickness`, `--rotation`); `set` replaces an existing item matched by
  its current string. This closes the gap where `revision_marking` /
  `board_name` silk findings from `analyze pcb` / `fab-gate` had no
  agentic fix — `edit text *` only touches the schematic. Requires KiCad
  open with the PCB editor; calls `board.save()`. Round-5 field report R5-7.
- `kcd render pcb` gains `--region-ref` / `--region-bbox` — render a cropped
  sub-area instead of the whole board, so fine placement (a 1 mm courtyard
  overlap, a part nudge) is actually visible. `--region-ref REF` centres a
  `--region-window` mm square (default 20) on a footprint; `--region-bbox
  x1,y1,x2,y2` is an explicit mm window. The board-area SVG is cropped by
  rewriting its viewBox, and PNG rasterization dpi scales up so a zoomed
  region keeps full-board pixel detail. svg/png only; needs KiCad open (the
  board outline bbox and footprint position are read over IPC). Round-5
  field report R5-2.

### Known limitations
- Diff-pair length tuning: not implemented
- Specctra DSN export: not headless (manual KiCad step required)
- Schematic hierarchical net tracing: v1 stub only
- Windows: untested
- KiCad 9: not supported (use kicad-mcp or similar for v9)
- `analyze pcb` `trust_summary.provenance_coverage_pct` can read 0.0 despite
  topology evidence, and `statistics.track_count` can be null — internals
  of the vendored analyzer engine (Round-3 field report B11/B12)
- Schematic net counts differ across `sync` (netlist nets), `analyze` /
  `fab-gate` (S-expr nets), and PCB (pad-touching nets) — three legitimate
  definitions, not a drift bug (Round-3 field report B13)
