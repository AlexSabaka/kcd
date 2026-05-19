# Cheetah-to-Dove closeout: session-4 findings

**From:** Cheetah 🐆 (session 4 close)
**To:** Dove 🕊️ (session 5 prep)
**Date:** 2026-05-19
**Branch:** `main`, 4 atomic phase commits + this report

## TL;DR

All three new session-4 findings closed, plus the kicad-cli `--pages` upstream
bug draft (#24) ready for Sabaka to file when convenient. The defensive warning
on `kicad_reverted: false` (#21) now fires on the IPC-unavailable branch — the
silent-corruption hazard scenario you flagged is no longer reachable by an
agent that ignores `data`. `kcd parity` (#22) is live as a top-level command;
five drift scenarios all green against monkeypatched PCB data. The error-code
classification fix (#23) turned out to be cleaner than you outlined — one
exception subclass and the existing `LookupError` handler does the rest.

**63 passed, 1 skipped** (the gated agentic-loop integration test). Clean
working tree.

## Closed findings

| # | Finding | What landed | Commit |
|---|---|---|---|
| 21 | `kicad_reverted: false` silent on `IpcUnavailable` | `r.warn(...)` added in the IpcUnavailable branch of `snapshot.restore` with a hazard message matching the move-fp tone ("Reload the .kicad_pcb in KiCad before continuing"). Generic-exception branch already warned; left alone. Existing test renamed `_is_silent` → `_warns`. | `d8bae96` |
| 22 | No whole-board parity command | New top-level `kcd parity <proj> --json` registered flat alongside `drc`/`erc`. Reports `schematic_only`, `pcb_only`, `value_mismatches`, `footprint_mismatches`. Mirrors `pcb_only`/`schematic_only` counts into envelope `warnings`. IPC degradation: no KiCad open → schematic-only listing with a warning, not a failure. 5 CliRunner tests cover clean alignment, both-side drift, value mismatch, footprint mismatch, and IPC-unavailable. | `767598e` |
| 23 | `edit *` not-found classified as `edit_failed` instead of `not_found` | New `SymbolNotFound(LookupError)` class in `skip_sch.py` used at the two not-found-by-design sites (`find_symbol`, `locate`). The existing `LookupError → not_found` handler in `core/output.py` catches it automatically. `SchEditError` stays for real edit failures; `SymbolNotFound` is a peer, not a child, so no catch site loses coverage. | `60d5242` |
| 24 | kicad-cli `--pages` SVG upstream bug undocumented | `docs/upstream/kicad-cli-pages-svg-bug.md` (NEW). Includes reproducer (uses KiCad's bundled `complex_hierarchy` demo — no project setup needed), expected vs observed behavior, why-it-matters paragraph citing kcd's mtime-based workaround, and triage suggestion. Ready to paste to GitLab. | `508afd9` |

## Validation

- `pytest -v`: **63 passed, 1 skipped** (`test_agentic_loop` — by design, env-gated)
- **+9 new tests** this round: 5 for π (parity drift flavors + IPC degrade), 3 for ο (CliRunner across edit prop / edit value / inspect ref), 1 update for ξ (test rename + new assertion). 1 extension to `test_locate.py::test_locate_raises_for_missing_symbol` asserting the exception is a `LookupError` and not a `SchEditError`.
- All four phases atomic with `Co-Authored-By: Claude Opus 4.7 (1M context)`
- No lints, no hook bypass, no scope creep

## Surprises / decisions worth your input

1. **Your framing of #23 missed an interesting detail.** You observed `edit_value`
   returning `not_found` and `edit_prop` returning `edit_failed`. That was true at
   session 3, but Phase ν (hierarchical sheet lookup, session 3) routed *all* five
   schematic edit commands through `locate()`, which raises `SchEditError` for
   not-found — so by session 4, **both** commands were returning `edit_failed`
   uniformly. The fix is still right (`not_found` is the honest code), but it
   addresses a slightly different (consistent-but-wrong) symptom than the
   inconsistency you described.

2. **`SymbolNotFound` is a peer of `SchEditError`, not a subclass.** Two reasons:
   the catch order in `run_command` is `SchEditError → edit_failed` *before*
   `LookupError → not_found`, so a `SymbolNotFound` that multi-inherited from
   both would still be misclassified. And semantically: "the symbol doesn't
   exist" isn't a *kind of* edit failure — they're different categories. Letting
   `LookupError` claim it cleanly mirrors how `FileNotFoundError` flows.

3. **`kcd parity` is a flat top-level command, not a Typer sub-app.** With one
   operation and no foreseeable subcommands, the flat shape (mirroring
   `drc`/`erc`) is cleaner. If we ever add `kcd parity drc` / `kcd parity bom` /
   etc., switching to a sub-app is a one-line change at registration.

4. **PCB-only counts as a BOM hazard; schematic-only is mid-design.** Both get
   warnings, but I phrased PCB-only as "BOM hazard" and schematic-only as "not
   placed on the PCB" — the former is a fab-and-source danger, the latter is
   usually just a layout in progress. Tell me if that framing matches what your
   review-skill consumers expect; happy to flip it.

## Re-test cards (in priority order)

1. **#21 — silent restore on offline KiCad:**
   ```
   # KiCad not running
   kcd snapshot restore <proj> <ref> --yes --json
   # expect: warnings[] contains "not synced" + "Reload the .kicad_pcb"
   # expect: data.kicad_reverted == false
   ```
   Was: silent. Now: warning is mandatory on the offline path. Use this as the
   gate before any subsequent `move-fp` in a script.

2. **#22 — parity against `pic_programmer`:**
   ```
   # KiCad open with pic_programmer.kicad_pcb
   kcd parity pic_programmer --json
   # expect: data.pcb_available: true
   # expect: data.pcb_only contains C6, C7 (the legacy decoupling caps you flagged)
   # expect: warnings[] contains "BOM hazard" and "no schematic backing"
   ```
   With KiCad closed:
   ```
   kcd parity pic_programmer --json
   # expect: data.pcb_available: false
   # expect: data.schematic_only populated from sch alone
   # expect: warnings[] contains "KiCad not running"
   ```

3. **#23 — `not_found` classification:**
   ```
   kcd edit prop pic_programmer --ref DOES_NOT_EXIST --field X --value Y --json
   # expect: ok: false, error.code: "not_found" (was "edit_failed")
   kcd inspect ref pic_programmer DOES_NOT_EXIST --json
   # expect: same classification
   ```

4. **#24 — read the bug-report draft:**
   `docs/upstream/kicad-cli-pages-svg-bug.md`. If you'd refine the body or want
   to switch out the demo project, say so before Sabaka files it.

## Answers to your session-4 questions / wish-list

- **Flat `inspect sch` shape: kept.** You called it; I didn't touch it. The
  per-symbol `sheet` tag is the right shape for `groupby` consumers.
- **Mutator API: kept on `(sch_path, ...)`.** Your reasoning is the load-bearing
  argument — debuggability + single-purpose primitives. The `locate()` wrapper
  is paid once at the command layer, not five times in mutators.
- **kicad-cli upstream filing: drafted, not filed.** Reasoning: I have no
  GitLab account attached. Sabaka pastes when convenient; the draft is
  copy-and-go.
- **Validation against `complex_hierarchy` for #20: still owed.** I didn't
  switch the active project in this session — that's a hardware switch (need
  to close pic_programmer, open complex_hierarchy in KiCad). Carried for
  session 5.

## What I'd want from session 5

- **Run #22's re-test card against `pic_programmer` as-loaded** — your
  prediction that C6, C7 will appear in `data.pcb_only` is the cleanest end-to-end
  validation. If they don't, that's a parity-side bug; if they do, that's the
  "EE review skill" foundation landing as designed.
- **Validate #20 against `complex_hierarchy`** — your fixture suggestion is
  unchanged from session 4; I just couldn't run it from here without
  taking your KiCad seat. The test path you wrote (steps 1–6 in the
  session-4 report) is ready to go.
- **Read the kicad-cli `--pages` draft** and tell me if it should be tighter
  before filing. Specifically: do you want the "Suspected location" link?
  I left it as a hint but it might attract noise during triage.
- **Edge case: parity on a project where KiCad is open with a *different*
  board** — currently `kipy_pcb.list_footprints()` returns whatever's open,
  which means a parity check against the wrong PCB. We probably want a
  consistency check at the parity layer that the open board's path matches
  the requested project; flag it if it bites you.

## Still open (carried)

| Item | Status |
|---|---|
| `complex_hierarchy` validation of #20 | Carried (needs your KiCad seat) |
| File kipy `Board.is_dirty()` upstream request | Carried |
| `library_id` on fresh KiCad-10-native project | Carried |
| FreeRouting end-to-end | Carried |
| `edit move-fp --rotation` E2E test | Carried |
| KiCad upstream segfault filing | Carried |
| README ↔ CLI drift cleanup (now needs `kcd parity`) | Carried, small |

🐆

---

*Generated alongside commits `d8bae96 → 508afd9` on `main`. Dove's session-4
report at `docs/Dove-to-Cheetah-Standup-Report-post-η-ν.md`.*
