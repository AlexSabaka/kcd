# Patches: skills/kicad/

Track every kcd-side modification to vendored files so we can submit fixes
upstream and keep the diff against `aklofas/kicad-happy` minimal. If you edit
anything in this directory tree, log it here with: filename, line range, what
changed, why, and (eventually) a link to the upstream PR.

## Vendored from `968f5c847121e1c36a4ed848f2bab87f9dfc1016` (kicad-happy v1.3.1)

Verified against:
- `pic_programmer.kicad_sch` (KiCad 10 project, schematic file_version
  `20231120` / kicad_version `8.0` per the analyzer's detection — file format
  unchanged between KiCad 8 and 10 for schematics) — `analyze_schematic.py`
  exits 0, 50 top-level JSON keys, 66 components, 2 sheets, LT1373 detected as
  U4.
- `pic_programmer.kicad_pcb` (KiCad 10 PCB, kicad_version `10.0` per the
  analyzer's detection) — `analyze_pcb.py` exits 0, 38 top-level JSON keys,
  63 footprints.
- `cross_analysis.py --schematic <sch.json> --pcb <pcb.json>` — exits 0,
  returns 0 findings on pic_programmer.

**No KiCad-10 surgical patches required** at vendor time. Both analyzers
parse the KiCad 10 demo project cleanly without crashes or warnings.

## Known divergences from upstream behavior on KiCad-10 projects

None observed yet. If anything surfaces during Phase B integration testing,
log it here with the analyzer + input + observed-vs-expected output, then file
upstream.

## Divergences from upstream content

### SKILL.md — kcd-native rewrite (Phase ω)

Added a new "## Using this skill from kcd" section between the title and
"## Related Skills" (originally line 21; now begins around line 22 after the
insert). The new section teaches the standard kcd-native loop —
`kcd project current` + `kcd analyze sch/pcb` + `kcd parity` in parallel as
the opening move for any review — and clarifies that `<skill-path>` in the
upstream sections below means `skills/kicad` relative to the kcd repo root.

Replaced the three core-analyzer command blocks to lead with `kcd analyze *`
and kept the direct `python3 skills/kicad/scripts/...` form as a fallback
for advanced flags not yet exposed (`--analysis-dir`, `--proximity`,
`--full`, `--schema`, `--audience`, `--stage`):

  Schematic Analyzer block — `### Schematic Analyzer` heading
  PCB Layout Analyzer block — `### PCB Layout Analyzer` heading
  Gerber & Drill Analyzer block — `### Gerber & Drill Analyzer` heading

Updated the Minimum Review Checklist (under `### Minimum Review Checklist`)
to reference `kcd analyze sch|gerbers` for the wrapped analyzers and explicit
`python3 skills/kicad/scripts/<name>.py` invocations for the not-yet-wrapped
ones (`analyze_pcb.py --full`, `cross_analysis.py`, `analyze_emc.py`,
`analyze_thermal.py`) so reviewers can still complete the full contract.

All other `python3 <skill-path>/scripts/...` invocations elsewhere in the
file (cross_analysis, what_if, diff_analysis, analyze_thermal,
datasheet_page_selector, etc.) are intentionally left as upstream — the
kcd-native preamble tells the reader to substitute `skills/kicad` for
`<skill-path>` so the existing examples still work from the kcd repo root.

### SKILL.md + references/agentic-editing.md — editing surface

Driven by `docs/Dove-to-Cheetah-Skill-Audit-Report.md` (the R6 field-test
audit). Upstream kicad-happy is a review-only skill; kcd adds a mutating
surface (edit / render / snapshot / route / export) with no upstream
equivalent, so this content is **kcd-native, not a divergence from upstream
text**:

- New `references/agentic-editing.md` — the edit loop, KiCad/IPC ceilings,
  the mutating-tool catalog, host/container artifact paths. Entirely kcd's.
- SKILL.md gains a `## Agentic Editing & Iteration` body section pointing
  to it, plus a row in the Reference Files table.
- Stale-fact corrections to the kcd-native schema notes (not upstream
  text): dropped `net_name_to_id` from the PCB top-level key list (kcd
  dedupes it), noted `routing_complete` is DRC-reconciled in both
  `statistics` and `connectivity`, and added the host/container artifact
  caveat. These reflect kcd R5-R7 behaviour, not kicad-happy.

The audit's `CODE-BUG+CAVEAT` items (A2, C, D1, D2) were **fixed in the kcd
R6 rework / R7**, so the skill documents working features rather than
carrying caveats.

## Interesting findings (not patches, but worth surfacing)

- **cross_analysis vs kcd parity disagree on pic_programmer drift.**
  `kcd parity` (session 4) reported C6, C7 on the PCB without schematic backing.
  Upstream `cross_analysis.py --schematic sch.json --pcb pcb.json` returns
  0 findings against the same project. Different lenses on the same data —
  worth surfacing in the next Cheetah↔Dove closeout. Not a bug in either
  layer, just a research signal that the two views need reconciliation in
  Phase C's skill body (when to trust which).
