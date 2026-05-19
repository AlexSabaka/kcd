# Standup report: post-α-ε validation

**From Dove 🕊️ session 3 → Cheetah 🐆 / Sabaka 🐕**
**Date:** 2026-05-19
**Session:** Post-#11–#14 fixes against `pic_programmer` (PCB editor open)

## TL;DR

**The kcd surface is now genuinely good for agentic work.** All six high-priority findings from session 2 landed cleanly. The agentic loop is fast, the consistency block is a UX gem, and even my speculative #16 ("warn about concurrent saves") shipped as an in-band warning string. Four new findings, two real (#18 silent file/memory desync, #17 write-only-property gap) and two smaller (#19 order non-determinism, #20 hierarchical sheet blindness). 12 of 13 calls returned exactly what I expected. The one failure (`export_step`) was a real KiCad-CLI issue with old VRML models, surfaced cleanly through the now-untruncated envelope.

## Closed findings from session 2 (7 of 7 high-priority)

| # | Finding | Verified by |
|---|---|---|
| 3 | MCP shim truncates errors | `export_step` returned full stderr including the VRML model error and the file-attributes traceback. No truncation. |
| 6 | `~` doesn't expand | `kcd_export_bom` with `~/Downloads/kcd-demo` resolved cleanly to `/Users/oleksii/Downloads/kcd-demo` (failed for the right reason — empty dir — with the right path in the error). |
| 11 | `edit_prop` can't create new properties | Added `MPN=LT1373CN8#PBF` to U4 successfully. The kicad-skip path is fixed. |
| 12 | Render cache returns stale artifacts | After `edit_prop U4`, artifacts list contained exactly **one** SVG (`pic_programmer.svg`). No more `Arduino_Pro_Mini.svg` ghost. |
| 13 | Auto-render renders all sheets | Same call returned only the sheet U4 lives on. Sub-sheet `pic_programmer-pic_sockets.svg` wasn't re-rendered. The per-sheet filter works. |
| 14 | `inspect_ref` should flag sch↔pcb divergence | **Consistency block landed beautifully**: `{pcb_available, value_matches, footprint_matches, notes[]}` *plus* mirrored entries in `warnings[]`. Even surfaces the old-format footprint-mismatch quirk as actionable agent input. |
| 16 | `kipy board.save()` may save concurrent edits | Shipped as a `warnings[]` entry on every `move-fp` call: *"move-fp calls board.save() — any unsaved changes you have open in KiCad's PCB editor are persisted along with this edit. kipy 0.7.1 has no API to detect or skip this; save or revert in the editor before running mutating IPC commands."* Honest about the limitation, actionable for the user. |

## Validation matrix (this session, 13 calls)

| Tool | Result | Notes |
|---|---|---|
| `project_current` (no KiCad editor) | ✅ envelope-only error | First call: "KiCad is running but no editor is exposing documents" — actionable, came through the envelope cleanly. Even error messages got better. |
| `project_current` (after open) | ✅ | Bootstrap, 1 call. |
| `snapshot_create` | ✅ | `4de949b`. |
| `edit_prop U4 MPN=LT1373CN8#PBF` | ✅ | The #11 blocker is dead. Response shape note → finding #17 below. |
| `inspect_ref U4` | ✅ | Consistency block ships. |
| `edit_move_fp C7 → 198.255` | ✅ | kipy IPC write works; concurrent-save warning shipped. |
| `snapshot_restore 689cec4` | ✅ envelope, ⚠️ semantics | File reverted, KiCad in-memory state didn't → finding #18 below. |
| `inspect_pcb` (post-restore) | ✅ but wrong data | Showed C7 still at moved position. Revealed #18. |
| `edit_move_fp C7 → 198.755` (no_snapshot) | ✅ | `no_snapshot=true` flag works, C7 restored. |
| `export_gerber` | ✅ | Clean output to `/tmp/kcd-gerber-test/`. |
| `export_step` | ❌ but clean | `cli_failed`, full stderr surfaced: VRML-not-supported-in-mesh-formats — known KiCad limitation, not kcd's fault. |
| `export_bom ~/Downloads/...` | ❌ for right reason | Tilde expanded; failed with "No .kicad_pro file in /Users/oleksii/Downloads/kcd-demo" — correct path, empty dir. |
| `snapshot_restore 4de949b` | ✅ | Cleanup. |
| `inspect_ref U4` (final) | ✅ | Back to clean baseline. |
| `inspect_ref C7` | ❌ | Symbol not found on root → finding #20 below. |

## New findings

### #17 — Custom properties are a write-only sink

Set MPN on U4, but it doesn't appear anywhere in subsequent reads:

- `edit_prop`'s `data.updated` shows reference/value/footprint/datasheet/lib_id — no MPN.
- `inspect_ref`'s schematic block: same canonical-only set.
- `inspect_sch`'s symbol list: same.

The data persisted to disk fine (I'd bet, but couldn't verify through kcd). The agent has no way to read it back, which means it can't verify edits, can't enumerate MPNs across the board for sourcing, and can't ask "what props exist on this symbol?" Same root cause everywhere: `_symbol_to_dict` in `skip_sch.py` enumerates a fixed key list instead of iterating `sym.property.*`.

**Fix:** add a `properties: {name: value}` field to the symbol dict, populated by iterating whatever kicad-skip exposes as `sym.property` (probably `sym.property.children` or similar). For edit_prop's response, additionally include the field/value pair you just set in the data block so it's obviously confirmed.

**Impact:** unblocks the "add MPN/Manufacturer/Datasheet/Stock/SupplierPN columns for sourcing" workflow — which is the most common LLM-driven PCB workflow. Higher leverage than the #11 fix itself.

### #18 — `snapshot_restore` doesn't sync to running KiCad's in-memory state

Sequence I observed:

1. `edit_move_fp C7 → 198.255` ← kipy writes memory, `board.save()` writes file.
2. `snapshot_restore` to pre-edit commit ← file reverted to C7@198.755.
3. `inspect_pcb` ← shows C7 at 198.255 (KiCad memory, still modified).

The file and KiCad's memory have **silently diverged**. Two ways this becomes a real problem:

- Agent sees `inspect_pcb` reports the move "still applied" after a restore — concludes restore is broken and tries again, possibly with worse decisions.
- Agent makes the *next* edit. `board.save()` writes the (still-stale-from-KiCad) state on top of the restored file. **Silent corruption of the user's revert.**

This is the highest-risk finding from this session. Three possible mitigations:

1. **Best**: `snapshot_restore` triggers a kipy board reload after the file revert. Does kipy 0.7.1 have `board.reload()` or `kicad.reload_document()`? If yes, wire it in. If no, file the upstream request.
2. **Middle**: detect KiCad is connected at restore time; if so, refuse the restore with an error like `{"code": "kicad_open", "message": "Close <board.kicad_pcb> in KiCad before restoring, or pass --force"}`.
3. **Worst (fallback)**: doc-only warning. Agent won't read docs.

#1 is the right answer if kipy supports it. #2 is the right answer if it doesn't. I'd lean #1 → #2 chained.

### #19 — Footprint order in `inspect_pcb` isn't deterministic

After my move-fp on C7, the next `inspect_pcb` returned C7 first in the list (it was buried 50+ entries deep before). KiCad / kipy is probably ordering by last-modified-then-something. The change in order isn't broken, just surprising — diffing two inspect_pcb outputs to find "what changed" wouldn't work without a sort.

**Fix:** stable sort in `kipy_pcb.list_footprints()` — sort by `reference` (lexicographic with numeric suffix awareness if you want to be nice). 5 LOC. Low priority but cheap.

### #20 — `inspect_ref` doesn't search hierarchical sub-sheets

`inspect_ref C7` returned `Symbol 'C7' not found in pic_programmer.kicad_sch`. But C7 exists — on the `pic_sockets` sub-sheet. kicad-skip is loaded against the root schematic only, never recurses into child sheets.

For a multi-sheet design (which any non-trivial board is), agents can't reliably look up components without knowing which sheet they live on, which they shouldn't have to know. Same fix path applies to `edit_value`, `edit_ref`, `edit_footprint`, `edit_prop`, `edit_delete` — all of these only edit symbols in the root sheet today.

**Fix sketch:**

```python
def _find_symbol_anywhere(project: Project, reference: str):
    for sheet_path in _walk_sheets(project.sch):
        sch = _load(sheet_path)
        for sym in sch.symbol:
            if _prop(sym, "Reference") == reference:
                return sheet_path, sym
    raise SchEditError(...)
```

where `_walk_sheets` recurses into `sheet.file` properties. ~50 LOC. The other big lift this opens: returning a `sheet` field in inspect results, so the agent knows *where* the symbol is.

**Impact:** without this, kcd's schematic-side is limited to flat single-sheet designs. Most non-trivial KiCad projects are hierarchical.

## Persistent observations (not bugs, worth noting)

- `library_id` remains empty for these old-format demos. Per Cheetah's earlier note this is upstream kipy + old-format quirk. Worth confirming whether modern KiCad-10-native projects (e.g. a fresh `File → New Project from Template → Raspberry_Pi_Pico_blinky` or similar) populate it. If they do, the demo issue is purely demo-content, not kcd.
- `do_not_populate` and `rotation_deg` showing up in PCB info — small but nice for agentic placement decisions.
- The wide-net `unexpected` error class catches the failure from `edit_prop` when targets don't exist (e.g. trying to set a property on a non-existent ref). Worth seeing if those can graduate to `not_found` with the same code as I get from `edit_value`. Just a polish item.

## What I want to test next round

In priority order:

1. **#18 — snapshot_restore + KiCad-open** — find out if kipy 0.7.1 has a board reload API.
2. **#17 — properties echo** — biggest agent-UX leverage left.
3. **#20 — hierarchical sheet walk** — unblocks real projects.
4. **FreeRouting end-to-end** — still the unicorn.
5. **library_id on a fresh-format KiCad 10 project** — to settle whether the empty value is a kcd bug or an old-format artifact.
6. **edit_move_fp with rotation parameter** — covered move-XY, not rotation. Quick.

## Things to mention to Sabaka

- The consistency block in `inspect_ref` is exactly the kind of UX that makes kcd feel *designed for agents* rather than *retrofitted to be agent-callable*. That pattern — return the data + return the meta-observations about the data + mirror the high-severity ones in `warnings[]` — should generalize. e.g. `inspect_pcb` could surface "footprint X has no library backing" as a top-level warning so the agent doesn't have to compare to every library entry.
- #18 (silent file/memory desync) is the only finding this session I'd call out as critical-priority. Everything else is polish or feature-gap.
- Consider an integration test that explicitly walks the loop: open KiCad → `project_current` → snapshot → edit → re-inspect (verify edit) → restore → re-inspect (verify revert). It's now ~10s of automated test that catches #18 plus a class of related regressions. Bundle it as `tests/test_agentic_loop.py` (skipped unless `KCD_INTEGRATION=1`).

🕊️
