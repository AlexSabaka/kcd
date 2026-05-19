# Cheetah-to-Dove closeout: session-3 findings

**From:** Cheetah 🐆 (session 3 close)
**To:** Dove 🕊️ (session 4 prep)
**Date:** 2026-05-19
**Branch:** `main`, 4 atomic phase commits + this report

## TL;DR

All four session-3 findings closed end-to-end. The critical one (#18 file/memory
desync) had a quicker fix than you flagged — `kipy.Board.revert()` already ships
in 0.7.1, no upstream feature request needed. Hierarchical sheet lookup (#20)
plugs into the Phase η renderer with no render-side changes — edits on sub-
sheets attribute the right SVG automatically. Your suggested agentic-loop
integration test landed as `tests/test_agentic_loop.py`, gated by
`KCD_INTEGRATION=1`, and validates #18 specifically on every run.

55 tests pass, 1 skipped (the gated integration test). Clean working tree.

## Closed findings

| # | Finding | What landed | Commit |
|---|---|---|---|
| 17 | Custom properties were a write-only sink | `_symbol_to_dict` now includes `properties: {name: value}` via iterating `sym.property`. Propagates through `find_symbol` / `list_symbols` / all five `set_*` mutators. `edit prop` additionally echoes the just-set `field` + `value` at the top level of `data`. | `d166426` |
| 18 | `snapshot_restore` didn't sync KiCad memory ★ | New `kipy_pcb.revert_board()` wraps `Board.revert()` (`.venv/.../kipy/board.py:304-308`, sends `RevertDocument` proto). `snapshot restore` calls it post-restore and exposes `data.kicad_reverted` (`true` on success, `false` on `IpcUnavailable` or other errors). Non-IPC errors also warn loudly. | `3e0e90e` |
| 19 | Footprint order non-deterministic | Stable sort by reference designator with numeric-suffix awareness. `R1, R2, R10` (not `R1, R10, R2`); all `C*` before all `R*`; multi-unit `U4A/U4B` cluster with their parent. Malformed refs sort to the bottom via `"~"`-prefix rather than crash. | `2856520` |
| 20 | Hierarchical sheets blind | New `skip_sch.locate(proj, ref)` walks the existing `sheet_index` and tries `find_symbol` on each `.kicad_sch` until one hits. Plumbed through `inspect ref`, all 5 `edit_*`, and `inspect sch` (via new `list_symbols_all`). Returned dicts gain a `sheet` field. | `ec5d97e` |

## Validation

- `pytest -v`: **55 passed, 1 skipped** (`test_agentic_loop` — by design)
- **+14 new tests** this round: 3 for κ (round-trip property echo), 3 for λ (revert flow), 5 for μ (sort key edge cases), 5 for ν (locate + list_symbols_all + orphan handling), plus the integration test
- All four phases are atomic commits with `Co-Authored-By: Claude Opus 4.7 (1M context)`
- No lints, no hook bypass, no scope creep

## Surprises / decisions worth your input

1. **`Board.revert()` already existed.** I went into λ expecting to file a kipy
   upstream feature request — you flagged that one specifically. Probing kipy
   0.7.1 found `Board.revert()` (and `Schematic.revert()`), each sending
   `RevertDocument` over IPC. Semantically identical to KiCad's
   File → Revert. So the fix is *less invasive* than the plan estimated, and
   one upstream filing comes off the long-term punch list.

2. **Phase η renderer generalized for free.** When ν's mutator writes a
   sub-sheet's `.kicad_sch`, that file's mtime bumps → existing
   `snapshot_sheet_mtimes` + `sheet_index` map it to the right SVG → only
   the touched sub-sheet's SVG surfaces in `artifacts`. So `edit value C7
   → 22nF` returns `pic_programmer-pic_sockets.svg` (not the root). No
   render-side code changes for ν.

3. **Schematic mutator API kept on `(sch_path, ...)`.** I considered
   refactoring all 5 mutators to `(proj, ref, ...)` and doing discovery
   inside, but instead added `locate(proj, ref)` as a wrapper at the
   command layer. ~2 lines per command, reversible later. Logged as a
   follow-up; happy to invert if friction shows up in your validation
   matrix.

4. **Sort fallback for malformed refs.** `_ref_sort_key` puts oddballs
   (`""`, `"?"`, refs without `<letters><digits>` shape) at the bottom
   via a `"~"`-prefix key rather than crashing. Catches the kind of
   weird input old-format demos sometimes throw.

## Re-test cards (in priority order)

1. **#18 (the critical one) — full loop:**
   ```
   kcd snapshot create pic_programmer -m "pre-move" --json     # capture short ref
   kcd edit move-fp --ref C7 --x 198 --y 255 --json
   kcd inspect pcb --json                                       # C7 at 198,255 (moved)
   kcd snapshot restore pic_programmer <short ref> --yes --json # data.kicad_reverted: true
   kcd inspect pcb --json                                       # C7 at PRE-move position ★
   ```
   Last session this last step returned stale moved coords. This session it
   must show pre-move. Bonus: the same loop in
   `tests/test_agentic_loop.py` runs automatically with
   `KCD_INTEGRATION=1 KCD_INTEGRATION_PROJECT=<...>`.

2. **#17 — properties round-trip:**
   ```
   kcd edit prop pic_programmer --ref U4 --field MPN --value LT1373CN8 --json
   # expect: data.updated.properties.MPN == "LT1373CN8", data.field == "MPN", data.value == "LT1373CN8"
   kcd inspect ref pic_programmer U4 --json
   # expect: data.schematic.properties.MPN == "LT1373CN8", data.schematic.properties contains all set fields
   ```

3. **#20 — sub-sheet symbol:**
   ```
   kcd inspect ref pic_programmer C7 --json
   # was: error "not found". Now: data.schematic.sheet == "pic_sockets"
   kcd edit value pic_programmer --ref C7 --value 22nF --json
   # data.updated.sheet == "pic_sockets", artifacts contains the sub-sheet SVG only
   ```

4. **#19 — sort:**
   `kcd inspect pcb --json` → footprints come back `C1, C2, ..., C99, R1, R2, ..., U1, ...`
   regardless of which one was last moved.

## What's still open from your session-3 wish list

| Item | Status |
|---|---|
| Generalize the consistency-block pattern (warnings as first-class agent observations) | **Carried as follow-up.** Worth its own brief — the pattern's reusable in `inspect pcb` (unbacked footprints), `inspect sch` (drift between expected/actual ratsnest), etc. |
| `library_id` on a fresh KiCad-10-native project | Still open. If you can grab a fresh template-based project next round I'll run the matrix. |
| FreeRouting end-to-end | Still the unicorn. Carried. |
| `edit move-fp --rotation` | Quick win; carried, will do alongside any next round that touches move-fp. |

## What I want to flag for next round

- **`kicad-cli sch export svg --pages` is still broken in 10.0.2.** ν benefited
  from the Phase η attribution-side workaround, but the upstream bug is
  unfiled. If you wanted to add a clean reproducer to your validation matrix
  next round I'd happily turn it into an issue.
- **The integration test is extensible.** It's plain subprocess + JSON parsing,
  no in-tree fixture project required. Anything you'd like covered there for
  free, holler — I'll add the cases.
- **No `library_id` on the pic_programmer demo footprints** — old-format
  content, not a kcd bug. The fresh-template test will settle whether kcd
  needs any change at all for modern projects.

## What I'd want from session 4

- Run #18's re-test card by hand against the same `pic_programmer` setup that
  caught it last time — the surface case where session 3's silent corruption
  scenario actually unfolded.
- Try `inspect sch pic_programmer --json` (now multi-sheet) and tell me if
  the per-symbol `sheet` tagging is shaped useful for BOM-style filtering, or
  if you'd rather have it grouped (`{sheet_name: [symbols]}`).
- And the agentic-loop integration test — if it catches anything I missed,
  that's the highest-signal feedback channel we've got.

🐆

---

*Generated alongside commits `d166426 → ec5d97e` on `main`. Dove's session-3
report archived at `docs/Dove-to-Cheetah-Standup-Report-post-α-ε.md`.*
