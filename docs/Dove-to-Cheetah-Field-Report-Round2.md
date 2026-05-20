# kcd Toolset — Field Report, Round 2

**Author:** Claude (agentic session)
**Test vehicle:** `Brushed_Flight_Controller` (same board, post-F8 state)
**Config:** PCB editor open, schematic editor closed; full tool schema preloaded (no lazy discovery)
**Date:** 2026-05-20
**Predecessor:** `Dove-to-Cheetah-Field-Report.md` (Round 1)

---

## TL;DR

Cheetah shipped essentially the entire Round-1 wishlist — net inspection, parity, sync, symbol add/swap, wire/netlabel edits, track/via/zone edits, design-rule edits, routing, 3D render. The result is a different class of tool: **this session went from "diagnose and hand off" to actually mutating the board and watching DRC respond** (234+22 violations → 181+20 after one cleanup operation).

The two Round-1 "P0" gaps resolved as follows:

- **Net inspection — fully closed.** `net_pcb` / `net_of` / `net_trace` / `net_list` are excellent. The net-blindness that made me *guess* in Round 1 is gone. `net_of +12V` handed me every stranded track with geometry, layer, and width.
- **Forward annotation — closed as far as KiCad permits, which is "not fully."** `sync --check` and `parity` give precise drift visibility, but KiCad 10 exposes no headless forward-annotation API, so neither can actually *push* sch→pcb. This is a hard KiCad ceiling, and the tools are honest about it. The residual is that orphan footprints (U3/L1/D1) can't be removed from the PCB by any current primitive (see Gap-Still-Open #1).

Net: the foundation is now genuinely strong. What remains is a cluster of **concrete bugs** (below) and **two KiCad-imposed ceilings** the toolset routes around imperfectly.

---

## What I exercised this round

`project_current`, `parity`, `net_pcb`, `net_of`, `sync --check`, `drc` (×2), `snapshot_create`, `edit_designrules` (probe + set), `edit_track_delete`, `route_track`. Read-then-mutate-then-measure, with a snapshot (`719b9a5`) before mutating.

**Headline result on the board:** deleting the 34 orphan `+12V` tracks (dead buck-output copper) removed ~53 DRC violations in one call — they'd been shorting and mask-bridging against the now-`+BATT` motor pads. Clean demonstration of the measure→mutate→measure loop the new tools enable.

---

## New bugs found this round

| # | Severity | Tool | Bug |
|---|---|---|---|
| 1 | **HIGH** | `route_track` | Layer enum is broken and inconsistent. The schema's documented **default `"F.Cu"` FAILS** (`ValueError: unknown enum label "F.Cu"`). So does `"F_Cu"`. Only the kipy label **`"BL_F_Cu"`** works — but that's *not* the form any other tool accepts or emits: `net_of` and `track_delete` both **return** `"layer": "F.Cu"`. So an agent that reads a track's layer and feeds it straight back into `route_track` gets a hard error. Fix: accept `"F.Cu"` (and ideally the bare default should be valid), normalize internally. |
| 2 | **HIGH** | `parity` | `footprint_mismatches` reports `"pcb": ""` (empty) for **every** component — all 60+. The PCB-side footprint ID isn't being read, so footprint parity is effectively non-functional (it flags everything as a mismatch). The board demonstrably has valid footprints (DRC resolves them with pads/positions), so this is a read bug in parity's PCB-side fpid lookup, not reality. |
| 3 | **MEDIUM-HIGH** | `edit_designrules` | **Silent no-op while KiCad holds the project.** Setting `min_through_hole_diameter` 0.3→0.2 returned `ok:true` with a clean before/after, but DRC still reported `min hole 0.3000 mm` on all 51 drill errors — KiCad's cached project settings overwrote the `.kicad_pro` edit. The tool *warns* about this, and the warning proved exactly true. Problem: it returns success for an edit that had zero effect. Consider hard-failing (or refusing) when `project_current` shows the project open, rather than writing-and-hoping. |
| 4 | **MEDIUM** | `parity` | `schematic_only` lists all **74 `#PWR` power-flag symbols** as drift. Power flags have no footprint and never appear on a PCB by design — flagging them buries the one real signal (the 3 genuine orphans) under 74 false ones. Filter `#PWR*` / no-footprint / `exclude_from_board` symbols out of the parity diff. |
| 5 | **LOW** | snapshots | **Failed mutating calls still create snapshots.** Both failed `route_track` attempts and the failed `edit_designrules` probe populated `snapshot_before`. Minor history noise; consider only snapshotting on a mutation that actually lands. |

---

## Gaps still open (KiCad ceilings the toolset can't fully bridge)

1. **No PCB-footprint delete.** To remove U3/L1/D1 from the *board*, there's still no primitive — `edit_delete` is schematic-only. The only paths are F8-with-"delete extra footprints" or manual GUI delete. kipy can remove footprints from a board object; a `kcd_edit_delete_footprint` may be feasible and would close the last bit of the "execute a deletion end-to-end" loop. Worth investigating.

2. **No headless forward annotation.** Confirmed hard KiCad-10 limit; `sync`/`parity` document it honestly. The agent's workaround is direct PCB mutation (track/via/zone edits + `route_track`), which works but is reconstruction, not reconciliation — and it can't remove footprints (see #1). Not Cheetah's bug to fix; just the boundary of what's automatable today.

3. **Concurrency model.** Two distinct footguns surfaced, both well-warned:
   - `edit_designrules` writes `.kicad_pro`, which KiCad overwrites on its next save (bug #3 above).
   - Mutating IPC calls invoke `board.save()`, persisting *any* unsaved PCB-editor changes (kipy 0.7.1 has no dirty-check). 
   The warnings are good. The stronger fix is a session model: detect the open project once, and either route all edits through KiCad's IPC (so they respect/refresh the live state) or require a clean/closed editor for the file-level ones.

---

## What's genuinely excellent (don't regress)

- **The net-inspection family.** `net_of <net>` returning full pad+track+via+zone membership with geometry is the single biggest quality-of-life jump. It's what let me confirm the `+12V` orphan precisely instead of inferring from DRC strings.
- **`sync --check` honesty.** `components_removed: [D1,L1,U3]`, `net_changes: []`, plus a warning that names the exact KiCad menu action and explains *why* kcd can't do it. This is the right way to handle a capability boundary.
- **Discoverable enums via error.** `edit_designrules` with a bogus rule returns the full valid-key list. More tools should do this (and `route_track`'s layer enum should, given bug #1).
- **Mutation echoes + before/after.** `edit_designrules` returned `before:0.3, after:0.2`; `track_delete` returned all 34 deleted segments with `count`. Easy to verify and to log.
- **Large-result handling.** The 234-violation DRC spilled to a file path automatically rather than blowing the response. Good.

---

## To actually finish this board (sequence for the human)

The tools got me far, but the KiCad ceilings mean a few steps need the GUI. Recommended order:

1. **Close KiCad** (or at least the project).
2. Re-apply `kcd parts`... — re-run `edit_designrules min_through_hole_diameter 0.2` *with the project closed* so it sticks (or just accept 0.3 and resize vias). Verify via a closed-project DRC.
3. **Reopen in KiCad, run F8 with "delete extra footprints" checked** — removes U3/L1/D1 from the board. (Or, if Cheetah adds footprint-delete, do it headless.)
4. **Re-route motor power.** Deleting the orphan +12V copper correctly exposed ~14 `+BATT` unconnected pads — that was dead/mis-netted copper serving as the only physical tie between the MX1508 VCC pins and bulk caps. `route_track` (with `BL_F_Cu`) works for this; the +BATT motor bus wants wide traces (≥0.5 mm) given motor current.
5. **Fix the remaining real shorts** that aren't +12V-related: the USB-C J7 `SH` shield pad (`<no net>`) shorting to GND on multiple segments (decide shield strategy — direct GND vs cap+R), and the `/OUTA1`,`/OUTA2` tracks crossing U5's GND pads 10/11/15 (genuine routing collision from Round 1, still present).
6. **Courtyard overlaps** on C20/C22/C26/C28 vs the MX1508s — the tiny caps are jammed into the driver courtyards; nudge them with `edit_move_fp`.
7. Re-run DRC, iterate.

---

## Bottom line

Round 1 the verdict was "excellent read + diagnose, can't really mutate." Round 2 it's "**read + diagnose + mutate, with a handful of enum/parity bugs and two KiCad-imposed ceilings.**" The bugs (#1–#4) are all concrete and fixable. The ceilings (forward annotation, footprint delete) are mostly KiCad's, and `sync`/`parity` already handle them with the right honesty. Fix `route_track`'s layer enum and `parity`'s PCB-footprint read, decide the concurrency story for `edit_designrules`, and this is a tool that can carry a refactor from diagnosis to a fab-ready board with the human only touching the two genuinely KiCad-locked steps.

**Snapshots from this session:** `719b9a5` (pre-mutation baseline) → orphan-track delete + designrule attempt + one +BATT track. Restore `719b9a5` to revert all Round-2 mutations.
