# Brief: integrate kicad-happy as kcd's skills foundation

**From:** Dove 🕊️ (session 5 prep)
**To:** Cheetah 🐆 (next major work)
**Date:** 2026-05-19
**Branch:** new feature branch, expect multi-day work

## Mission

Vendor `aklofas/kicad-happy`'s analyzer layer and `mattpainter701/my-claude-setup`'s reference docs into kcd as the foundation of kcd's *design-review skill* — the knowledge layer that complements kcd's existing *live-editing tool* layer. Drop the result behind new `kcd analyze` subcommands and surface the reference docs as kcd's first proper skill at `skills/pcb-review/`.

This is the move that turns kcd from "tool that does what an agent asks" into "tool that knows what a competent EE would ask for next."

## Strategic context

After Sabaka's quick survey of existing KiCad-related skill repos, the cleanest division of labor falls out naturally:

- **kcd already has**: low-level, IPC-live, snapshot-safe access — inspect / edit / parity / DRC / ERC / snapshot lifecycle, kipy + kicad-skip + kicad-cli all wrapped behind a clean JSON envelope.
- **kcd doesn't have**: the *what to look for* layer — Vref lookup tables for 60+ regulator families, decoupling-tier heuristics, thermal-pad-via adequacy thresholds, IPC-2221A trace-width tables, SOT-23 pinout-ambiguity detection, USB compliance checks, ground-domain classification, ...

`kicad-happy` has the second of those. It's MIT, KiCad 5–10, validated against 5,800+ open-source projects per the author, and the analyzer scripts emit structured JSON that's clean to wrap. `mattpainter701/my-claude-setup` ships the same analyzer family with substantially expanded reference docs (~5K lines of standards-citing review methodology). Together they're the missing knowledge layer.

The two compose like this:
```
kicad-happy/mattpainter says:  "Your MAX17760 feedback divider computes 14.95V, not 12V — Vref heuristic may be wrong, see datasheet table 1"
kcd says:                       "Fix R6 from 226k to 158k, snapshot first, re-render, re-parity, re-analyze"
```

## What to vendor

### From `aklofas/kicad-happy`

Vendor **only the `kicad/` skill folder** at first. The rest (bom, digikey, mouser, lcsc, jlcpcb, pcbway) are sourcing/manufacturing skills with API-credential requirements — different scope, defer.

Files we want:
- `kicad/scripts/analyze_schematic.py` — schematic structure → JSON
- `kicad/scripts/analyze_pcb.py` — PCB layout → JSON
- `kicad/scripts/analyze_gerbers.py` — Gerber/drill → JSON
- `kicad/SKILL.md` and any reference subfolder
- `kicad/scripts/README.md` (if present — explains analyzer internals)

### From `mattpainter701/my-claude-setup`

Vendor `claude-config/skills/hardware/kicad/references/`:
- `schematic-analysis.md` (~1117 lines — deep schematic review methodology)
- `pcb-layout-analysis.md` (~414 lines — impedance, diff pairs, return paths)
- `standards-compliance.md` (~597 lines — IPC-2221A/IPC-2152/IEC 60664-1 tables)
- `file-formats.md` (~361 lines — KiCad S-expr field reference)
- `pdf-schematic-extraction.md` (~315 lines — extract from datasheets / app notes)
- `supplementary-data-sources.md` (~301 lines — legacy KiCad 5 recovery)
- `report-generation.md` (~479 lines — review report template + severity definitions)
- `manual-{schematic,pcb,gerber}-parsing.md` (fallbacks when scripts fail)

These are the *expertise* docs. `kicad-happy`'s analyzer is the data layer; `mattpainter`'s references are the interpretation layer. They were originally co-designed (commits suggest shared lineage — please verify; if mattpainter is a fork of kicad-happy with expanded docs, vendor *only from the source of each artifact*, never both).

## What NOT to vendor (yet, or ever)

| Source | Reason |
|---|---|
| kicad-happy's `bom` / `digikey` / `mouser` / `lcsc` / `jlcpcb` / `pcbway` skills | API credentials needed; sourcing workflow is a separate concern; defer to v0.3. The architecture should accommodate them, but no need to vendor today. |
| `Roboworks-Automation/Kstack` | Tightly coupled to `kiutils` (we use `kicad-skip` + `kipy`). Different mental model: mines *your own design history*. Steal the knowledge-graph idea later as a kcd-native feature; don't vendor. |
| `rjwalters/kicad-tools` (`kct`) | Competing CLI. Different design choices than kcd (no IPC, bundled autorouting, CMA-ES placement). **Don't vendor.** Use as research target — read their `kct --help` before designing each new kcd subcommand. |
| `2456018331lby-dev/embedded-engineering-skill` | Too broad (covers MCU selection, firmware, RF). Light on KiCad mechanics. Skip. |
| `Prithvi-0g/claude-kicad-skills` | Inaccessible via fetch. Sabaka could check manually but no strong signal. |
| mcpmarket.com pages | Marketing landing pages, no raw content. Skip. |

## Concrete integration plan

### Phase A — vendor + verify (target: ~1 day)

1. **Sibling-clone, don't submodule.** Clone `kicad-happy` to `/tmp/kicad-happy-src` (or a sibling dir). Verify it doesn't try to be a git submodule of kcd — we want the freedom to edit, refactor, and remove what we don't need.

2. **Create the skills directory layout:**
   ```
   kcd/
   ├── skills/                                     ← NEW
   │   └── pcb-review/                             ← First skill
   │       ├── SKILL.md                            ← Reauthored, kcd-specific
   │       ├── ATTRIBUTION.md                      ← Credits + license trail
   │       ├── scripts/
   │       │   ├── analyze_schematic.py            ← from kicad-happy
   │       │   ├── analyze_pcb.py                  ← from kicad-happy
   │       │   └── analyze_gerbers.py              ← from kicad-happy
   │       └── references/
   │           ├── schematic-analysis.md           ← from mattpainter
   │           ├── pcb-layout-analysis.md          ← from mattpainter
   │           ├── standards-compliance.md         ← from mattpainter
   │           ├── file-formats.md                 ← from mattpainter
   │           ├── pdf-schematic-extraction.md     ← from mattpainter
   │           ├── supplementary-data-sources.md   ← from mattpainter
   │           ├── report-generation.md            ← from mattpainter
   │           └── manual-{sch,pcb,gerber}-parsing.md
   ```

3. **Verify against `pic_programmer`** (the demo we know intimately):
   ```bash
   python3 skills/pcb-review/scripts/analyze_schematic.py \
       /Volumes/2TB/_electronics/demos/pic_programmer/pic_programmer.kicad_sch \
       > /tmp/sch-out.json
   python3 skills/pcb-review/scripts/analyze_pcb.py \
       /Volumes/2TB/_electronics/demos/pic_programmer/pic_programmer.kicad_pcb \
       > /tmp/pcb-out.json
   ```
   Must not crash. Inspect output:
   - Does it find the LT1373 regulator and compute Vout?
   - Does it find the C6, C7 PCB-only drift that `kcd parity` flagged?
   - Does it run on the "Racine" root sheet correctly?

   The scripts are written for KiCad 5–9; KiCad 10's `.kicad_sch` format may have minor field changes. **Expect to patch.** Track everything you change to vendored files in a `skills/pcb-review/PATCHES.md` so we can submit upstream.

### Phase B — wire under kcd CLI (target: ~1 day)

1. **Three new top-level commands:**
   ```
   kcd analyze sch     <proj> [--out <file>] [--full] [--compact] [--json]
   kcd analyze pcb     <proj> [--out <file>] [--full] [--proximity] [--json]
   kcd analyze gerbers <gerber-dir>           [--full] [--json]
   ```
   Each is a thin wrapper that:
   - Resolves the project path via the standard `core/project.py::resolve`
   - subprocess-invokes the analyzer script
   - Wraps the analyzer JSON in the standard kcd envelope (`{ok, command, data, warnings, artifacts, snapshot_before, error}`)
   - Pulls top-level analyzer warnings (regulator Vout mismatches, missing decoupling, unverified pinouts) up into envelope `warnings[]` so agents see them without parsing the full JSON
   - Saves the raw analyzer JSON as an artifact at a stable path (e.g. `/tmp/kcd/<proj>-analyze-sch.json`) — analyzer runs are expensive, agents will want to re-read

2. **No snapshot needed.** Analysis is read-only.

3. **Surface tier from `pcb-review` skill content as kcd warnings**:
   The mattpainter docs talk about "verify analyzer output against reality" — that's an agent prompt to look at the raw `.kicad_sch` and cross-reference. kcd's existing `inspect_sch` already returns the truth; the analyzer's JSON is the inferred view. Treat any analyzer claim with a `vref_source: "heuristic"` (vs `"lookup"`) as needing a warning automatically.

### Phase C — first kcd-native skill (target: ~1 day)

1. **Reauthor `skills/pcb-review/SKILL.md`** — don't ship mattpainter's verbatim. The mattpainter SKILL.md describes calling `python3 <skill-path>/scripts/analyze_*.py` directly; kcd users should call `kcd analyze *`. Take mattpainter's structure (file-types quick reference, analysis depth principles, datasheet acquisition, schematic-PCB cross-reference) but rewrite the command examples for kcd. Cite mattpainter prominently in `ATTRIBUTION.md`.

2. **Skill activation conditions** in the YAML frontmatter:
   ```yaml
   name: pcb-review
   description: |
     Use when reviewing a KiCad project for design errors, manufacturability,
     or sourcing readiness — triggers on phrases like "review my board",
     "check before fab", "find bugs in this schematic", or when the user
     loads a kicad_pro/kicad_sch/kicad_pcb file and asks for evaluation.
   ```

3. **Skill body teaches the loop**:
   - Always start with `kcd project current` + `kcd analyze sch` + `kcd analyze pcb` + `kcd parity` in parallel
   - Cross-reference results to find the "high-confidence" issues
   - Reach for `references/schematic-analysis.md` for deep dives on specific subcircuits
   - Use `kcd inspect ref`, `kcd inspect pcb`, `kcd snapshot` for any verification step that needs ground-truth data
   - Produce reports via `references/report-generation.md`'s template

## Attribution and licensing

- **Both upstream projects are MIT.** Compatible with kcd. Preserve the MIT headers in every vendored file.
- **`skills/pcb-review/ATTRIBUTION.md`** must list:
  - Original repo URL + commit hash we vendored from
  - Original author (aklofas, mattpainter701)
  - License (MIT)
  - The list of files vendored from each source
  - Our modifications (kept brief — link to PATCHES.md)
- **Don't vendor across forks.** Before vendoring mattpainter's references, check whether they're verbatim copies of kicad-happy's docs (current evidence suggests shared lineage). If a doc exists in both: vendor from the originator. If we can't determine the originator, vendor from mattpainter (more detailed) and credit both in ATTRIBUTION.

## Verification checklist (before merging)

- [ ] `python3 skills/pcb-review/scripts/analyze_schematic.py pic_programmer.kicad_sch` runs without crashing
- [ ] `python3 skills/pcb-review/scripts/analyze_pcb.py pic_programmer.kicad_pcb` runs without crashing
- [ ] Output JSON has `components`, `bom`, `nets`, `signal_analysis`, `design_analysis` keys
- [ ] Analyzer detects the LT1373 regulator
- [ ] Analyzer's `pcb_only` (or equivalent) drift detection sees C6, C7 — *and matches `kcd parity`* (they should agree; if not, that's a finding)
- [ ] `kcd analyze sch pic_programmer --json` wraps with the standard envelope
- [ ] `kcd analyze pcb pic_programmer --json` wraps with the standard envelope
- [ ] `kcd analyze gerbers <some_gerber_dir> --json` wraps with the standard envelope
- [ ] `skills/pcb-review/SKILL.md` is kcd-native (no `python3 <skill-path>/scripts/...` examples)
- [ ] `skills/pcb-review/ATTRIBUTION.md` cites originals
- [ ] CLAUDE.md updated to mention `kcd analyze` and the `skills/` directory
- [ ] CHANGELOG.md entry for the integration
- [ ] Tests: at minimum 3 (one per analyzer subcommand), gated on `KCD_INTEGRATION=1` since they need actual `.kicad_*` files. Easiest fixture: copy a small kicad_sch into `tests/fixtures/` (3-4 components — `kicad-skip` ships demos we can borrow).

## Inspirations not vendored

These three I'd like you to *skim* (not study) before starting:

- **`rjwalters/kicad-tools` (`kct`)** — read `kct --help` to see what they expose. If their command names are better than ours, copy. Specifically look at: `kct check` (pure-Python DRC), `kct route` (autorouting), manufacturer-tier exports. Don't compete on autorouting (we have FreeRouting), but their `check` vs our `drc` is worth comparing.
- **`Roboworks-Automation/Kstack`** — read the `kicad-block-extract` SKILL.md. The idea of mining MCU↔peripheral connectivity across a user's project history is novel; if we ever want a "you've used ESP32 IO21 for I2C 14 times before" feature, that's the prior art.
- **`drandyhaas/KiCadRoutingTools`** (surfaced during my survey) — has an `analyze-power-nets` skill that uses Claude to *classify* component roles (POWER_SOURCE / CURRENT_SINK) when reference prefixes lie. That's a clever pattern — uses LLM judgment as a parsing primitive. Worth knowing about for v0.3.

None of these get vendored. They're prior art to read before designing.

## Carries from session-4 closeout

These all stay open after Phase A–C:

| Item | Notes |
|---|---|
| Validate #20 against `complex_hierarchy` demo | Needs Sabaka to switch KiCad's open project. After integration, this *also* covers analyzer multi-sheet support. |
| File `kicad-cli sch export svg --pages` upstream bug | Draft is paste-ready at `docs/upstream/kicad-cli-pages-svg-bug.md`. Filing is Sabaka's call. |
| File kipy `Board.is_dirty()` upstream request | Still wanted. |
| `library_id` on fresh KiCad-10-native project | Carried. The analyzer's behavior on a fresh project will *also* tell us whether the empty-lib_id was pic_programmer-specific. |
| FreeRouting end-to-end | Carried. |
| `edit move-fp --rotation` E2E test | Carried. |
| KiCad upstream segfault filing (eeschema+pcbnew both open IPC bug) | Carried. |
| README ↔ CLI drift cleanup (now needs `kcd parity` + `kcd analyze`) | Bumped — bigger surface area now. |

## New finding — file as #25 before integration starts

**#25 — `kcd parity` against a project where KiCad has a *different* board open**: per your session-4 closeout question, currently `kipy_pcb.list_footprints()` returns whatever's open, which means a parity check could silently compare the requested project's schematic against an unrelated PCB. Fix: at the top of `kcd parity`, call `project_current()`, compare its board path to the resolved `proj.pcb` path; if different, return `{ok: false, error: {code: "wrong_board_open", message: "KiCad has <other.kicad_pcb> open, not the requested <this.kicad_pcb>. Switch KiCad or pass --no-pcb-compare for schematic-only output."}}`. ~10 LOC. Same defensive-warning pattern as the move-fp concurrent-save fix. Land before merging Phase A so it doesn't interact with analyzer integration.

## What I'd want from session 5 (Dove side)

After Phase A–C land:

1. **Run `kcd analyze sch pic_programmer --json`** and read the output. Compare its findings to what `kcd parity` returned in session 4 (PCB-only C6/C7). Different lenses on the same drift should agree.
2. **Validate #20 against `complex_hierarchy`** — both kcd's `locate()` walker AND the analyzer's multi-sheet handling.
3. **See if any analyzer findings should graduate into kcd primitives.** Example: if the analyzer routinely surfaces "starved thermal pad" with structured data, maybe `kcd inspect ref U4 --json` should include `pcb.thermal_pad: {via_count: 14, recommended: 16, status: "warning"}` as part of the standard response. Don't pre-commit to this — see what the analyzer actually flags and decide reactively.
4. **First end-to-end review session**: load a real (not demo) project, run the full review skill loop, write a report using `references/report-generation.md`'s template. The output of that session is the validation that the integration works.

## On scope creep

A few temptations to resist during this integration:

- **Don't refactor kcd's adapters to use the analyzer.** The analyzer is a parallel reader; our `inspect_sch` / `inspect_pcb` are still the canonical live-data sources. They coexist. Long-term we might consolidate, but not now.
- **Don't vendor the sourcing skills (bom, digikey, lcsc, etc.) "for completeness."** They're a separate axis (API credentials, network calls) and a separate vendor decision.
- **Don't rewrite the analyzer scripts in our style.** Vendor as-is, patch surgically where KiCad 10 breaks them, file PRs upstream for the fixes. Reverse-engineering and rewriting loses the "5,800-projects-validated" provenance.

🕊️
