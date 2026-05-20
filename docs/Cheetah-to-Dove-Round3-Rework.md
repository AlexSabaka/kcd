# Cheetah → Dove: kcd Round-3 Rework Handout

**For:** Dove 🕊️ (R4 field-test session)
**From:** Cheetah 🐆 (R3 rework)
**Date:** 2026-05-20
**Branch:** `main` — 6 commits (`93a5c90` … `2b32a09`)
**Source:** `docs/Dove-to-Cheetah-Field-Report-Round3.md` (R3 verdict layer)

---

## 0. Verdict in one paragraph

All 14 R3 items are addressed: **11 fixed** (B1–B10, B14), **3 documented as
known limitations** (B11/B12 vendored-engine internals, B13 not-a-bug). The
big theme of R3 — MCP-output overflow — is closed: `analyze *`, `snapshot
diff`, and the render tools no longer dump unbounded payloads. Several
**output shapes changed** as a result; §2 is the must-read before you test,
so a reshaped envelope doesn't read as a regression. One thing I could not
verify from here (no live KiCad in the rework env): the **render→image
round-trip over MCP** — please exercise it deliberately (§4).

---

## 1. What's fixed — verify these

| # | Fix | How to verify |
|---|-----|---------------|
| B1 | `edit move-fp --rotation` no longer crashes (`Angle` import repointed to `kipy.geometry`) | `move-fp --ref C21 --x .. --y .. --rotation 90` — should round-trip, not `ImportError` |
| B2 | `analyze *` folded to fit the 1MB cap | `analyze sch` on the 58-component board — returns, no "too large" rejection; see §2 |
| B3 | Render tools return an inline image | `kcd_render_3d` / `render_pcb` / `render_sch` over MCP — an image should appear in-context (§4) |
| B4 | `snapshot diff` folded to fit the cap | `snapshot diff baseline→worktree` after a zone fill — returns a summary, not a hard reject |
| B5 | `fab-gate` routing reconciled against DRC | On a board with DRC unconnected pads — `routing_completeness` should now be `fail`, not `pass` |
| B6 | `analyze thermal` no false 100 | A board it can't classify — `thermal_score: null`, `thermal_score_status: "insufficient_data"` |
| B7 | MPN check sees the `MP` field | A board with `MP`-field parts (U5/U7 MX1508) — `mpn_coverage` should count them, not 0/N |
| B8 | `inspect ref` flags part-identity incoherence | `inspect ref U1` — `data.consistency.part_identity` should flag AP2112K-vs-NCP1117 |
| B9 | `delete-fp` net-staleness documented | Docstring only — re-query `net pcb` after a footprint delete |
| B10 | `lib list` shows embedded libs | `lib list --project` — embedded `mx1508:` should appear with `location: "embedded"` |
| B14 | No `board.save()` warning on no-ops | A `track delete`/`modify` that matches nothing — no `board.save()` warning emitted |

---

## 2. Output-shape changes — READ BEFORE TESTING

These are intentional. kcd is pre-release 0.1.0; reshaped envelopes are not
regressions.

- **`analyze *` `data` is folded.** `findings` is now a list of groups
  `{rule_id, severity, count, sample}` plus `finding_total`; bulk sections
  (`bom`, `nets`, `statistics`, graphs) are replaced by `{count}` stubs and
  named in `data.spilled.sections`. **The complete analyzer JSON is only in
  the artifact** — re-read the artifact path for full detail. There is **no
  `--full` flag** (inlining the whole report would just re-trip the 1MB cap).
- **`snapshot diff` `data` is folded.** Now `{ref_a, ref_b, files_changed,
  added, removed, files[]}`. A small diff body still rides inline as
  `data.diff`; a large one is omitted (`data.diff_inlined: false`) and the
  full unified diff is the `snapshot_diff` artifact.
- **Render MCP tools return an image.** `kcd_render_sch/pcb/3d` now return a
  PNG content block *alongside* the JSON envelope. An oversize preview is
  skipped with a warning (not a hard fail). `kcd render pcb` gained a `png`
  format (flat 2D layer view).
- **`fab-gate` can self-downgrade.** If DRC finds unconnected pads, the
  `routing_completeness` check flips `pass`→`fail` and `summary` /
  `overall_status` are recomputed. A DRC cross-check that errors degrades
  gracefully (warning, gate untouched).
- **`analyze thermal`** — `thermal_score` is `null` (not 100) when
  `components_assessed == 0`; read `thermal_score_status`.
- **`inspect ref`** — `data.consistency` gained a `part_identity` sub-block
  `{coherent, issues[]}`, always present.
- **`lib list`** — every entry gained a `location` field
  (`standard | project | embedded`).

---

## 3. Not fixed this round (by decision)

- **B11 / B12** — `analyze pcb` `provenance_coverage_pct` reading 0.0 and
  `statistics.track_count` null are internals of the **vendored** kicad-happy
  engine; out of scope for a kcd-layer fix. Logged in CHANGELOG.
- **B13** — net counts differing across `sync` / `analyze` / PCB are **three
  legitimate definitions** (netlist nets / S-expr nets / pad-touching nets),
  not a drift bug. Documented in `.claude/CLAUDE.md` and CHANGELOG.

---

## 4. What I could NOT verify — please exercise

- **B3 render→image round-trip over MCP.** The rework env has no live KiCad,
  so `_attach_image` is unit-tested but the end-to-end "agent actually sees
  the render" path is unverified. Please call `kcd_render_3d`, `render_pcb`,
  `render_sch` over MCP and confirm an image lands in context — and that an
  oversize render degrades to a warning rather than failing the call.
- **B5** routing reconciliation runs DRC inside `fab-gate` — confirm the
  added DRC pass doesn't materially slow the gate on a real board.

---

## 5. Suggested R4 focus

1. The §2 shape changes — confirm each reads cleanly to a fresh agent.
2. B3 image round-trip (§4) — the one genuinely unverified path.
3. Re-run a full agentic loop on `Brushed_Flight_Controller` and check that
   `analyze`/`snapshot diff`/render no longer blow the context budget.
4. The still-untested R3 list (schematic-edit family, `analyze cross/whatif/
   lifecycle/diff`, `erc`, `export_*`) carries forward.

*Tests green here: full suite passes (3 integration-gated skips), MCP
parity guard green. The board is a means; the deliverable is the report.*
