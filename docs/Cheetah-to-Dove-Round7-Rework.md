# Cheetah → Dove: kcd Round-7 Rework Handout

**For:** Dove 🕊️ (next field-test session, if there is one)
**From:** Cheetah 🐆 (R7 rework)
**Date:** 2026-05-21
**Branch:** `main` — 3 commits (`c19033a` … `e0be694`)
**Source:** the two items R6 deferred — `edit swap-fp` (R6-2) and the
DRC delta token-saver.

---

## 0. Verdict in one paragraph

Both deferred hard items are built. `drc --since` is the clean one — a
delta mode that diffs the live board's DRC against a snapshot and reports
only the by-type counts that changed. `edit swap-fp` is the hard one: kipy
0.7.1 genuinely cannot swap a footprint over IPC, so it is an **offline
`.kicad_pcb` S-expr edit** — the first time kcd rewrites a whole board
file through its own `sexp` engine. The plan's headline risk was whether
`sexp.dumps` round-trips a real board faithfully; that is now **verified
end-to-end** — a 100 KB KiCad board parsed→dumped→re-parsed with structural
equality, and `kicad-cli pcb drc` loaded both the round-tripped board and a
swapped-footprint board cleanly. No vendored `analyzers/` patches.

---

## 1. What's new — verify these

| # | Feature | How to verify |
|---|---------|---------------|
| `drc --since` | DRC delta vs a snapshot | `kcd drc <proj> --since <snapshot-ref>` — `data` carries `since`, `summary` (before/after/Δ) and `changed` (only the by-type counts that moved); the full `violations` fold is gone. Two artifacts: the live report and the snapshot's. |
| `edit swap-fp` | Offline PCB footprint swap | `kcd edit swap-fp <proj> --ref R5 --to-footprint Lib:Name` — the placed footprint's definition is replaced, pads keep their nets, position/uuid/properties preserved. `render pcb` to see it. |

---

## 2. Output-shape / behaviour notes — READ BEFORE TESTING

- **`drc --since` reshapes `data`.** A normal `drc` run carries the folded
  `violations` list. With `--since`, `data` is instead
  `{project, since, summary:{before,after,delta}, changed:[...]}` — the
  folded list is intentionally dropped (that *is* the token win). Plain
  `drc` (no `--since`) is byte-for-byte unchanged. `--since` accepts any
  snapshot ref `git rev-parse` understands (short SHA from `snapshot list`,
  `HEAD~1`, …); an unknown ref → a clean `not_found` error.
- **`edit swap-fp` is an *offline* edit** — unlike `move-fp` / `delete-fp`
  it does **not** use IPC and must run with KiCad **closed**. It refuses
  with `project_open_in_kicad` when KiCad has the project loaded (KiCad
  would overwrite the edit on its next save); `--force` overrides with a
  warning, same contract as `edit designrules`.
- **`edit swap-fp` scope is identical-pad-layout only.** The new footprint
  must declare the same pad-number set as the placed one — then each pad
  keeps its net by an identity remap. A differing pad set is a clean
  `pad_set_mismatch` error (it names both sets). No `--pad-map` — a
  genuinely different pinout is out of scope by design.
- **What a swap keeps vs. replaces.** Kept from the placed instance: the
  footprint `uuid`, `path` (the schematic link), position `at`, all
  `property` values (Reference / Value / Footprint — the last is updated to
  the new lib-id), and `attr` (so DNP / exclude-from-bom intent survives).
  Replaced from the new library footprint: all geometry (`fp_*`), the pads
  (geometry only — nets are re-grafted), the 3D `model`, `descr`/`tags`.
- **New config knob:** `KCD_FOOTPRINT_DIR` — KiCad's standard footprint
  directory, auto-detected like `KCD_SYMBOL_DIR`. `edit swap-fp` resolves
  the new footprint via the project `fp-lib-table` then this directory.

---

## 3. What I verified

- **`sexp` round-trip on a real board.** `Arduino_Mega.kicad_pcb` (101 KB,
  ~40 footprints): `parse → dumps → parse` is structurally equal, and
  `kicad-cli pcb drc` loads the dumped board and runs DRC normally. The
  "first whole-`.kicad_pcb` rewrite through `sexp`" risk is cleared.
- **Real-board swap.** Swapped J1's footprint on that board via
  `swap_footprint`; `kicad-cli pcb drc` then loaded the result and reported
  the identical DRC state (a swap to the same footprint is electrically a
  no-op — exactly right). All 8 pads remapped, position preserved.
- Full unit suite green (3 integration-gated skips); MCP parity green
  (`kcd_edit_swap_fp` registered, `kcd_drc` gained `since`); ruff clean on
  changed lines (3 pre-existing items in untouched `snapshot.py` /
  `edit.py` lines left alone per the project rule).

---

## 4. What I could NOT verify — please exercise

- **`edit swap-fp` end-to-end on a real multi-pad part swap.** The unit
  tests swap 0805↔0603 (2 pads) on a fixture; the real-board smoke swapped
  a footprint to *itself*. A genuine different-footprint, same-pin-count
  swap on a live project — e.g. the U1 SOT-223 case — is the real test.
  Confirm the board still routes and the swapped part's pads land on the
  right nets.
- **`drc --since` on a board with a real edit between snapshots.** The
  unit tests monkeypatch DRC. On a live board: snapshot, make an edit that
  changes DRC (move a part into a clearance violation), `drc --since` →
  confirm `changed` shows exactly that type with the right Δ.
- **Custom `.kicad_dru` rules.** `materialize` extracts `.kicad_pcb` +
  `.kicad_pro` + `.kicad_dru` at the snapshot, so custom-rule violations
  *should* diff correctly — but I had no board with a `.kicad_dru` to
  confirm. If a delta looks off on a board with custom rules, that's the
  place to look.

---

## 5. Notes

- **`edit swap-fp` does not touch the schematic.** It pushes a footprint
  change onto the board only. If the schematic symbol's Footprint field
  still names the old footprint, `kcd parity` / `sync` will flag drift —
  run `edit footprint` on the schematic side too, or expect the report.
- The R6 round's open items not in this round (`analyze pcb` stale-verdict
  siblings beyond `connectivity`/`statistics`, the schematic-edit F8
  family, `route freeroute`, `export step/pos`) are untouched — still
  fair game for a future round.

*Tests green here: full suite passes (3 integration-gated skips), MCP
parity guard green, ruff clean on changed lines. The board is a means; the
deliverable is the report.*
