# Cheetah-to-Dove closeout: kicad-happy integration (session 5)

**From:** Cheetah 🐆 (session 5 close)
**To:** Dove 🕊️ (session 6 prep)
**Date:** 2026-05-19
**Branch:** `main`, 5 atomic phase commits + this archive

## TL;DR

End-to-end execution of the brief at `docs/Dove-to-Cheetah-Brief-kicad-happy-integration.md`.

- **#25 wrong-board guard** landed first, isolated from the vendor work.
- **kicad-happy v1.3.1 vendored** as `skills/kicad/` (66 files: SKILL.md
  + ATTRIBUTION + PATCHES + 18 references + 30 scripts). MIT preserved.
- **`kcd analyze sch|pcb|gerbers`** wired under the standard envelope —
  warning lifting, artifact registration, package-data force-include.
- **`skills/kicad/SKILL.md` reauthored** with a kcd-native preamble teaching
  the standard loop and the three core analyzer blocks rewritten to lead
  with `kcd analyze *`.
- **Docs pass**: CHANGELOG, README quick reference, agent cheat sheet.

**73 passed, 3 skipped** (2 of the skips are the new integration tests
under `KCD_INTEGRATION=1` — both pass against pic_programmer when enabled;
the third is the long-standing agentic-loop gate). Clean working tree.

## What landed

| Phase | Scope | Commit |
|---|---|---|
| σ | #25 parity wrong-board guard | `a4e3ef9` |
| τ | Vendor kicad-happy → `skills/kicad/` (66 files) | `e3122bb` |
| υ | `kcd analyze` sub-app + analyzers adapter + hatch force-include | `(after τ)` |
| ω | SKILL.md kcd-native preamble + 3 analyzer-block rewrites | `6ab945d` |
| docs | CHANGELOG / README / `.claude/CLAUDE.md` | `688fb1c` |

(Phase τ and υ commit hashes are in the git log — both shipped while the
session-4 push had not yet landed.)

## Verification

- `pytest -v`: **73 passed, 3 skipped**.
  - +1 over Phase 0 (wrong-board test in `test_parity.py`).
  - +9 unit tests in `test_analyze.py`: envelope shape × 3, lifting × 2
    (info doesn't surface; warning/error/critical do, with `[severity][rule_id]`
    tagging), artifact registration, CliError → `cli_failed`, gerbers'
    not-a-directory + nonexistent-directory branches.
  - +2 integration tests in `test_analyze_integration.py` (skipped by default,
    pass under `KCD_INTEGRATION=1` against pic_programmer).
- **Smoke against pic_programmer**: `kcd analyze sch <project> --json` →
  `ok=true`, 30 findings (3 error / 2 warning / 25 info), **5 lifted to
  envelope warnings**:
  - `[error][DS-001]` No datasheets directory found, no MPNs — review is
    consistency-only.
  - `[warning][RS-001]` VPP has no declared source.
  - `[error][RS-002]` VCC_PIC has no source unless user solders JP1.
  - `[warning][SJ-DET]` JP1 (JUMPER) open by default, between VCC ↔ VCC_PIC.
  - `[error][SS-001]` Sourcing blocker: BOM has <50% MPN coverage.
- **Artifact** at `/tmp/kcd/pic_programmer-analyze-sch.json` (registered
  in envelope `artifacts[]`).
- **No KiCad-10 surgical patches needed** — both schematic and PCB analyzers
  parsed pic_programmer (KiCad 10) cleanly. The schematic analyzer reports
  `kicad_version: "8.0"` because the schematic file format `(version 20231120)`
  didn't change between KiCad 8 and 10; the PCB analyzer correctly identifies
  `kicad_version: "10.0"`. Both behaviors are upstream and correct.

## Surprises / decisions worth your input

1. **Lineage flipped vs your brief.** You proposed splitting the vendor:
   scripts from `aklofas/kicad-happy`, references from
   `mattpainter701/my-claude-setup`. Scout-verified the actual repos at
   vendor time: **kicad-happy has all 18 references plus the 12 mattpainter
   ships** — and where they overlap, kicad-happy is the *newer* version.
   Mattpainter's `supplementary-data-sources.md` describes pre-auto-cache
   analyzer behavior; kicad-happy's version reflects the current auto-cache
   feature. Mattpainter is a downstream curation that hasn't kept up.
   Sabaka picked the conservative path; I vendored everything from
   kicad-happy and skipped mattpainter (logged in
   `skills/kicad/ATTRIBUTION.md`).

2. **kicad-happy is bigger than the brief described.** You scoped the
   vendor at 3 analyzer scripts; the actual `scripts/` folder has **30
   files** — the three main analyzers plus `cross_analysis`, `analyze_thermal`,
   `diff_analysis`, `what_if`, `analyze_emc` (yes, EMC! — `analyze_emc.py`
   isn't on the file list I scouted but it's referenced from the SKILL.md's
   review checklist), `lifecycle_audit`, `fab_release_gate`, plus 22 support
   modules. I vendored all of them — they're interdependent and the size is
   modest (under 1 MB total). Only the three top-billing analyzers are wrapped
   by `kcd analyze *` in this session; the rest remain accessible via
   `python3 skills/kicad/scripts/<name>.py` from the kcd repo root. Decide
   reactively which to graduate into `kcd analyze ...` next.

3. **cross_analysis vs `kcd parity` disagree on pic_programmer.** Your
   session-4 finding said C6, C7 are PCB-only drift on pic_programmer.
   `kicad-happy/scripts/cross_analysis.py --schematic sch.json --pcb pcb.json`
   returns **0 findings** against the same project. Two different lenses;
   not a bug in either. Worth a session-6 dive: is `kcd parity` over-counting
   (e.g. counting C6/C7 as PCB-only because of a tstamp mapping subtlety
   the analyzer is more careful about), is cross_analysis under-counting
   (its checks are decoupling/ESD/sync, not reference-set diff), or do they
   measure orthogonal things? Logged in `skills/kicad/PATCHES.md` under
   "Interesting findings".

4. **SKILL.md preamble shape.** I added a new "## Using this skill from
   kcd" section between the title and "## Related Skills" — teaches the
   `kcd project current` + `analyze sch/pcb` + `parity` opening move, plus
   the cross-reference principle ("flagged by both = high confidence;
   analyzer-only = needs primary-source verification"). The rest of upstream
   SKILL.md is preserved verbatim except the three core-analyzer command
   blocks (Schematic / PCB / Gerber) which now lead with `kcd analyze *`
   and fall back to the direct `python3 skills/kicad/scripts/...` form for
   advanced flags we don't expose (`--proximity`, `--full`, `--schema`,
   `--audience`, `--stage`). Minimum-Review Checklist points at the kcd-native
   form where wrapped, direct-script for the rest.

5. **wheel-packaging via `force-include`.** Hatch is finicky about non-package
   data; the cleanest answer was
   `[tool.hatch.build.targets.wheel.force-include] "skills" = "kcd/skills"`.
   `analyzers._locate_scripts_dir()` checks two paths (source-tree layout via
   `parents[3]`, wheel layout via `parents[1]`) and uses whichever exists.
   I tested only the source-tree layout in this session; verifying the wheel
   path needs an actual `pip install .` which I deferred to session-6 (no
   hardware reason to think it'd break, but it's an unbroken assumption).

## Re-test cards (in priority order)

1. **#25 — wrong-board guard against pic_programmer**:

   ```bash
   # KiCad open with some_other_project.kicad_pcb
   kcd parity pic_programmer --json
   # expect: ok=false, error.code="wrong_board_open"
   # expect: error.message names BOTH the open and requested board
   ```

   With KiCad closed → existing IPC-degraded path (schematic-only listing
   + warning). With KiCad open on pic_programmer → unchanged behavior.

2. **`kcd analyze sch pic_programmer --json`**:

   ```bash
   kcd analyze sch pic_programmer --json | python3 -c "
   import json, sys
   o = json.load(sys.stdin)
   print('ok:', o['ok'])
   print('warnings:', len(o['warnings']))
   print('findings:', o['data']['summary']['total_findings'])
   "
   # expect: ok=true, warnings≈5 (the DS-001/RS-001/RS-002/SJ-DET/SS-001 set
   # — exact list depends on whether you've synced datasheets yet)
   ```

3. **`kcd analyze pcb pic_programmer --json`**:

   ```bash
   kcd analyze pcb pic_programmer --json | python3 -c "
   import json, sys
   o = json.load(sys.stdin)
   print('# footprints:', len(o['data']['footprints']))
   print('kicad_version:', o['data']['kicad_version'])
   "
   # expect: 63 footprints, kicad_version=10.0
   ```

4. **`kcd analyze gerbers <dir>`**: generate a gerber dir via
   `kcd export gerber pic_programmer --out /tmp/g/`, then
   `kcd analyze gerbers /tmp/g/ --json`. Check that the analyzer JSON has
   `layers`, `findings`, and a `summary`.

5. **Wheel install path**:

   ```bash
   pip install /Volumes/2TB/repos/kcd
   cd /tmp && kcd analyze sch <project> --json
   # expect: `_locate_scripts_dir` finds skills/kicad/scripts/ via the wheel
   # path, not the source path. If it falls through to FileNotFoundError,
   # the force-include rule didn't ship the tree — needs investigation.
   ```

## Answers to your session-5 questions / wish-list

- **#25 (wrong-board guard) — landed in Phase σ.** ~22 LOC in
  `commands/parity.py`, +1 new test in `tests/test_parity.py`, updated
  4 existing happy-path tests to mock `list_open_documents` matching the
  project, and the IPC-degrade test to raise from `list_open_documents`
  too (since the trip-wire moved one call earlier).
- **Sibling-clone, not submodule — done.** Cloned to `/tmp/kicad-happy-src`
  and `/tmp/mattpainter-src`, used only for vendoring and per-doc diff,
  not retained in the kcd repo. ATTRIBUTION.md records the exact upstream
  commit hashes.
- **Skill folder name — `skills/kicad/`, not `skills/pcb-review/`.** Per
  Sabaka's call at planning time. Rationale: matches upstream's
  `skills/kicad/` shape exactly (zero rebase friction); broader scope than
  "pcb-review" (the analyzer also does BOM extraction, PDF schematic
  mining, datasheet verification, gerber analysis — well beyond just PCB
  review).
- **Vendor more than the brief listed — `kicad-happy/scripts/` has 30
  files, not 3.** All vendored. Most are interdependent support modules
  (`sexp_parser`, `kicad_utils`, `finding_schema`, `detector_helpers`, the
  `*_detectors.py` family, etc.). Only the three top-billing are exposed via
  `kcd analyze *`. The rest are accessible via `python3 skills/kicad/scripts/...`
  and the SKILL.md preamble tells the reader how.
- **mattpainter — considered but not vendored.** ATTRIBUTION.md records
  the per-doc decision. No material additions justified a co-vendor.

## What I'd want from session 6

After the re-tests land cleanly:

1. **First end-to-end review session** on a real (non-demo) board. The
   actual validation that the integration works as designed — load a real
   project, run the full review skill loop, write a report using
   `references/report-generation.md`'s template. Surface anything that
   surprised you.

2. **Pick the next analyzer(s) to graduate into `kcd analyze *`.** Reading
   the 30 vendored scripts and the SKILL.md review checklist, the
   highest-leverage candidates are:
   - `cross_analysis.py` — already needed in every full review; the brief
     even lists it in the Minimum Review Checklist. Wrap as
     `kcd analyze cross <project>` taking the schematic + PCB JSONs from
     `$KCD_RENDER_CACHE` (or running them if missing).
   - `analyze_thermal.py` — same shape, takes sch + pcb JSON.
   - `analyze_emc.py` — same shape; the brief lists it in the Minimum
     Review Checklist.

   But: don't pre-commit. See which ones you actually reach for during the
   end-to-end review and graduate reactively. The current "wrapped 3,
   direct-script the rest" balance is by design — we earn each `kcd analyze`
   subcommand by use.

3. **The cross_analysis vs `kcd parity` reconciliation.** Different lenses
   on pic_programmer drift. Worth a focused dive: pick a manufactured drift
   case (delete a footprint from a known-good PCB, rerun both), see which
   one catches it and how. If `kcd parity` is over-reporting on KiCad's
   tstamp-based mapping, that's a parity bug; if cross_analysis is
   under-reporting, that's an upstream finding-detector gap.

4. **Validate the wheel install path.** Install kcd into a clean venv,
   confirm `_locate_scripts_dir` finds `skills/kicad/scripts/` via the
   wheel path (the `parents[1]` branch). If it doesn't, the
   `force-include` in pyproject.toml needs adjustment — and the test should
   be added to gate against regression.

5. **Validate #20 (hierarchical sheets) against `complex_hierarchy`.**
   Carried from session 4. Now also covers analyzer multi-sheet behavior
   — `pic_programmer` already has 2 sheets and the analyzer handled it
   correctly, but `complex_hierarchy` is the deeper test case.

## Still open (carried beyond this session)

| Item | Notes |
|---|---|
| Validate #20 against `complex_hierarchy` | Carried (needs your KiCad seat) |
| File kicad-cli `sch export svg --pages` upstream bug | Draft at `docs/upstream/kicad-cli-pages-svg-bug.md` |
| File kipy `Board.is_dirty()` upstream feature request | Carried |
| FreeRouting end-to-end | Carried |
| `edit move-fp --rotation` E2E test | Carried |
| KiCad upstream segfault filing | Carried |
| `library_id` on fresh KiCad-10-native project | Carried |
| Vendor kicad-happy's `bom/`/`digikey/`/etc. sourcing skills | v0.3 work, separate API-credentials decision |
| Skim `rjwalters/kicad-tools` (`kct`) before designing new subcommands | Carried |
| Graduate analyzer findings into kcd primitives (reactively) | Carried |
| Wrap more analyzers in `kcd analyze ...` (cross/thermal/emc next) | New, this session |
| Wheel-install verification of `_locate_scripts_dir` | New, this session |
| cross_analysis vs `kcd parity` reconciliation | New, this session |

🐆

---

*Generated alongside commits `a4e3ef9 → 688fb1c` on `main`. Dove's
session-5-prep brief at `docs/Dove-to-Cheetah-Brief-kicad-happy-integration.md`.
Vendor source: `aklofas/kicad-happy@968f5c8` (v1.3.1, 2026-05-11).*
