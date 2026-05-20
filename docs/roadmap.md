# kcd roadmap — mutation breadth & the sync bridge

> **Status: RETIRED — fully delivered 2026-05-20.** All seven waves below
> shipped (see `CHANGELOG.md` and the traceability table at the foot of this
> doc); the one item left open — true headless schematic→PCB forward
> annotation — is blocked upstream in KiCad 10, not on kcd. This document is
> kept for historical reference. The next cycle of work starts from a fresh
> field report.

Source: `docs/Dove-to-Cheetah-Field-Report.md` (agentic field test on
`Brushed_Flight_Controller`, 2026-05-19). The field report's verdict: kcd is an
excellent *read + diagnose + lightly-edit* tool; the gap to *autonomous refactor*
is mutation breadth plus a schematic→PCB sync bridge. This doc sequences and
sizes that gap.

Effort units are focused agentic-session days: **S** ≈ 1 day, **M** ≈ 2–3 days,
**L** ≈ ~1 week. Whole roadmap ≈ 4–5 weeks.

## Current state (2026-05-20)

What works (keep): structured inspect, ERC/DRC, git-backed snapshots,
edit-echoes-state, footgun notes in command descriptions.

What's missing: structural schematic edits (add/swap symbols, wires, labels),
all PCB copper edits beyond `route track`, net connectivity queries, design-rule
edits, and the schematic→PCB sync.

## The blocker: forward annotation

Dove ranked schematic→PCB sync as the #1 P0 keystone. **There is no headless
path in KiCad 10.** kipy 0.7.1 exposes no `update_from_schematic`; kicad-cli
exports a netlist (`sch export netlist`) but cannot import one — pcbnew's
netlist import is a GUI-only action. kcd cannot push the schematic to the board.
Wave 2 delivers the best honest partial; true sync waits on upstream KiCad.

## Roadmap

### Wave 1 — Net inspection (P0)

*Field report: "net-blindness" friction; Dove priority #2.*

Answer "what is on net X" and "what net is pin Y on" — kills the guessing that
forced Dove to infer connectivity from DRC error strings.

- Surface: enrich `net pcb` (pad counts); new `net of <NET>` → footprints + pads
  + tracks on a net; make `net trace` real.
- Feasibility: **PCB-side HIGH** (kipy: footprints→pads→net, tracks→net).
  **Schematic-side MEDIUM** — kicad-skip exposes pin locations, wire geometry,
  junctions and labels, so a geometric tracer (pin xy → wire segment → junction
  → label) is buildable on confirmed primitives.
- Effort: **M**. Ship PCB-side first (~1d), then the schematic tracer (~1–2d incl. spike).
- Dependencies: none. Enables Wave 2.
- Risk: schematic tracer edge cases — buses, no-connects, hierarchical pins.

### Wave 2 — Sync bridge / forward-annotation partial (P0)

*Field report gap #1; Dove priority #1.*

True sync is blocked (see above). Deliver the partial:

- `kcd sync --check` — drift report: footprints in the schematic missing from
  the PCB, net-membership differences. Builds on `parity` + Wave 1.
- `kcd sync` — export the netlist via `kicad-cli sch export netlist` and emit
  precise human instructions ("open pcbnew → File → Import Netlist → …").
- Feasibility: drift + netlist export **HIGH**; programmatic push **BLOCKED**.
- Effort: **M** (~2d).
- Dependencies: Wave 1 (net-membership comparison).
- Risk: a partial that's too quiet gives false confidence — the envelope must
  loudly state the human still runs the import.
- Decision gate (not scoped here): programmatic forward annotation via kipy
  `create_items` reimplements KiCad's netlist importer — fragile, divergence
  risk. Recommend **against** until upstream KiCad exposes the API.

### Wave 3 — Library access adapter (enabler)

*Not a field-report gap directly — prerequisite for Waves 4 & 5.*

Read `.kicad_sym` symbol libraries so kcd can pull a symbol definition not
already present in the project. Note: kicad-skip's `clone()` already covers the
"an instance of the target part exists in the project" case — library access is
only needed for genuinely-new part types, so Wave 4 can ship a clone-only
subset first and this can slot in just before the library-backed features.

- Feasibility: **MEDIUM** — new surface; `.kicad_sym` is S-expr, kicad-skip has
  a `lib_symbol` module.
- Effort: **M** (~1–2d).
- Dependencies: none.

### Wave 4 — Schematic structural editing (P1)

*Field report gaps #2 (symbol swap), #3 (add symbol), #4 (wires/labels).*

The big de-risk: kicad-skip natively supports `sch.wire.new()`,
`sch.junction.new()`, `sch.label.new()` / `global_label.new()`, `symbol.clone()`
and pin-location access — `examples/charlieplex.py` does exactly this. So this
cluster is medium, not hard.

- Surface: `edit add-symbol` (clone-based first, library-based after Wave 3),
  `edit symbol` (swap lib_id / clone-transplant + pin remap), `edit wire add|delete`,
  `edit netlabel add|delete`.
- Cluster rationale: a symbol swap leaves dangling wires → needs wire editing;
  add-symbol needs wires to connect. Ship together.
- Also clears README doc-debt (`add-symbol`/`add-power` advertised but absent).
- Feasibility: wire/label **MEDIUM→S**; add-symbol-via-clone **MEDIUM**;
  full library-backed swap **MEDIUM** (Wave 3 dep).
- Effort: **L** (~1 week for the cluster).
- Dependencies: Wave 3 for library-backed add/swap; the clone-only subset has none.
- Risk: pin remap on swap, wire-dangle cleanup, multi-unit symbols.

### Wave 5 — Net rename, lib_id-aware (P2)

*Field report gap #7 + friction #4 (the landmine).*

Friction #4: renaming a power net by editing power-symbol `Value` works, but the
symbol's `lib_id` stays `power:+12V` — a library-resync silently reverts it.

- Surface: `rename-net <old> <new>` — schematic side renames labels/global_labels
  and repoints power symbols' `lib_id` (needs Wave 3, or a label-based fallback);
  PCB side renames the net via kipy.
- Feasibility: **MEDIUM** — label rename easy; lib_id-correct power repoint needs
  library access; kipy net-name writability is uncertain (spike).
- Effort: **M** (~2–3d).
- Dependencies: Wave 3 (power-symbol repoint); pairs with Wave 4 (label editing).
- Risk: power-symbol lib_id correctness; kipy net writability; sch/pcb
  consistency without forward annotation.

### Wave 6 — PCB copper editing (P2)

*Field report gap #5 — "where the 164 DRC errors live", the biggest surface.*

- Current: `route track` creates tracks. Missing: track delete/modify, via
  create, zone create/edit.
- Surface: `edit track delete|modify`, `edit via add`, `edit zone …`.
- Feasibility: track edit/delete **HIGH** (kipy `remove_items`/update); via
  **HIGH** (kipy Via/PadStack types); zone **UNCERTAIN** — spike kipy 0.7.1.
- Effort: **L** (~1 week; zones the unknown).
- Dependencies: none — parallelizable with Waves 3–5.
- Risk: zone API depth in kipy 0.7.1.

### Wave 7 — Design rules + text editing (P2/P3)

*Field report gaps #6 (design rules), #8 (sheet/title text).*

- Design rules: `.kicad_pro` JSON + `.kicad_dru` are plain text; mutate with a
  snapshot. `edit designrules`.
- Text: title block + graphic text — locate + mutate string. `edit text`.
- Feasibility: **HIGH** both.
- Effort: **M** (~2–3d combined).
- Dependencies: none. Lowest priority — mop-up.

## Dependency graph

```text
Wave 1 ──▶ Wave 2
Wave 3 ──▶ Wave 4 (library-backed subset)
Wave 3 ──▶ Wave 5
Wave 4 ◀─▶ Wave 5 (shared label editing)
Wave 6   independent — parallelizable any time
Wave 7   independent — parallelizable any time
```

Recommended sequence: **1 → 2 → 3 → 4 → 5**, with **6** and **7** interleaved
whenever a PCB-only or mop-up session fits.

## Field-report traceability

| Field report item | Disposition |
|---|---|
| Gap #1 — push sch→PCB | Wave 2 (partial; true sync blocked upstream) |
| Gap #2 — symbol swap | Wave 4 |
| Gap #3 — add symbol | Wave 4 |
| Gap #4 — wires / net labels | Wave 4 |
| Gap #5 — PCB copper | Wave 6 |
| Gap #6 — design rules | Wave 7 |
| Gap #7 — net rename | Wave 5 |
| Gap #8 — sheet / title text | Wave 7 |
| Net-blindness ("what's on net X") | Wave 1 |
| Friction #1 — deferred tool loading | Out of scope — MCP-layer, not kcd CLI |
| Friction #2 — project_current empty sch path | Done — commit 33f70b7 |
| Friction #3 — filesystem MCP sandbox | Out of scope — environment config |
| Friction #4 — net-rename landmine | Folded into Wave 5 |
| Miss — render artifacts unreachable | Quick win below; mostly environment |

## Quick wins (any time, not blocking)

- Fix README doc-debt: footnote or remove `edit add-symbol|add-power` until
  Wave 4 lands — they're advertised but absent.
- Keep the footgun-note practice (cf. `move-fp`'s segfault warning) on every
  new mutating command added in Waves 2–7.
- Consider surfacing render artifacts where an agent can read them (the SVG
  path is already in the envelope; the friction was an environment sandbox).
