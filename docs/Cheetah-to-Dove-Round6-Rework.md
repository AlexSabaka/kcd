# Cheetah → Dove: kcd Round-6 Rework Handout

**For:** Dove 🕊️ (R7 field-test session, if there is one)
**From:** Cheetah 🐆 (R6 rework)
**Date:** 2026-05-21
**Branch:** `main` — 9 commits (`9cca9a5` … `a71e3ca`)
**Source:** `docs/Dove-to-Cheetah-Field-Report-Round6.md` + Sabaka's PNG-render note

---

## 0. Verdict in one paragraph

The full round Sabaka scoped is done — both R5 carryovers (B2 fold, the
R5-3 sibling), four of the six new findings (R6-1, R6-3, R6-4, R6-5),
the R6-6 doc alignment, and Sabaka's own catch: PCB renders coming back
as an opaque slab. The two **deferred** items are exactly the two that
were scoped out: `edit swap-fp` (R6-2) is blocked by a kipy 0.7.1 API gap
and `drc --since` has no snapshot-DRC infrastructure — both are R7 asks,
documented in §5, not coded. No vendored `analyzers/` patches. One path I
**could not verify** from the rework env (no live KiCad): the `--side
both` transparency composite — unit-tested, §4 is the must-test.

---

## 1. What's fixed — verify these

| # | Fix | How to verify |
|---|-----|---------------|
| C1 | `analyze pcb` inline envelope genuinely small | `analyze pcb` — `data` well under 40 KB; `spilled.sections` names `nets`, `layers`, `silkscreen`, `ground_domains`, `copper_presence`; `net_name_to_id` gone from `data` *and* the artifact |
| C2 | R5-3 sibling reconciled | On the board with 16 DRC unconnected — **both** `connectivity.routing_complete` and `statistics.routing_complete` read `false` |
| R6-1 | Symbol `extends` resolved | `lib show <Lib>:<AP2112K-variant>` returns real `pins` (was `[]`); `edit symbol` can now target a derived part |
| R6-3 | `edit net` drift no longer false-green | Rename a net that's still on the board — `pcb.stale: true` (it compared bare `ELRS_TX` to `/ELRS_TX` before) |
| R6-4 | `move-fp` refills zones | `edit move-fp` — `data.zones_refilled: true`; the moved pad re-bonds to the pour instead of stranding copper |
| R6-5 | `bad_pin_map` enumerates pins | `edit symbol --pin-map 1=99` on a real swap — the error lists the valid pins of both parts |
| R6-6 | `analyze cross` doc aligned | `SKILL.md` + the command docstring now explain the fast `insufficient_data` return (see §3) |
| PNG | `render pcb` no longer an opaque slab | `render pcb --format png` (default `--side top`) — F.Cu + silk readable, no solid B.Cu fill; `--side both` shows back copper faded |

---

## 2. Output-shape / behaviour changes — READ BEFORE TESTING

These are intentional. kcd is pre-release 0.1.0; reshaped envelopes are
not regressions.

- **`analyze *` spills more, including dicts.** The R5 fold only stubbed
  *list* sections. `_compact` now also stubs **dict** sections, and an
  always-spill set (`nets`, `net_name_to_id`, `layers`, `silkscreen`,
  `ground_domains`, `copper_presence`) spills regardless of size. A spilled
  dict carries `{count, sample}` where `sample` is its first 3 key/value
  pairs. This is global — `analyze gerbers`' small `layers` list now also
  shows as a `{count, sample}` stub. The artifact always holds the full
  data.
- **`analyze pcb` drops `net_name_to_id`.** It's the exact inverse of
  `nets` (id→name); the duplicate is gone from the artifact *and* the
  envelope. Invert `nets` if you need name→id.
- **`render pcb` default is now a top-side view.** `render pcb` with no
  flags renders `F.Cu, F.SilkS, Edge.Cuts` only — not both coppers.
  `--side bottom` renders the mirrored back set; `--side both` composites
  the two with the back faded; explicit `--layers` overrides `--side`
  entirely. This also changes `--format pdf` (default now top-side
  layers); `--side both --format pdf` is a `bad_side` error.
- **`render pcb` `data` gains `side`.** `"top"` / `"bottom"` / `"both"`,
  or `"custom"` when `--layers` was given.
- **`move-fp` runs a zone refill.** `edit move-fp` is now one
  `refill_zones()` slower and re-pours copper around the moved part —
  `data.zones_refilled: true`. The `board.save()` caveat is unchanged.

---

## 3. Notes on findings not converted to straight code

- **R6-6 is doc-only.** `analyze cross` *does* run both analyzers
  internally — the code was correct. The "fast-fails in 5 ms" you saw was
  most likely the legitimate fast return: 0 findings →
  `summary.assessment_status: insufficient_data` (the R5-6 guard), or a
  `not_found` if a file was missing. `SKILL.md` and the command docstring
  now document that fast-return path so a quick return reads as expected.
  **If you saw a genuine fast *crash*** (not `insufficient_data`, not
  `not_found`), that's a real bug — send the exact command + envelope and
  I'll chase it; I couldn't reproduce one from the rework env.
- **R6-3 is root-level only.** The `/`-prefix normalization fixes
  root-sheet nets. A sub-sheet-nested net (`/sheet/NET`) still won't match
  a bare schematic label — out of scope for this pass.
- **R6-4 refills zones; it does not clean up track stubs.** A moved pad
  re-bonds to the pour, but a track whose far end now dangles is still
  `route track` territory (your finding #4's "+3 dangling warnings").

---

## 4. What I could NOT verify — please exercise

No live KiCad in the rework env, so this is unit-tested but not run
end-to-end:

- **`render pcb --side both` transparency composite.** The composite
  logic (`_composite_layers`) is unit-tested with synthetic SVGs: it keeps
  the front SVG's root, inserts the back content first inside a
  `<g opacity=...>`, and both share the page-size-mode-2 viewBox so they
  overlay. **Risk:** if kicad-cli's `pcb export svg` emits an opaque
  full-canvas background rect, the front's background would hide the back
  group. I'm betting it doesn't (KiCad plot SVGs draw copper as filled
  paths over a transparent canvas — that's why the slab you saw was the
  B.Cu *pour*, not a background). If `--side both` shows only the front
  with no back ghost, that's the background — tell me and I'll add a
  background-strip step. `--side top` / `--side bottom` are robust
  regardless (they just exclude the opposite copper).
- **R6-1 on a real derived symbol.** `extends` resolution is unit-tested
  against a new AP2112K base+derived fixture pair; confirm `lib show` on
  an actual stock derived symbol (a real AP2112K variant) returns its
  pins, and that `edit symbol` can now complete a swap to one.
- **R6-3 / R6-4 IPC paths.** Both need a live board: confirm the
  `edit net` drift check reports `stale: true` against real `/`-prefixed
  PCB nets, and that `move-fp` actually re-pours the zone.

---

## 5. Deferred to R7 (scoped out by Sabaka, not coded)

- **R6-2 `edit swap-fp` — blocked by kipy 0.7.1.** kipy exposes no
  footprint-definition-swap API and no footprint-library load. The only
  path is delete-old + create-new with a manual pad→net remap, which
  strands copper and is fragile. This is the real U1 enabler — worth an
  R7 round once we decide whether the delete+recreate hack is acceptable
  or we wait for a kipy API.
- **`drc --since <snapshot>` delta mode.** No snapshot-DRC infrastructure
  exists. A clean implementation would DRC a temp git-worktree at the
  snapshot commit and diff the by-type counts — real work, deferred.
- **Your other token-savers:** the `region_window` scale hint *is* shipped
  (option help + MCP docstring + cheat sheet). `lib show` on a placed ref
  (resolved pins in `inspect ref`) was left for R7 — it's a small add-on
  now that `extends` resolves.

*Tests green here: full suite passes (3 integration-gated skips), MCP
parity guard green, ruff clean on changed lines (4 pre-existing items in
untouched lines left alone). The board is a means; the deliverable is the
report.*
