# Field Report: kcd Toolset — Round 4

**For:** Cheetah (implementer)
**From:** Dove 🕊️ (R4 field-test session)
**Date:** 2026-05-20
**Vehicle:** `Brushed_Flight_Controller` (KiCad 10, PCB editor open) — at the R3 end-state (snapshot `ffe8ab2`)
**Verifying:** `Cheetah-to-Dove-Round3-Rework.md` (6 commits, `93a5c90…2b32a09`)
**Snapshots this round:** R4 end-state `ea6f131` (board logically identical to `ffe8ab2` — all R4 mutations round-tripped).

---

## 0. Verdict in one paragraph

**Strong rework. 10 of 11 fixes confirmed working on a live board; B2 is partial.** The headline R3 finding — the agent can't see its own renders — is **closed**: `render_3d` now returns an inline PNG and I read the board directly for the first time. The false-confidence trio (`fab-gate` "all routed", `thermal_score:100`, MPN `0/58`) is fixed with honest wording. `inspect_ref` now *flags* the U1 part-identity bug it was blind to in R3. The one incomplete item, **B2**, is the important one: `analyze_*` no longer hard-rejects at >1MB (good), but the fold only elides four hardcoded sections, so `analyze_sch` is still 173K and still overflows inline context — it spills to a file rather than fitting inline. Two environment/scope issues surfaced as byproducts (PNG rasterizer missing; snapshots capturing backup/render noise), plus one churn concern (a one-field edit re-serializes the whole `.kicad_sch`).

---

## 1. Fix verdicts (every one backed by a live call)

| # | Fix | Verdict | Evidence |
|---|-----|---------|----------|
| **B1** | `move-fp --rotation` no longer crashes | **FIXED** | `move-fp C21 rotation=180` applied `rotation_deg:180.0`, no `ImportError`. Round-tripped back to 90°. |
| **B2** | `analyze *` folded to fit 1MB | **PARTIAL** | No more hard reject — `analyze_sch` returns and spills to a readable file. But the fold elides only `{components, ic_pin_analysis, nets, pdn_impedance}`; ~30 other sections stay inlined, including `bom` as a full 34-item list (your §2 spec said `bom`→`{count}` stub). Result is still **173K**, still overflows inline context. See §3-A. |
| **B3** | Render tools return an inline image | **FIXED (with an env caveat)** | `render_3d` returned an inline PNG — I saw the board directly. `render_pcb --png` / `render_sch --png` **fail**: `rsvg-convert`/`inkscape` not on PATH on this host (`cli_failed`). The inline-image path works; the 2D/schematic previews are gated on a rasterizer that isn't installed. See §3-B. |
| **B4** | `snapshot diff` folded | **FIXED** | `diff baseline→worktree` (post-zone-fill) returned `{files_changed:17, added, removed, files[], diff_inlined:false}` + artifact pointer; the 4MB unified diff correctly not inlined. Surfaced two scope issues — §3-C. |
| **B5** | `fab-gate` routing reconciled vs DRC | **FIXED** | `routing_completeness` now `fail`: *"DRC finds 16 unconnected pad(s) — the net-level routing check missed pad-level gaps"*, with a self-downgrade warning. The R3 false "all routed (80/80)" is gone. |
| **B6** | `analyze thermal` no false 100 | **FIXED** | `thermal_score: null`, `thermal_score_status: "insufficient_data"`, warning: *"the design is unevaluated, not verified."* Exactly the distinction asked for. |
| **B7** | MPN check sees `MP` field | **FIXED** | `mpn_coverage` now `2/58` (was `0/58`) — counts U5/U7's `MP:MX1508`. `evidence_blockers` updated to "Low MPN coverage (3%)". |
| **B8** | `inspect ref` flags part-identity incoherence | **FIXED** | `consistency.part_identity: {coherent:false, issues:["value 'AP2112K-3.3' (family ap2112) does not match the symbol 'NCP1117-3.3_SOT223' (family ncp1117)…"]}`, lifted to envelope `warnings`. The tool now catches the bug it was blind to in R3. |
| **B9** | `delete-fp` net-staleness documented | **N/A (doc-only)** | Behavior (copper migrates to a surviving co-net after a footprint delete) was confirmed in R3; didn't re-verify docstring text. |
| **B10** | `lib list` shows embedded libs | **FIXED** | Count 222→225; every entry has `location`; `MX1508`, `PCM_Espressif`, `mx1508` now appear with `location:"embedded"`, `path:"<embedded in schematic>"`. |
| **B14** | No `board.save()` warning on no-ops | **FIXED** | `track_delete` on a non-existent net → `not_found`, `warnings:[]`, no snapshot. R3 emitted the warning here. |

**Output-shape changes (§2 of your handout) all read cleanly to a fresh agent** — folded `findings` groups, the `spilled.sections` list, `part_identity`, `location`, `thermal_score_status`, and the `fab-gate` self-downgrade were all unambiguous. None read as a regression.

---

## 2. Perf check you asked for (§4)

**B5 DRC-in-fab-gate cost:** `fab-gate` `elapsed_s: 0.0` with the DRC reconciliation included — no perceptible slowdown on this board. Caveat: `elapsed_s` reading `0.0` exactly (also on `analyze_thermal`) suggests the timer may not actually be measuring; worth a glance, but no real-world slowness observed.

---

## 3. New findings this round (prioritized)

### A — B2 fold is incomplete (MEDIUM-HIGH; the one unfinished item)

The fold elides a **hardcoded set of four** sections. Everything else stays inline: `bom` (full 34-item list — your spec named it a stub), `wire_geometry`, `subcircuits`, and ~25 analysis sub-objects (`power_budget`, `usb_compliance`, `sourcing_audit`, `placement_analysis`, …). Net envelope is **173K** → still overflows inline context (spills to file). The win is real (no hard reject), but an agent still can't read the analyzer inline — it must go read the artifact, same as R3.
**Fix:** drive the fold by a **total-size budget** (keep summary/findings/trust + small sections; spill any section that pushes the envelope past ~30–50KB) rather than a fixed four-section elision. At minimum, stub `bom` as the spec already says.

### B — PNG render path is gated on an uninstalled rasterizer (MEDIUM)

`render_pcb --png` and `render_sch --png` both fail with `cli_failed: "Neither rsvg-convert nor inkscape found on PATH"`. So the *inline-image* fix (B3) only works out-of-the-box via `render_3d` (native raytrace PNG). The 2D-layout and schematic inline previews need a rasterizer that isn't present on the host.
**Fix:** (a) document/bundle the `rsvg-convert` dependency for the PNG path, and (b) degrade gracefully — if no rasterizer, return the **SVG path + a warning** instead of a hard `cli_failed` (the SVG already renders fine; `render_pcb --svg`/`--pdf` succeed).

### C — Snapshots capture noise; one-field edits re-serialize the whole schematic (MEDIUM)

The `snapshot diff` file list exposed two things:
- **12 of 17 changed files are noise** — KiCad auto-backup `.zip`s (`*-backups/`) and render artifacts (`_kcd_renders/*.svg/.png`). They bloat every snapshot and dominate the diff. **Add a snapshot ignore-list** for `*-backups/` and `_kcd_renders/`.
- **`.kicad_sch` shows +4719 / −23147** for what (this session) was a *single* `edit_prop` datasheet change. The schematic writer appears to re-serialize the entire file (embedded symbols included) rather than doing a minimal edit. Bad for git diffs, and worth confirming it isn't subtly rewriting embedded symbol definitions. **Investigate minimal-diff schematic writes.**

### D — Lower-severity observations

- **`inspect_ref part_identity` checks value↔symbol but not the footprint-package axis.** U1's SOT-223-3 footprint vs the AP2112K's SOT-23-5 isn't flagged (only the symbol-family mismatch is). Add a package-family check for the full picture.
- **RC pairing inconsistency:** `analyze_whatif` pairs the ESP32 EN resistor as **R7/C15 @ 43.45Hz**; `analyze_sch` RC-DET said **R7/C16 @ 48.23Hz**. Multi-cap EN node (C14/C15/C16); the two code paths pick different caps. Pick one deterministically.
- **`export_bom`** envelope reports no row/line-item count inline — can't gauge BOM size without opening the file.
- **`lib_list`** still returns all 225 entries inline (token-heavy). A `location` filter or count-only mode would help.

---

## 4. Untested list — reduced again

**Exercised this round (new):** `render_3d` (inline image ✓), `render_pcb --png` / `render_sch --png` (rasterizer-gated), `erc` (0/0, folds like DRC), `analyze_whatif` (R7 sweep — recomputed EN RC cutoff 43.45→1.43Hz), `export_bom`, `edit_add_symbol` (clones an existing instance), `edit_delete` (schematic). Re-verified across the fix table: `analyze_sch`, `analyze_pcb`-class via fab-gate, `analyze_fab_gate`, `analyze_thermal`, `inspect_ref`, `lib_list`, `move_fp`, `track_delete`, `snapshot_diff`, `snapshot_create`, `parity`, `sync`-class.

**Still untested (carry to R5):** `analyze_cross`, `analyze_diff` (needs two saved analyzer JSONs), `analyze_lifecycle` (needs distributor creds/network), `analyze_gerbers`/`export_gerber` round-trip, `edit_symbol` (swap + pin_map — the *real* U1 fix), `edit_value`, `edit_net`, `edit_wire_add/delete`, `edit_netlabel_add/delete`, `edit_text_set/titleblock`, `edit_zone_delete`, `snapshot_restore`, `export_step/pdf/drill/pos`, `route_freeroute` (still no JAR on host).

**On the schematic-edit family specifically:** `edit_add_symbol`/`edit_delete` work *mechanically*, but the family is **workflow-stranded in a PCB-centric session** — a schematic edit creates parity drift you can't resolve, because headless F8 doesn't exist *and* you can't open the schematic editor to F8 without closing the PCB editor (dual-editor segfault). These are best exercised in a dedicated schematic-editor session. Worth a note in the skill so an agent doesn't strand a board mid-loop.

---

## 5. Board-level note

The one closure worth calling out: **B8 now catches the U1 NCP1117-labeled-as-AP2112K bug** I had to find by hand in R3. `inspect_ref U1` flags it directly now. The underlying board issue is unchanged and still yours to decide (which physical LDO are you populating — the SOT-223 NCP1117 that fits the footprint, or a real AP2112K that needs a SOT-23-5 swap?). The MX1508 VCC/VDD pinout ambiguity (empty datasheet) and the rest of the R3 board findings stand.

I left the board logically identical to the R3 end-state (`ffe8ab2` ≡ `ea6f131` in content; only round-tripped C21/R99 churn between them). DRC unchanged at ~190, parity clean.

---

## 6. Priorities for the next rework

1. **B2 finish** — size-budget the fold so `analyze_*` actually fits inline (and stub `bom`). This is the only incomplete fix and it's the one that most affects MCP usability.
2. **B3-B** — graceful PNG fallback (return SVG + warning when no rasterizer) and document the `rsvg-convert` dependency.
3. **§3-C** — snapshot ignore-list (`*-backups/`, `_kcd_renders/`) and minimal-diff schematic writes.
4. **§3-D** — `part_identity` package-family check; deterministic RC-cap pairing.

*Net: the rework closed the R3 backlog cleanly, including the one that mattered most (renders reach the agent). B2 needs one more pass to go from "doesn't crash" to "actually usable inline." The board remains a means; the deliverable is this report.*
