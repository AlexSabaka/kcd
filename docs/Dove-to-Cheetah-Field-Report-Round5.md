# Field Report: kcd Toolset — Round 5 (final)

**For:** Cheetah (implementer)
**From:** Dove 🕊️ (R5 field-test session)
**Date:** 2026-05-20
**Vehicle:** `Brushed_Flight_Controller` (KiCad 10, PCB editor open) — at the R4 end-state (`ea6f131` ≡ baseline `832da61`)
**Trigger:** "Cheetah fixed PNG renders" → full end-to-end re-test.
**Board state:** UNCHANGED this round. Zero mutations — renders/analysis/exports only. Still DRC ~190, parity clean.

---

## 0. Verdict in one paragraph

**The PNG render fix works — and for the first time the loop the whole arc was chasing actually closes: I can see the board.** `render_3d` (top + bottom) and `render_pcb --png` all returned inline images. Using them I confirmed visually + analytically that the R3 GND pour **actually filled** (82% coverage, real 1673mm² plane, not an empty outline). The export→DFM chain (`export_gerber` → `analyze_gerbers` → `export_drill` → re-analyze) works end-to-end and caught a genuine fab-blocker. But three things stand out: (1) `render_pcb --png` plots the board on a full **A4 frame** so it's tiny — and with no crop/zoom, vision is good for the *forest, not the trees*; (2) **B2 is still only partially folded** — `analyze_pcb` now squeaks back inline but is still enormous; (3) two new tool issues: `export_gerber` silently omits drill files, and `analyze_diff` crashes (`KeyError`) on gerber JSONs.

---

## 1. PNG render fix — VERIFIED, with caveats

| Render | Result |
|--------|--------|
| `render_3d` top / bottom | **Works** — inline PNG, tightly framed, readable. This is the workhorse: confirmed orphans gone, ESP32 antenna keepout clear, U1 visibly a 3-pin SOT-223 (not SOT-23-5). |
| `render_pcb --png` | **Works** (no more `rsvg` error — Cheetah's fix landed) **but plots on the full A4 worksheet frame**, so the ~48×45mm board occupies ~15% of the pixels and is essentially unreadable. The 300 DPI is spent on empty sheet. |
| `render_sch --png` | Not re-verified this round (shares the same rasterizer that `render_pcb --png` now uses successfully; near-certain fixed, but I didn't confirm — carry-forward). |

**Finding R5-1 (MEDIUM): `render_pcb --png` needs a board-bbox crop.** Plotting on A4 makes it useless for layout inspection. Add a "fit to Edge.Cuts + margin" crop (or drop the worksheet frame for PCB PNG). 

**Finding R5-2 (MEDIUM, the deepest one): no crop/zoom = vision is macro-only.** At 300 DPI across a 48mm board in a full-board view, a 0.5mm part is a few pixels and a 1mm nudge is sub-perceptible. So renders now answer *"is the orphan gone / antenna clear / did the pour fill"* (forest) but not *"did this cap move clear a 1mm courtyard overlap"* (trees). Fine-placement work is still effectively blind. A region/zoom parameter (render a bbox around a ref or coordinate window) would close this — and it's the thing that would finally make vision-driven `move_fp` safe. *This is why I did no placement surgery this round: I couldn't have verified it.*

---

## 2. What vision + analysis confirmed

**The R3 GND pour is real and filled.** `analyze_pcb` zones: `is_filled: true`, `filled_area_mm2: 1673.07`, `fill_ratio: 0.824`, `outline_area 2031mm²`, 4 stitching vias (`TS-DET`). The bottom 3D render looked ambiguous (poured copper under soldermask reads as uniform green), so the analyzer — not the render — is the right tool to confirm a fill. Worth noting for the skill: *to verify a pour, read `zones[].is_filled`/`fill_ratio`, don't eyeball a 3D render.*

---

## 3. B2 (analyze fold) — still partial

`analyze_pcb` returned **inline** this round (R3 it spilled to file — progress), but it's still huge: only `footprints` is stubbed via `spilled.sections`, while `decoupling_proximity` (60 entries), `net_lengths` (52), `layer_transitions`, `decoupling_placement`, and a full `audience_summary` are all still inlined. Same root cause as R4: the fold elides a **hardcoded section set** instead of enforcing a size budget. It's right at the edge of fitting. **Recommendation unchanged:** spill by total-size budget (keep summary/findings/trust + small sections; spill the rest until under ~30–50KB).

**Finding R5-3 (LOW): `analyze_pcb.connectivity.routing_complete: true` while DRC has 16 unconnected.** Cheetah's B5 reconciliation reached `fab-gate` but not `analyze_pcb`'s own `connectivity` block — it still reports the un-reconciled net-level view. Same false-"complete" shape, different surface.

**Insight (not a tool bug): the drill rule contradicts itself.** The Default net class makes 0.2mm via drills, but the board's `min_through_hole_diameter` is 0.3mm — so the board's own net class violates its own rule. That's the root of all 51 `drill_out_of_range`. Fix is to reconcile the two (net-class via drill → 0.3, or min-hole → 0.2 to match a JLCPCB-class fab).

---

## 4. Export → DFM chain — works end-to-end, caught a real blocker

Exercised a full fab-prep chain (all four tools previously untested):

`export_gerber` → `analyze_gerbers` → **GR-003 "No drill file in gerber set — Fab will reject"** → `export_drill` → re-`analyze_gerbers` → **clean (finding_total 0, 84 holes, complete:true)**.

This is the chain working as designed — the DFM gate correctly flags an incomplete fab package and clears once fixed. The drill classification is genuinely good (52 vias split 0.2/0.3mm, 32 component holes across 6 tool sizes, 2 NPTH).

**Finding R5-4 (MEDIUM-HIGH): `export_gerber` silently omits drill files.** A user/agent running `export_gerber` to "make the fab package" ships a set the fab rejects — and `export_gerber`'s output gives **no warning** that drills are separate. Either bundle drills into `export_gerber`, or have it emit a warning ("drill files not included — run `export_drill`"). The fact that `analyze_gerbers` catches it after the fact is good defense, but the export step shouldn't set the trap.

---

## 5. New tool findings this round

**Finding R5-5 (MEDIUM): `analyze_diff` crashes on gerber JSONs.** `analyze_diff base=<gerber.json> head=<gerber.json>` → `KeyError: 'gerber'` (uncaught, in `diff_analysis.py` `diff_funcs[base_type]`). The happy path is fine — verified `analyze_diff` on two `pcb` JSONs returns a clean `{total_changes:0, has_changes:false}`. So it supports pcb (and presumably sch) but **crashes ungracefully on unsupported analyzer types** instead of returning a clean "diff not supported for analyzer_type 'gerber'" error. Add the missing handlers or a graceful guard.

**Finding R5-6 (LOW): `analyze_cross` doesn't carry the B6 "insufficient_data" honesty.** It returned 0 findings in 5ms with `provenance_coverage_pct: null` — the same empty-assessment shape `analyze_thermal` now flags as `insufficient_data`. Without current/datasheet data it can't do connector-current-vs-trace checks, so "0 findings" may mean "couldn't assess," not "all clear." Apply the thermal-style status to `cross` (and audit the other analyzers for the same).

**Finding R5-7 (LOW): no PCB-silk text primitive.** The `revision_marking` / `board_name` silk findings (flagged by both `analyze_pcb` and `fab-gate`) can't be auto-fixed — `edit_text_set`/`edit_text_titleblock` operate on the **schematic** root sheet, not PCB silk. If closing those findings agentically is wanted, a `edit_pcb_text` primitive is the gap.

---

## 6. Untested list — what's left (carry to R6 if there is one)

`analyze_lifecycle` (needs DIGIKEY/MOUSER/LCSC creds — ties to the parts-knowledge-layer work), `edit_symbol` (swap + pin_map — the *real* U1 fix), `edit_net`, `edit_wire_add/delete`, `edit_netlabel_add/delete`, `edit_text_set/titleblock`, `edit_zone_delete`, `snapshot_restore`, `export_step/pdf/pos`, `route_freeroute` (still no JAR on host), and `render_sch --png` re-verify. The schematic-edit family remains workflow-stranded in PCB-only sessions (F8 ceiling + dual-editor segfault) — best in a dedicated schematic session.

---

## 7. The arc, R1 → R5 (since this is the final round)

- **R1/R2:** found 8 gaps, then 4 bugs; net inspection landed as the keystone.
- **R3:** all 4 R2 bugs fixed; `edit_delete_fp` closed the footprint-delete ceiling; the headline finding was *the agent can't see its own renders*, plus the analyzers blowing the MCP cap.
- **R4:** 10/11 R3 fixes verified; `render_3d` inline image proved the render round-trip; B2 left partial.
- **R5:** PNG renders work across the board; the export→DFM chain works end-to-end; B2 still partial; vision is real but macro-only without a crop.

**Where kcd stands as a harness:** it can now carry an agent from diagnosis → cleanup (delete orphans, add pour, edit props) → fab export → DFM gate, with honest provenance/trust throughout and a real visual channel. The remaining gaps to "agent goes diagnosis-to-fab unaided" are concrete and small: (a) finish the B2 size-budget fold; (b) a render bbox/zoom for fine work; (c) `export_gerber` drill bundling; (d) close the schematic-edit workflow (the F8/dual-editor ceiling is the real blocker, and it's KiCad's, not kcd's — may need a documented "schematic session" mode). The board-level U1 part-identity and MX1508 pinout questions remain yours/the parts-layer's.

---

## 8. Priorities for the next rework

1. **R5-4** `export_gerber` drill bundling/warning — silent incomplete fab package is the highest-impact correctness gap here.
2. **B2** finish — size-budget the fold so the analyzers are actually readable inline (still the top MCP-usability item, three rounds running).
3. **R5-1/R5-2** render bbox crop + zoom/region — turns vision from macro-only into usable for placement.
4. **R5-5** `analyze_diff` graceful unsupported-type handling (+ gerber handler if wanted).
5. **R5-6** `insufficient_data` honesty for `cross` and any other empty-assessment analyzers.

*Board left untouched at `832da61` (≡ R4 `ea6f131`): orphans gone, GND pour filled, parity clean, DRC ~190. No surgery this round — by choice, since fine placement can't yet be visually verified. The board was always the means; the deliverable is the report.*
