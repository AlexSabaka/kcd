# kicad SKILL.md — Field-Run Audit & Patch (post-R6)

**By:** Dove 🕊️ (R6 field-test session, used as the skill's test execution)
**Date:** 2026-05-21
**Target:** `/mnt/skills/user/kicad/SKILL.md` (698 lines, read-only)
**Method:** skill-creator's "evaluate → rewrite" half of the loop. The R6 run *is* the
evaluation: I followed this skill as the agent across a real diagnosis→fab editing
session on `Brushed_Flight_Controller`. Every finding below is anchored to a concrete
moment in that run, not a hypothetical.

---

## How to read this

Each finding carries:
- **Where** — SKILL.md section / approx. line range.
- **R6 moment** — what actually happened that exposed the issue.
- **Class** — `DOC-FIX` (skill text change, applyable now) or `CODE-BUG+CAVEAT`
  (a kcd defect surfaced via the skill; skill gets a temporary warning until Cheetah
  fixes the code).
- **Severity** — cost-to-agent during the run.
- **Fix** — exact proposed text or a pointer.

**Headline:** the skill is a *review* skill (~95% analyzers + the design-review
contract). R6 was an *editing* session, and the edit/render/snapshot/route/export
surface — where the whole run lived — is undocumented. The single highest-value change
is a new `references/agentic-editing.md` + a body pointer, NOT more inline bloat (the
file is already 698 lines, over skill-creator's ~500 ideal).

---

## A. Correctness / fact-check

### A1 — `analyze cross` description is aspirational `DOC-FIX` `medium`
**Where:** Cross-Domain Analysis, ~lines 265–273; mirrored in the MCP tool blurb.
**R6 moment:** `analyze cross` returned in **5 ms** with `summary.assessment_status:
"insufficient_data"` and 0 findings — it fast-failed *without* running the sub-analyzers,
because there were no datasheet/load-current inputs. The skill says it "Runs the schematic
and PCB analyzers internally."
**Fix:** Replace the second sentence with:

> Runs the schematic and PCB analyzers internally **when it has the inputs to do so**.
> When load-current and datasheet inputs are absent it short-circuits and returns
> `summary.assessment_status: "insufficient_data"` with 0 findings in milliseconds —
> **this is "unevaluated," not a clean bill of health.** Treat a `cross` result of 0
> findings as meaningful only when `assessment_status` is absent or `evaluated`.

This also correctly documents the R5-6 honesty feature, which the skill currently omits.

### A2 — `statistics.routing_complete` can lie `CODE-BUG+CAVEAT` `medium`
**Where:** PCB analyzer schema quick-ref, ~line 377 (`statistics: {... routing_complete ...}`).
**R6 moment:** In the same `analyze_pcb` payload, `connectivity.routing_complete: false`
+ `drc_unconnected: 16` (correct, R5-3 fix), while `statistics.routing_complete: true`
and `statistics.unrouted_net_count: 0` (stale). Cheetah noted he only reconciled the
`connectivity` block. An agent reading `statistics` first gets the wrong verdict.
**Fix (skill caveat now):** add to the JSON field cheat sheet (lines 165–179):

> | Routing completeness | `connectivity.routing_complete` + `connectivity.drc_unconnected` (DRC-reconciled, authoritative) | `statistics.routing_complete` / `statistics.unrouted_net_count` — net-level only; can read `true`/`0` while DRC still finds unconnected pads. Do not trust for fab-readiness. |

**Fix (code, for Cheetah):** make `statistics.routing_complete` derive from the same
DRC reconciliation, or drop it.

---

## B. Missing — the editing surface (the big one)

### B1 — Edit/render/snapshot/route/export commands are undocumented `DOC-FIX` `high`
**Where:** "Using this skill from kcd" (lines 21–44) lists only `kcd analyze *` and asserts
"the kcd CLI is the only surface." The agentic loop (54–61) stops at analyze + parity.
**R6 moment:** The entire run — `render_pcb` (region crop), `edit_move_fp`, `route_track`,
`snapshot_create/restore`, `edit_symbol`, `edit_pcb_text`, `export_gerber` — used tools the
skill never names. I discovered each via `tool_search` and learned their pitfalls live.
**Fix:** Add a short body section + a new reference file (keeps SKILL.md lean):

> ## Agentic Editing & Iteration
> The analyzers above are read-only review. kcd also exposes an **editing surface** for
> carrying a board from diagnosis toward fab: `edit_move_fp` / `edit_track_*` /
> `edit_via_add` / `edit_zone_*` / `route_track` / `edit_symbol` / `edit_net` /
> `edit_pcb_text` (PCB), the schematic-edit family, `snapshot_*`, `render_*`, and
> `export_*`. The canonical pattern and the KiCad/IPC constraints that govern them live
> in **`references/agentic-editing.md`** — read it before any mutating session.

See proposed reference outline in **§F**.

### B2 — Operational ceilings live in the field brief, not the skill `DOC-FIX` `high`
**Where:** nowhere in SKILL.md. These are persistent KiCad facts, not field ephemera.
**R6 moment:** I knew to run PCB-editor-only and that U1 couldn't forward-annotate only
because the field brief told me. A fresh agent reading just the skill would dual-open
editors (segfault) or expect a schematic edit to reach the board.
**Fix:** In `references/agentic-editing.md` (and a one-line flag in the body):

> **KiCad ceilings (10.0.2) — these are KiCad's limits, not kcd's:**
> - **No headless forward annotation (F8).** Schematic edits do NOT propagate to the PCB.
>   `sync --check` reports the drift honestly but cannot push it. A symbol/footprint
>   change is therefore stranded on the schematic side in a PCB-centric session.
> - **Dual-editor IPC segfault.** Having both the schematic and PCB editors open at once
>   crashes IPC routing. **Run PCB-editor-only for all mutating IPC tools.** Confirm with
>   `project_current` before mutating.
> - **`board.save()` dirty-state.** Every mutating IPC edit persists *all* unsaved
>   PCB-editor changes (kipy 0.7.1 has no dirty-check). Save or revert in the editor
>   before driving kcd.

### B3 — No `region_window` sizing guidance `DOC-FIX` `low` (but pure waste)
**Where:** renders undocumented; once added, the render section.
**R6 moment:** I rendered a 24 mm `region_bbox` to inspect a 0402 move and couldn't see
the pads or 0.15 mm stubs; had to re-render at ~9 mm. One sentence saves a round-trip on
every placement task.
**Fix:** in the render docs:

> `region_window`/`region_bbox` sizing: ~20 mm is **neighborhood** scale (did the part
> land in the right area, gross collisions). For **fine-placement** verification — 0402
> pads, 0.15 mm dangling stubs, sub-mm clearances — use **~6–10 mm**. The crop is
> calibrated to the board-outline bbox (verified to the micron in R6), so the reported
> `region_mm` center equals the footprint's true coordinates.

### B4 — Container-vs-host artifact paths `DOC-FIX` `medium`
**Where:** Artifacts notes, ~lines 46–52 and 290–295 (`$KCD_RENDER_CACHE/...`).
**R6 moment:** Analyzer artifacts landed at `/tmp/kcd/...` (the KiCad **host**), which the
agent's container CANNOT read. I wanted to byte-measure B2 from the artifact and couldn't.
Big analyzer payloads that overflow context spill to `/mnt/user-data/tool_results/...`,
which the agent CAN read.
**Fix:** add to the Artifacts note:

> **Filesystem split (agent-relevant):** the `path` in `artifacts[]` (e.g.
> `/tmp/kcd/<name>.json`) is on the **KiCad host** and is **not readable** from the
> agent's container. When a payload is too large for context the harness spills a copy to
> **`/mnt/user-data/tool_results/...json`**, which the agent **can** `bash`/`grep`.
> To parse analyzer output, read the inline envelope `data`, or the spilled
> `/mnt/user-data/tool_results` copy — never assume the `/tmp/kcd` path is reachable.

### B5 — The measure→mutate→measure loop isn't codified `DOC-FIX` `high`
**Where:** the agentic loop (54–61) ends at analysis.
**R6 moment:** The capstone (snapshot → render → DRC-baseline → move → render → reroute →
DRC-delta → keep/revert) is the correct edit pattern and worked end-to-end, but I carried
it from the field brief, not the skill.
**Fix:** in `references/agentic-editing.md`:

> **The edit loop:** `snapshot_create` (label it) → measure baseline (`drc` / `analyze_*`)
> → render the region BEFORE → mutate (one change) → render the region AFTER (verify it
> landed and didn't collide) → reroute/refill stranded copper → measure delta → **keep
> only if net-positive, else `snapshot_restore`.** Snapshot before *every* mutation; the
> human may be away — never leave a half-rerouted board.

---

## C. Zone staleness extends to the edit path `DOC-FIX` `medium`
**Where:** "Zone fills must be current" (line 244) — currently scoped to *analysis* only.
**R6 moment:** Moving C22 stranded its pour-bonded GND; `route_track` reconnected the net
but left dangling far-ends, because a moved pad can't re-bond to the GND pour and there is
**no standalone zone-refill primitive** (only `edit_zone_add` refills, as a side effect of
adding a zone). This produced the +3 `track_dangling` warnings in my otherwise −6-error
capstone.
**Fix (skill):** extend the line-244 note:

> This also applies **after edits**: `move_fp` / `route_track` / `edit_track_*` leave zone
> fills stale, and a moved SMD pad will not re-bond to a pour without a via. kcd has **no
> standalone refill** — re-bond manually (`edit_via_add` to drop the pad's net to the pour
> layer) or accept and document the staleness. Verify with `drc` (`unconnected_items` /
> `track_dangling`) and `analyze_pcb` zone `is_filled`/`fill_ratio` — never eyeball a render.

**Fix (code, for Cheetah):** a `kcd refill-zones` primitive, and/or `route_track`
snap-to-nearest-pad/copper so reroutes don't leave dangling far-ends. This is the single
biggest friction multiplier for agent-driven placement — every move generates this debt.

---

## D. Confusing / underspecified

### D1 — `edit_symbol` pin-map + the derived-symbol (`extends`) trap `CODE-BUG+CAVEAT` `high`
**Where:** `edit_symbol` undocumented in skill; would belong in `references/agentic-editing.md`.
**R6 moment:** The U1 NCP1117→AP2112K-3.3 swap. `pin_map` rejected both numeric (`1=2,...`)
and name (`1=GND,...`) forms with `bad_pin_map ... new: [...] unknown` — because `lib_show
Regulator_Linear:AP2112K-3.3` returns **`pins: []`**. So does `AP2112K-1.2`. But
`lib_show Device:R` returns its 2 pins correctly. Strongly consistent with **kcd not
following KiCad's `extends` (symbol inheritance)** — derived symbols (most of the regulator
families, many MCUs) appear pin-less, so `edit_symbol` cannot target them at all.
**Fix (skill caveat now):**

> **Swapping to a derived symbol currently fails.** Many stock KiCad parts (fixed-voltage
> regulator variants, MCU variants) are *derived* symbols that inherit pins from a base via
> `extends`. kcd does not yet resolve inheritance, so `lib_show` returns `pins: []` for them
> and `edit_symbol`'s `pin_map` rejects every reference (`bad_pin_map ... unknown`). Until
> fixed, `edit_symbol` only targets base symbols (those whose `lib_show` shows pins). To
> check first: `lib_show <target>` — empty `pins` ⇒ the swap will fail.

**Fix (code, for Cheetah), priority order:**
1. **Resolve `extends` in the symbol-pin parser.** Self-contained; unblocks `lib_show` and
   `edit_symbol` for the common case. (Confirm the exact mechanism — both AP2112K variants
   returned empty, so the base may itself extend deeper, or it's library-structural.)
2. `bad_pin_map` should **enumerate the target's valid pin identifiers** instead of just
   "unknown" — it sent me guessing twice.
3. The real U1 enabler is a **PCB-side footprint-swap** (`edit_swap_fp <ref> <new_fp>` with
   pad→net remap) that bypasses the F8 round-trip kcd can't perform.

### D2 — `edit_net` PCB-drift check is a false-green `CODE-BUG+CAVEAT` `medium`
**Where:** `edit_net` undocumented in skill.
**R6 moment:** Renaming the schematic label `ELRS_TX`→`ELRS_TX_T` returned
`pcb: {old_net_present: false, stale: false}`. But the board carries this net as
**`/ELRS_TX`** (root sheet-path prefix). The check compares the *bare* label name against
the *prefixed* PCB net, fails to match, and reports "not stale" — defeating the very
F8-honesty signal it exists to provide. An agent would believe the rename fully propagated
or that there's no drift to reconcile.
**Fix (code, for Cheetah):** normalize the leading `/` (and sheet path) before comparing.
**Fix (skill caveat):** note that `edit_net`'s `pcb.stale`/`old_net_present` are unreliable
for prefixed nets; confirm drift with `parity` / `net_of` instead.

---

## E. Keep as-is — verified effective in R6 (don't regress these)

- **DS-001 "consistency only" discipline** (86–88). Clear; I correctly refused to assert the
  MX1508 VCC/VDD pin bug. The most load-bearing safety rail in the skill.
- **JSON field cheat sheet** (165–179). Read the envelope by hand all session, zero shape
  crashes. (Augment per A2; otherwise leave.)
- **"Announce what you're checking before each probe"** (641–646). Kept the run legible.
- **Defensive JSON-shape patterns** (648–657). Good guardrails.
- **Analyzer command reference + output schema quick-ref** — accurate for analyzers
  (`footprints[].x` not `.position.x`; `nets` keyed by name; `zones[].net` integer id).

One efficiency nit for the schema ref (not a correctness bug): the inline `analyze_pcb`
envelope ships both `nets` and `net_name_to_id` — inverse views of the same 80-entry map —
fully inline, plus the 44-element component lists in *both* `ground_domains` and
`copper_presence`. That's the bulk of the B2 over-budget. Worth a note that these are
de-dupe/spill candidates (a Cheetah item, but the skill could flag the duplication so agents
don't read both).

---

## F. Proposed new file: `references/agentic-editing.md`

Rationale (skill-creator progressive disclosure): SKILL.md is already 698 lines, over the
~500 ideal. Don't inline the editing depth — put it here and point from the body (B1).

Outline:
1. **The edit loop** (B5) — snapshot → measure → render-before → mutate → render-after →
   reroute/refill → measure-delta → keep/revert.
2. **KiCad ceilings & IPC constraints** (B2) — F8, dual-editor segfault, board.save().
3. **Render for editing** (B3) — region_window sizing; calibration note; renders are for
   *seeing*, DRC/analyze for *measuring* (don't eyeball pours/connectivity).
4. **Mutating-tool catalog** — one line each: `move_fp`, `track_*`, `via_add`, `zone_*`
   (refill side-effect; no standalone refill — C), `route_track` (no snap-to-copper —
   leaves dangling; reroute to verified endpoints, not estimates), `edit_symbol`
   (pin-map scheme; derived-symbol trap — D1), `edit_net` (F8; drift-check caveat — D2),
   `edit_pcb_text` (the R5-7 silk primitive — supersedes the old "no PCB-silk-text" note),
   `edit_text_titleblock` (schematic title block, NOT PCB silk).
5. **Artifact filesystem split** (B4).
6. **Verification discipline** — every kept change backed by a DRC/analyze delta;
   `snapshot_restore` is the safety net, test it deliberately.

---

## G. Summary table

| # | Finding | Where | Class | Sev |
|---|---------|-------|-------|-----|
| A1 | `analyze cross` "runs analyzers" is aspirational; document fast-fail/insufficient_data | 265–273 | DOC-FIX | med |
| A2 | `statistics.routing_complete` can disagree with DRC-reconciled `connectivity` | 377 | CODE+CAVEAT | med |
| B1 | Edit/render/snapshot/route/export surface undocumented | 21–44 | DOC-FIX | high |
| B2 | KiCad ceilings (F8, dual-editor segfault, board.save) not in skill | — | DOC-FIX | high |
| B3 | No `region_window` sizing guidance | — | DOC-FIX | low |
| B4 | `/tmp/kcd` host artifacts unreadable from container; `/mnt/.../tool_results` is | 46–52, 290–295 | DOC-FIX | med |
| B5 | measure→mutate→measure loop not codified | 54–61 | DOC-FIX | high |
| C | Zone staleness/no-refill applies to edits, not just analysis | 244 | DOC-FIX (+code) | med |
| D1 | `edit_symbol` can't target derived (`extends`) symbols; pin-map opaque | — | CODE+CAVEAT | high |
| D2 | `edit_net` PCB-drift check false-greens on prefixed nets | — | CODE+CAVEAT | med |

DOC-FIX items are applyable to the skill now. CODE+CAVEAT items get a temporary skill
warning and a Cheetah ticket; remove the caveat when the code lands.
