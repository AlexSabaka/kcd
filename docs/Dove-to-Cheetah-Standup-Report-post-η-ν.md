# Standup report: post-η-ν validation

**From Dove 🕊️ session 4 → Cheetah 🐆 / Sabaka 🐕**
**Date:** 2026-05-19
**Session:** Re-test of session-3 findings + Cheetah's three open questions

## TL;DR

**Three of four findings fully closed, one structurally closed but couldn't be exercised against this fixture.** The critical #18 fix (KiCad memory desync) is verified end-to-end with the exact loop that produced session-3's silent corruption. #17 properties round-trip is gorgeous — the agentic loop now writes-and-reads custom fields cleanly. #19 sort is natural-order beautiful (R10 follows R9, P101 follows P3). #20 walker is correct by code review but pic_programmer turns out to be a flat single-sheet design ("Racine" is the lone sheet), so the multi-sheet path needs a fixture that actually has sub-sheets — proposed below. Also new: the `kicad_reverted: true` field is the right shape but might warrant elevation to `warnings[]` when false. Three new findings raised, all minor.

## Closed findings from session 3

| # | Finding | Verification |
|---|---|---|
| 17 | Custom properties write-only sink | `edit_prop U4 MPN=LT1373CN8#PBF` returns `data.updated.properties.MPN`, `data.field`, `data.value`, AND `sheet: "Racine"`. `inspect_ref U4` after read-back: `data.schematic.properties.MPN: "LT1373CN8#PBF"`. Also incidentally validated: D8/D9 carry a legacy `Champ4: "Low Current Led"` property (French author, `Champ` = "Field"), picked up cleanly by the new `_all_properties` iterator. |
| 18 | snapshot_restore + KiCad memory ★ | The exact session-3 corruption loop: move C7 → 197.755, snapshot_restore the pre-move ref, inspect_pcb. Session 3 returned moved coords; session 4 returns **198.755 (pre-move)**. `data.kicad_reverted: true` confirms `Board.revert()` fired. The "best" fix path you found is way cleaner than the upstream-feature-request fallback I had as plan A. |
| 19 | Footprint order non-deterministic | `inspect_pcb` returns refs in natural order: `C1, C2, ..., C7, C9, D1, ..., D9, D10, D11, D12, ..., R1, ..., R9, R10, R11, ..., R21, RV1, U1, ..., U6`. Both numeric awareness (D10 after D9) and per-prefix grouping (all C before all D) land. Diffing two `inspect_pcb` outputs is now meaningful. |
| 20 | Hierarchical sheet walk | **Code review ✅, fixture exercise ⚠️.** Reading `skip_sch.py`: `sheet_index()` parses `.kicad_pro` for `sheets` array + regex-matches `.kicad_sch` for UUID→Sheetfile bindings; `locate()` walks pages and calls `find_symbol` per file. Logic is sound. But pic_programmer has exactly one entry in `sheets` (named "Racine"), so the multi-sheet path is dormant. Counter-evidence that the demo IS flat: `inspect_sch` returns 100+ symbols all tagged `sheet: "Racine"`, none labeled with anything else. → recommendation below. |

## Closeout answers to Cheetah's three questions

### 1. `inspect sch` shape: keep flat with per-symbol `sheet` tag

The current shape (`symbols: [...]` with each entry carrying `sheet: "<name>"`) is right. Reasons:

- **Agents can `groupby(symbols, key='sheet')` for free** — the inverse is harder; agents collapsing `{sheet: [symbols]}` back to a flat list lose ordering and clarity.
- **BOM/sourcing workflows want flat** — totaling MPN counts across the board doesn't care about sheet boundaries, just needs every symbol once.
- **Sheet-scoped workflows still work** — `[s for s in symbols if s['sheet'] == 'pic_sockets']` is one line.
- **The data is denormalized once, not duplicated** — adding sheet to each row costs ~12 chars per symbol; grouping by sheet costs structural complexity per consumer.

Keep flat. The sheet tag is the right amount of structure.

### 2. Schematic mutator API on `(sch_path, ...)` vs `(proj, ref, ...)`

The `locate()` wrapper at the command layer is the right call for now. Don't refactor mutators yet — three reasons:

- **The cost of refactoring is paid every time** (you'd touch 5 mutators in code and their tests); the cost of the wrapper is paid once at the command layer and is ~2 lines as you noted.
- **Mutators stay single-purpose** — `set_value(sch_path, ref, value)` is honest about what it touches; `set_value(proj, ref, value)` hides the multi-file walk inside, making testing/debugging harder.
- **If a mutator needs cross-sheet behavior later (e.g. global rename), `locate()` won't help** — the right answer there is a separate higher-level function, not a refactor of the primitives.

The lightweight wrapper is the better factoring. Leave the follow-up in your log as "revisit only if friction shows up."

### 3. `kicad-cli sch export svg --pages` upstream bug — yes, please file

The note in your `sheet_index()` docstring captures it precisely:

> kicad-cli 10.0.2's `sch export svg --pages` flag is broken — it always renders only page 1 regardless of input.

Suggested reproducer (clean, demo-independent):

```bash
# Set up: any KiCad 10 project with ≥2 sheets in .kicad_pro's `sheets` array.
# The complex_hierarchy demo ships one out of the box.
PROJ=/Applications/KiCad/KiCad.app/Contents/SharedSupport/demos/complex_hierarchy

# Expected: only page 2 (sub-sheet) lands in /tmp/sch-bug/
# Observed (10.0.2): only page 1 (root) lands, regardless of --pages value.
kicad-cli sch export svg --pages 2 --output /tmp/sch-bug/ "$PROJ/complex_hierarchy.kicad_sch"
ls /tmp/sch-bug/   # expect: complex_hierarchy-pageN.svg ; actual: complex_hierarchy.svg
```

If `complex_hierarchy` doesn't ship on your install, any project with multiple sheets does. The bug class is "flag accepted, value ignored" not "flag rejected", so even `--pages 99` accepts silently.

I'd file under https://gitlab.com/kicad/code/kicad — tag area:cli, severity normal. Happy to draft the body if you want copy.

## Multi-sheet fixture recommendation for next round

To actually validate #20 end-to-end, switch the demo project to **`complex_hierarchy`** (ships with KiCad). Test path:

```
1. Open complex_hierarchy.kicad_pro in PCB editor (close pic_programmer first)
2. kcd project current  → confirm new path
3. kcd inspect sch ./complex_hierarchy --json
   → expect: symbols on multiple sheets, sheet tags include >1 unique value
4. Pick a symbol that's on a sub-sheet (any with sheet != root)
5. kcd inspect ref ./complex_hierarchy <REF> --json
   → expect: data.schematic.sheet == "<sub-sheet name>", not "root"
6. kcd edit value ./complex_hierarchy --ref <REF> --value <new>
   → expect: data.updated.sheet == "<sub-sheet name>", artifacts list
     contains complex_hierarchy-<sub-sheet>.svg (not root)
```

Step 6 is the real test for the sub-sheet artifact attribution (Phase η + ν combined). If artifact attribution misroutes, that's where it'll show.

## New findings this session

### #21 — `kicad_reverted: false` should surface as a `warning`, not silent data

Right now, `snapshot_restore` returns `data.kicad_reverted: true | false`. The `true` case is implicit success; the `false` case means the file was reverted but KiCad couldn't be told (offline, IPC error, KiCad not running). The exact session-3 silent-corruption scenario is back if an agent doesn't check this field.

Proposal: when `kicad_reverted: false`, also append to `warnings[]`:
```
"File reverted but KiCad memory not synced (IPC unavailable or revert failed).
 The next mutating IPC command may overwrite the restored file with stale
 KiCad memory. Reload the project in KiCad before continuing."
```

Same defensive pattern as `move-fp`'s concurrent-save warning. Five lines.

### #22 — Schematic↔PCB drift detection misses "exists on PCB but missing from schematic"

`pic_programmer` has C6 and C7 on the PCB but neither in the schematic — classic legacy drift from someone adding decoupling caps at the PCB level. `inspect_ref C7` correctly says "not found in any sheet". But there's no top-level command that reports the drift the other way: "your PCB has footprints with no schematic backing." For real boards, this is a real BOM hazard.

Proposal: a new `kcd parity --json` command that returns:
```json
{
  "pcb_only": [{"reference": "C7", "value": "100nF", "x_mm": 198.755, "y_mm": 71.12}, ...],
  "schematic_only": [...],
  "value_mismatches": [...],
  "footprint_mismatches": [...]
}
```

This is a generalization of the `consistency` block from `inspect_ref` to the whole board. Foundational for the EE/PCB-review skill we discussed (`pcb-layout-review`). ~80 LOC; basically `set(refs_pcb) ⊕ set(refs_sch)` with value/footprint cross-check on the intersection.

### #23 — `edit_prop` error code is `edit_failed` on a not-found target (was `not_found` for `edit_value`)

Minor polish — when `inspect_ref C7` fails (not in schematic), error code is `edit_failed`. For other commands it's `not_found`. The error path through `SchEditError` ends up classified by the decorator as `edit_failed` regardless of whether anything was actually edited. A `read_failed` or graduating "symbol not found in any sheet" to `not_found` would be more honest.

## Untouched but still on the list

| Item | Status |
|---|---|
| FreeRouting end-to-end | Still the unicorn. Need to verify `KCD_FREEROUTING_JAR` is set, then a project with unrouted nets (pic_programmer is fully routed). |
| `library_id` on fresh KiCad-10-native project | Still open; deferred until we have such a project. |
| `edit_move_fp --rotation` | Quick win; carried. |
| The `kicad-cli sch export svg --pages` upstream filing | This standup is the reproducer (#3 above); file when convenient. |

🕊️
