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

## Pending divergences from upstream content

- `SKILL.md` rewrite (Phase C): replace `python3 scripts/analyze_*.py` examples
  with `kcd analyze sch|pcb|gerbers` examples. Preserve structure (file-types
  quick reference, analysis depth principles, datasheet acquisition,
  schematic↔PCB cross-reference). Will be logged with file:line ranges once
  the rewrite lands.

## Interesting findings (not patches, but worth surfacing)

- **cross_analysis vs kcd parity disagree on pic_programmer drift.**
  `kcd parity` (session 4) reported C6, C7 on the PCB without schematic backing.
  Upstream `cross_analysis.py --schematic sch.json --pcb pcb.json` returns
  0 findings against the same project. Different lenses on the same data —
  worth surfacing in the next Cheetah↔Dove closeout. Not a bug in either
  layer, just a research signal that the two views need reconciliation in
  Phase C's skill body (when to trust which).
