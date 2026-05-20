# Cheetah → Dove: kcd Round-5 Rework Handout

**For:** Dove 🕊️ (R6 field-test session, if there is one)
**From:** Cheetah 🐆 (R5 rework)
**Date:** 2026-05-20
**Branch:** `main` — 6 commits (`65c38c5` … `4e84d68`)
**Source:** `docs/Dove-to-Cheetah-Field-Report-Round5.md`

---

## 0. Verdict in one paragraph

All seven R5 findings are addressed — **R5-1..R5-7 plus B2**, the full round
Sabaka scoped. No vendored `analyzers/` patches were needed this time; every
fix lives in kcd's own code. The headline closures: `export gerber` now ships
a complete fab package (drills included), the analyzer fold is finally tight
enough to be readable inline, the PCB render is cropped to the board, and
`render pcb` gains a region/zoom so vision works for fine placement — not just
the forest. Two paths I **could not verify** from the rework env (no live
KiCad): the R5-2 region crop's viewBox calibration against a real board, and
the R5-7 `edit pcb-text` IPC path. Both are unit-tested; §4 is the must-test.

---

## 1. What's fixed — verify these

| # | Fix | How to verify |
|---|-----|---------------|
| R5-4 | `export gerber` ships drills too | `export gerber --out ./fab` — `./fab` holds both `.gbr` and `.drl`; `data.drill_included: true` |
| B2 | `analyze *` inline envelope is genuinely small | `analyze pcb` — compacted `data` well under 50 KB; more sections in `spilled.sections`; spilled lists carry a `sample` |
| R5-3 | `analyze pcb` connectivity reconciled vs DRC | On the board with 16 DRC unconnected — `connectivity.routing_complete: false` + `drc_unconnected: N` + a warning |
| R5-6 | `analyze cross` flags an empty assessment | `analyze cross` with 0 findings — `summary.assessment_status: "insufficient_data"` + a warning |
| R5-5 | `analyze diff` no longer crashes on gerber JSONs | `analyze diff <gerber.json> <gerber.json>` — clean `error.code: "unsupported_diff"`, exit 1, no traceback |
| R5-1 | PCB render cropped to the board | `render pcb --format png` — board fills the frame, no A4 worksheet border |
| R5-2 | `render pcb` region/zoom | `render pcb --region-ref <REF>` — PNG shows the area around that footprint (§4) |
| R5-7 | `edit pcb-text add\|set` | `edit pcb-text add --text REV-A --at X,Y` then `render pcb`; `edit pcb-text set --match REV-A --to REV-B` (§4) |

---

## 2. Output-shape / behaviour changes — READ BEFORE TESTING

These are intentional. kcd is pre-release 0.1.0; reshaped envelopes and new
files are not regressions.

- **`export gerber` writes drill files into the same directory.** A `.drl`
  appearing alongside the gerbers is the fix, not a stray file. `data` gains
  `drill_included: true`. The standalone `export drill` still exists for
  drill-only exports.
- **`analyze *` budgets retuned.** `_TOTAL_BUDGET` 96 KB → 40 KB,
  `_VALUE_BUDGET` 24 KB → 8 KB. Expect `spilled.sections` to name *more*
  sections than in R4 (`decoupling_proximity`, `net_lengths`,
  `audience_summary`, …) — that's the point. A spilled **list** now carries
  `{count, sample}` (first 3 entries, when under 2 KB) instead of a bare
  `{count}`. The full report is still only in the artifact.
- **`analyze pcb` runs DRC.** To reconcile `connectivity.routing_complete`
  (R5-3) it runs a DRC pass when routing reads complete. `analyze pcb` is
  therefore slower than before by one DRC run — confirm it's tolerable on a
  real board. `connectivity` gains `drc_unconnected` when gaps exist.
- **`analyze cross`** — `summary` gains `assessment_status` (new field,
  mirrors `thermal_score_status`); set to `"insufficient_data"` when the run
  surfaced 0 findings.
- **`analyze diff`** — guards the input `analyzer_type` before the vendored
  differ; gerber / cross / mismatched-type inputs return a clean
  `unsupported_diff` error instead of a `KeyError` traceback. pcb/sch/emc/
  spice diffs are unaffected.
- **`render pcb` SVG/PNG are board-cropped.** `export_pcb_svg` now passes
  `--page-size-mode 2 --exclude-drawing-sheet`, so the board fills the
  render. `export pdf --target pcb` is untouched and keeps the framed sheet.
- **`render pcb` region flags.** `--region-ref REF` (centres a
  `--region-window` mm square, default 20, on a footprint), `--region-bbox
  x1,y1,x2,y2` (explicit mm window). svg/png only — `--region-* + --format
  pdf` is a `bad_region` error. PNG rasterization dpi auto-scales up for a
  cropped region so zooming in keeps full-board pixel detail. `data` gains
  `region_mm`.
- **New `edit pcb-text add|set`** (+ MCP tools `kcd_edit_pcb_text_add` /
  `kcd_edit_pcb_text_set`). PCB-only, needs KiCad open, calls `board.save()`
  — same caveat as `move-fp` / `via add`.

---

## 3. Notes on R5 findings not converted to code

- **R5-3 has a sibling that is *not* fixed:** the `analyze pcb` reconciliation
  fixes the `connectivity` block. If you still see a stale verdict elsewhere
  in `analyze pcb` output, flag it — I only touched `connectivity`.
- **R5-5 is guard-only.** A real gerber-to-gerber `diff_gerber` handler was
  out of scope; `analyze diff` on two gerber JSONs reports "unsupported", it
  does not diff them. If gerber diffing is wanted, that's an R6 ask.
- **The drill-rule contradiction** you noted (net-class 0.2 mm via drill vs
  `min_through_hole_diameter` 0.3 mm) is a board-data issue, not a kcd bug —
  left for the design, not the tool.

---

## 4. What I could NOT verify — please exercise

No live KiCad in the rework env, so these are unit-tested but not run
end-to-end:

- **R5-2 region crop calibration.** The fraction→viewBox math is unit-tested,
  but it assumes the `--page-size-mode 2` SVG content spans the board-outline
  bbox *exactly*. If KiCad adds a small page margin, a `--region-ref` crop
  will be slightly offset. Render `--region-ref` for a known footprint and
  check the part is centred. If it's consistently offset, that's the margin —
  report the magnitude and I'll add an offset term.
- **R5-2 IPC reads.** `kipy_pcb.board_bbox` (merges Edge.Cuts shape boxes via
  `get_item_bounding_box`) and the `find_footprint` ref lookup — both need a
  live board; confirm `board_bbox` returns sane mm extents.
- **R5-7 `edit pcb-text`.** `add_pcb_text` / `set_pcb_text` use kipy 0.7.1
  `BoardText` — verified against the API stubs, not a live board. Confirm
  `add` actually places visible silk and `set` matches/updates an existing
  item (it refuses an ambiguous multi-match).
- **R5-1 visual.** Confirm the cropped PCB PNG is genuinely board-tight with
  no leftover worksheet border.

---

## 5. Suggested R6 focus (if there is one)

1. The §4 unverified paths — R5-2 calibration is the one with real risk.
2. The §2 behaviour changes — confirm each reads cleanly to a fresh agent,
   especially the extra DRC pass inside `analyze pcb`.
3. The R5 untested list carries forward: `analyze lifecycle`, `edit symbol`
   (the real U1 SOT-223 fix), the schematic-edit family (still F8/dual-editor
   stranded), `route freeroute`, `export step/pdf/pos`.

*Tests green here: full suite passes (3 integration-gated skips), MCP parity
guard green, ruff clean on changed lines. The board is a means; the
deliverable is the report.*
