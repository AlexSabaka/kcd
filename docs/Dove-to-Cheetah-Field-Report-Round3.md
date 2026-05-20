# Field Report: kcd Toolset — Round 3

**For:** Cheetah (implementer)
**From:** Dove 🕊️ (R3 field-test session)
**Date:** 2026-05-20
**Vehicle:** `Brushed_Flight_Controller` (KiCad 10, PCB editor open, post-`Update PCB from Schematic`)
**Prior:** `kcd_field_report.md` (R1), `kcd_field_report_round2.md` (R2). This is the R3 verdict layer.

---

## 0. Verdict in one paragraph

The rework landed. **All four R2 bugs are confirmed fixed**, the **PCB-footprint-delete ceiling is gone** (`edit_delete_fp` exists and works), and the **concurrency story is genuinely solid** for the PCB-editor-only config. The board went 200 → 190 DRC and now passes parity cleanly after the orphan removal that R1/R2 couldn't do. But the session surfaced a coherent **new class of problem that is not about any single tool**: in the MCP-remote topology, several outputs the agent needs (renders, large analyzer JSON, zone-heavy diffs) **never reach the agent** — they're written to the operator's disk or rejected at the 1MB MCP cap. And three summary scores (`routing_completeness`, `thermal_score`, and the MPN gate) **report confident success from empty or partial evaluation**. One genuine new code bug: `edit_move_fp` crashes on any rotation.

---

## 1. R2 bug verdicts (all backed by a real call)

| # | R2 bug | Verdict | Evidence |
|---|--------|---------|----------|
| 1 | `route_track` default `"F.Cu"` rejected; only `"BL_F_Cu"` worked | **FIXED** | `route_track ... layer=(default F.Cu)` created a track and round-tripped `layer:"F.Cu"`. Enum is now consistent with what `net_of`/`track_delete` emit. |
| 2 | `parity` reported `"pcb":""` for all footprints (PCB fpid read broken) | **FIXED** | `parity` correctly enumerated the board side and returned `pcb_only:["D1","L1","U3"]` — impossible if the fpid read were dead. `footprint_mismatches:[]` is legitimate post-F8. |
| 3 | `edit_designrules` silent no-op + fake `ok:true` while KiCad holds the project | **FIXED** | Now refuses **loudly**: `ok:false`, `code:"project_open_in_kicad"`, with a message explaining KiCad's cached-settings clobber and offering `--force`. This is exactly the "fail loudly when it can't take effect" the R2 report asked for. |
| 4 | `parity` `schematic_only` flooded with 74 `#PWR` flags | **FIXED** | `schematic_only:[]`. No power-flag noise. |
| — | (minor) failed mutating calls still snapshot | **likely fixed** | Failed `edit_track_delete` (not_found) and the failed rotation `move_fp` both returned `snapshot_before:null`. No spurious snapshot on failure. |

**Open questions from the brief, answered:**
- *PCB-footprint-delete primitive?* — **Yes.** `edit_delete_fp <ref>`. Checks `had_symbol` first (refused-class safety; here all three were `false`), then removes via IPC + `board.save()`.
- *Concurrency model changed?* — **Yes, and well.** Mutating PCB tools work correctly with KiCad open in the PCB editor; `edit_designrules` (which touches `.kicad_pro`, separately cached) now hard-refuses instead of faking success.
- *New tools?* — `edit_delete_fp` is the headline. Tool docstrings now carry explicit concurrency contracts (PCB-editor-only segfault warning; `board.save()` dirty-state caveat).

---

## 2. New capabilities — confirmed working

- **`edit_delete_fp`** removed D1 (PMEG4030ER), L1 (47µH), U3 (APE1707H-12-HF) — the orphan boost circuit F8 can't touch (Image 5: "Delete footprints with no symbols" unchecked, and KiCad has no headless F8 anyway). Post-delete **parity is fully clean** (`pcb_only:[]`). End-to-end win, and it closes a gap open since R1.
- **Concurrency, PCB-editor-only:** every mutating IPC call (`delete_fp`, `track_delete`, `track_modify`, `move_fp`, `via_add`, `zone_add`, `route_track`) succeeded and emitted the honest warning: *"board.save() — any unsaved changes in KiCad's PCB editor are persisted along with this edit; kipy 0.7.1 has no dirty-check API."* That warning is a real strength — keep it.
- **Snapshot safety net:** `snapshot_create` returns SHAs; auto-snapshot-on-edit works; `no_snapshot:true` is honored. I left two named refs: baseline `b166317`, end-state `ffe8ab2`.
- **Graceful external-tool failure:** `route_freeroute` returns `code:"no_jar"` with the env var + download URL. No crash. (Untestable here — JAR not installed.)

---

## 3. New bugs found in R3 (prioritized)

### HIGH

**B1 — `edit_move_fp` crashes on any `rotation` argument.**
`move_fp ref=C21 x=.. y=.. rotation=90` →
`ImportError: cannot import name 'Angle' from 'kipy.common_types'`.
Rotation-*less* moves work fine (they skip that import) and **preserve existing rotation**. So position-only moves are safe; any rotate-during-move is dead. kipy 0.7.1 relocated/removed `Angle` — repoint the import (likely `kipy.geometry` / the newer angle API). *Caught live: my C21 round-trip failed on the restore leg and I had to re-move without rotation.*

**B2 — `analyze_sch` is unusable over MCP: result exceeds the 1MB cap and is hard-rejected.**
On a 58-component board, `analyze_sch` returned `"Tool result is too large. Maximum size is 1MB."` — unrecoverable inline. `analyze_pcb` (274K) landed in the spill-to-file band and was readable; `analyze_sch` did not. Root cause: the `analyze_*` MCP wrappers **inline the entire analyzer JSON**, unlike `drc`/`erc` which fold (grouped types + 3-sample occurrences + full report spilled to artifact). **Fix: give the `analyze_*` wrappers the same fold-and-spill treatment `drc`/`erc` already have** — return envelope summary + `findings` + `warnings` + artifact path inline; never inline the full `data`.

**B3 — Renders are write-only from the agent's side.**
`render_pcb` / `render_3d` succeed and return an artifact *path* on the operator's filesystem (`/Volumes/2TB/...`) — the bytes never come back inline. In MCP-remote operation the agent **cannot see its own render**. This reframes the R1/R2 "render-first" self-criticism: rendering wouldn't have given *me* a visual model either; the fix is on the tooling side. **Fix: have render tools return inline image content (base64 PNG/SVG, or a small rasterized preview), or expose an artifact-fetch channel into the agent's context.** Until then, render-first only helps a human-in-the-loop, and the operator's manual screenshots are doing that job.
*(This isn't theoretical — see §5: two of my three geometry edits introduced a clearance violation precisely because I was placing blind.)*

### MEDIUM

**B4 — `snapshot_diff` also overflows the 1MB cap on zone-touching diffs.** After adding the GND pour, `snapshot_diff baseline→worktree` was hard-rejected (the filled-zone polygon is thousands of points in the `.kicad_pcb`). Same remedy class as B2: fold/summarize (files-changed + per-file hunk counts + stat), spill the full unified diff to an artifact.

**B5 — `analyze_fab_gate` reports "all nets routed" while DRC finds 16 unconnected.** `routing_completeness: PASS "All nets routed (80/80)"` vs DRC `unconnected:16`. The gate's analyzer-side union-find counts a net "routed" if it carries any track, missing pad-level gaps (the +BATT orphan-region pads). A fab-gate that green-lights routing while DRC has unconnected pads is a false-confidence trap. **Reconcile the gate against DRC unconnected before passing the routing check.**

**B6 — Perfect scores from empty assessment.** `analyze_thermal` returned `thermal_score:100` with `components_assessed:0` and `total_board_dissipation_w:0` on a board with an LDO and four motor drivers (it couldn't classify power components without load currents / MPNs). Same shape as B5's "80/80". A confident 100 from zero evaluation is worse than no score. **Distinguish "0 issues found" from "0 items evaluated" in every summary score; surface the latter as `insufficient_data`, not a pass.** (`provenance_coverage_pct:null` is the only current hint.)

**B7 — MPN-coverage check ignores the `MP` field.** `fab_gate mpn_coverage: 0/58` — but U5/U7 carry `"MP":"MX1508"` + `MANUFACTURER` (SnapEDA convention). The check only recognizes a literal `MPN` field. Undercounts to zero, which also drags the trust posture's `evidence_blockers`. **Recognize `MP`/`MPN`/`Mfr_Part_No` aliases** (this is exactly the BOM identity-normalization the parts-knowledge-layer doc scopes — good cross-link for that work).

**B8 — `inspect_ref` consistency doesn't flag value↔symbol↔datasheet incoherence.** U1 has `value:"AP2112K-3.3"` but `lib_id:NCP1117-3.3_SOT223`, footprint `SOT-223-3`, datasheet NCP1117 — yet `consistency.value_matches:true, footprint_matches:true` (consistency only checks schematic-vs-PCB agreement). The raw fields are exposed (good — a careful agent catches it), but nothing *flags* the internal contradiction. **Add a part-identity coherence check** (value name vs symbol family vs datasheet vendor). Also a direct parts-knowledge-layer cross-link.

### LOW / cosmetic

- **B9** — After `edit_delete_fp`, copper on the deleted part's local net **migrates to a surviving co-net** (U3-FB's tracks moved to `Net-(R5-Pad2)`), so `edit_track_delete net=Net-(U3-FB)` returns `not_found`. Not a bug per se, but a workflow gotcha: **re-query `net_pcb` after a footprint delete; the old local-net handle may be gone.** Worth a one-line note in the `edit_delete_fp` docstring.
- **B10** — `lib_list` (even with `project=`) returns only the 222 global libs; project-local/embedded symbol libs (`mx1508:`) don't appear. Fine if symbols are embedded, but an agent trying to `lib_show` a project part won't find it via `lib_list`.
- **B11** — `analyze_pcb` `trust_summary.provenance_coverage_pct: 0.0` despite `by_evidence_source.topology:59` and `trust_level:"high"`. Coverage % looks miscomputed.
- **B12** — `analyze_pcb` `statistics.track_count: None` (tracks counted elsewhere). Minor schema gap; also `pad_nets`/`connected_nets` carry net mapping but **no per-pad XY** — which is why placement edits need DRC/`net_of` coords instead.
- **B13** — Net counts disagree across tools: `sync` schematic_nets=51, `fab_gate` schematic_nets=77, PCB nets=80. Unify the counter or document the difference.
- **B14** — Failed/no-op mutating calls still print the `board.save()` warning (e.g., `not_found` track delete). Cosmetic; suppress the warning when nothing was written.

---

## 4. analyze_* vs DRC (brief §4.3)

They are **complementary, not redundant** — run both in a fab-gate:
- **`analyze_pcb`** is design-review-shaped: edge-clearance with distances (PM-002), courtyard overlap with mm² (PM-001), narrow-signal (CC-002), no-fiducial (FD-001), unrouted nets (RT-001), and **caught what DRC structurally can't flag — zero copper zones on the whole board** (`zone_count:0`).
- **`drc`** is fab-grounded: board-setup rule violations DRC owns — `drill_out_of_range` (0.2mm holes vs 0.3mm rule), `solder_mask_bridge`, `shorting_items`, `hole_clearance`. These don't appear in `analyze_pcb`.

`analyze_pcb` for triage and design intent; DRC for the rule-bound fab verdict. Neither dominates.

---

## 5. Tools exercised this round (untested list materially reduced)

**Read/inspect:** `project_current`, `render_pcb`, `render_3d`, `parity` ×2, `sync --check`, `net_pcb` ×2, `net_of`, `inspect_ref` ×2, `analyze_pcb`, `analyze_sch` (overflow), `analyze_fab_gate`, `analyze_thermal`, `drc` ×2, `lib_list`, `snapshot_create` ×2, `snapshot_diff` (overflow).
**Edit/mutate:** `edit_designrules` (loud-fail path), `edit_delete_fp` ×3, `edit_track_delete` (net selector + segment selector), `route_track` (default-layer path), `edit_track_modify` ×2, `edit_move_fp` ×3 (incl. rotation-crash), `edit_zone_add`, `edit_via_add`, `edit_prop`, `route_freeroute` (graceful no-JAR).

**Still untested (next round):** `render_sch` (only fired indirectly via `edit_prop` auto-render), `analyze_cross`, `analyze_whatif`, `analyze_lifecycle`, `analyze_diff`, `erc`, `inspect_sch`, `edit_net`, `edit_symbol`, `edit_add_symbol`, `edit_wire_add/delete`, `edit_netlabel_add/delete`, `edit_text_set/titleblock`, `edit_zone_delete`, `snapshot_restore`, the `export_*` family. **Note:** the schematic-edit family was deprioritized — the highest-value schematic fix (U1, §6) needs a human decision, and editing the `.kicad_sch` while only the PCB is open can't be reconciled headlessly (no F8).

---

## 6. Board-level findings (real design issues the tools surfaced)

These are byproducts of the test, but several are genuinely worth your attention:

1. **U1 is electrically still an NCP1117, labeled AP2112K.** `value:"AP2112K-3.3"` but `lib_id:NCP1117-3.3_SOT223`, footprint `SOT-223-3_TabPin2`, datasheet NCP1117. R1's "swap" was a value-string edit only. Consequences: (a) the **R2 "EN tied to +3.3V startup-latch" flag is moot** — NCP1117 has no EN pin, so there's nothing to latch; the concern only re-emerges after a *real* swap; (b) **SOT-223-3 ≠ AP2112K's SOT-23-5** — a literal AP2112K won't fit the footprint. I fixed the one defensible axis (datasheet URL → AP2112K via `edit_prop`); **the symbol+footprint swap needs your call on which physical part you're actually populating.**
2. **MX1508 VCC/VDD pin assignment is unverifiable.** `+BATT` lands on U5/U7 pads 1 & 5 (the VCC pins per the schematic labels). Whether VCC or VDD is the motor-supply pin can't be confirmed — the MX1508 `datasheet` field is empty (DS-001 class). This is the exact pinout-ambiguity the parts-knowledge-layer is built to resolve. **Treated as consistency-only; not asserted as a bug.**
3. **No ground pour anywhere** (`zone_count:0`) on a 2-layer board with motor drivers and an ESP32-S3 antenna. 386 GND tracks hand-routed. **I added a B.Cu GND pour** (kept in the end state).
4. **35 `+BATT`↔GND shorts**, mostly GND tracks crossing U7 pad 1 (+BATT) at (160.9975, 113.2455) — a direct consequence of hand-routing GND with no plane.
5. **J7 USB-C shield/mounting pads (S1, SH) aren't in the symbol** → no-net → mask bridges + shorts. This is the exact Image 5 F8 error ("J7 pad S1 not found"). Needs a symbol with shield pins or explicit shield-to-GND handling.
6. **51 `drill_out_of_range`** — 0.2mm via holes vs a 0.3mm min-hole rule. **There is no `edit_via_modify` to resize vias**, so the only kcd path is `edit_designrules min_hole=0.2` (KiCad closed, or `--force`). The brief's "resize the vias instead" workaround isn't actually available — see Ceilings.

---

## 7. What I changed on the board (end state `ffe8ab2`, baseline `b166317`)

Kept: D1/L1/U3 deleted; `Net-(D1-K)` dangling tracks swept; B.Cu GND pour added; GND stitch via at C14 (0.3mm drill, rule-compliant); U1 datasheet → AP2112K. Reverted: C21 nudge, +BATT trunk widen (each was a clean round-trip / hygiene undo).

**DRC 200 → 190** (167→155 err, 33→35 warn, 19→16 unconn), **parity clean**. Honest accounting: the orphan cleanup removed ~12 errors; my GND via and (reverted) trunk-widen each *added* a clearance violation because I placed them blind (B3). I did **not** over-fix (per brief §0) — the courtyard overlaps, the +BATT/GND shorts, the drill rule, and the J7 shield remain for a human or a sighted pass.

---

## 8. Ceilings (KiCad, not kcd — document & route around)

- **No headless forward annotation (F8).** `sync --check` is honest about it; orphan removal still required the new `edit_delete_fp` rather than a schematic delete + push.
- **Dual-editor IPC segfault (KiCad 10.0.2).** The PCB-editor-only requirement is now baked into the mutating-tool docstrings — good. Worth a top-level note in the skill so an agent sets up the session correctly *before* the first mutate.
- **No via geometry edit in kipy** (only add/delete) — so `drill_out_of_range` can't be fixed by resizing vias; this is partly kcd scope (a delete-and-re-add `edit_via_modify` could wrap it).

---

## 9. Priorities for the next rework

1. **B1** `edit_move_fp` rotation `ImportError` — small, isolated, blocks all rotate-moves. Quick win.
2. **B2 + B4** — fold/spill the `analyze_*` and `snapshot_diff` MCP wrappers like `drc`/`erc`. Without this, the analyzers and diffs are unusable inline; this is the single biggest hit to MCP-driven usability.
3. **B3** — return render bytes inline (or an artifact-fetch path). This is what actually unblocks "render-first" for an agent, and would have prevented the two blind-placement clearance errors in §7.
4. **B5/B6** — kill confident scores from empty/partial evaluation (`routing 80/80`, `thermal 100`). False green is worse than honest grey.
5. **B7/B8** — `MP` alias + part-identity coherence check; both are also down-payments on the parts-knowledge-layer work.

---

*Run fresh next round: render-first only becomes a real reflex once B3 lands. Until then, lead with `parity` → `net_pcb`/`net_of` → `analyze_pcb` (read the spilled file) → `drc`, and treat every blind geometry edit as suspect. The board is a means; the deliverable is this report.*
