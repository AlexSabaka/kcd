---
name: kicad
description: >-
  Analyze KiCad projects and PDF schematics: schematics, PCB layouts, Gerbers,
  footprints, symbols, netlists, and design rules. Reviews designs for bugs,
  traces nets, cross-references schematic to PCB, extracts BOM data, checks
  DRC/ERC, DFM, power trees, and regulator circuits. Every finding carries a
  confidence label and evidence source with trust_summary rollup. Analyzes PDF
  schematics from dev boards, reference designs, eval kits, and datasheets.
  Supports KiCad 5–10. Use whenever the user mentions .kicad_sch, .kicad_pcb,
  .kicad_pro, PCB design review, schematic analysis, PDF schematics, reference
  designs, Gerber files, DRC/ERC, netlist issues, BOM extraction, signal
  tracing, power budget, DFM, or wants to understand, debug, compare, or
  review any hardware design. Also for "check my board", "review before fab",
  "what's wrong with my schematic", "is this ready to order", "check my power
  supply", "verify this circuit", or any electronics/PCB design question.
---

# KiCad Project Analysis Skill

## Using this skill from kcd

This skill is vendored into the kcd repo (originator: `aklofas/kicad-happy`
— see `ATTRIBUTION.md`). **Every analyzer is reachable as a `kcd analyze`
subcommand** — and therefore as an MCP tool — so this skill runs the same
whether kcd is driven from a shell or purely over MCP (Claude Code, Claude
Web). There is no separate `python3 .../scripts/...` path; the `kcd` CLI is
the only surface.

```bash
# Single-domain analyzers
kcd analyze sch      <project>   --json   # schematic structure + findings
kcd analyze pcb      <project>   --json   # PCB layout + DFM (--full for the deep pass)
kcd analyze gerbers  <directory> --json   # fabrication-output checks

# Cross-domain & specialised analyzers — pass a project, not pre-built JSON;
# they run the prerequisite sch/pcb analyzers for you
kcd analyze cross     <project>  --json            # schematic<->PCB cross-checks
kcd analyze thermal   <project>  --json            # junction temps, thermal vias
kcd analyze fab-gate  <project>  --json            # ready-for-fab pass/fail gate
kcd analyze whatif    <project> R5=4.7k --json     # component-value sweep
kcd analyze lifecycle <project>  --json            # BOM obsolescence + temp audit
kcd analyze diff      base.json head.json --json   # delta between two runs
```

`<project>` accepts a `.kicad_pro` path, a project directory, or the project
name. Each command wraps its analyzer in the standard kcd JSON envelope: the
raw analyzer JSON lands at `$KCD_RENDER_CACHE/<name>-analyze-<verb>.json` and
is registered as an envelope artifact for cheap re-reads. Findings with
severity `warning`, `error`, or `critical` are mirrored into envelope
`warnings[]` (tagged `[severity][rule_id]`) so even a skim of the response
surfaces the headline issues.

**Standard agentic loop (opening move for any KiCad review):**

```bash
kcd project current --json    # what is KiCad working on right now?
kcd analyze sch <project> --json
kcd analyze pcb <project> --json
kcd parity     <project> --json   # schematic <-> PCB reference-set drift
```

Cross-reference the results to find high-confidence issues — anything flagged
by both an analyzer AND `parity` is almost certainly real; analyzer-only
findings need verification against the primary source (`kcd inspect ref`,
`kcd inspect pcb`, raw `.kicad_sch`). See `references/schematic-analysis.md`,
`references/pcb-layout-analysis.md`, and `references/standards-compliance.md`
for the deep-dive methodology.

## Related Skills

| Skill | Purpose |
|-------|---------|
| `bom` | BOM extraction, enrichment, ordering, and export workflows |
| `digikey` | Search DigiKey for parts (prototype sourcing) |
| `mouser` | Search Mouser for parts (secondary prototype source) |
| `lcsc` | Search LCSC for parts (production sourcing, JLCPCB) |
| `element14` | Search Newark/Farnell/element14 (international sourcing, reliable datasheets) |
| `jlcpcb` | PCB fabrication & assembly ordering |
| `pcbway` | Alternative PCB fabrication & assembly |
| `spice` | SPICE simulation verification of detected subcircuits |
| `emc` | EMC pre-compliance risk analysis — consumes schematic + PCB analyzer output |

**Handoff guidance:** Use this skill to parse schematics/PCBs and extract structured data. Hand off to `bom` for BOM enrichment, pricing, and ordering. Hand off to `digikey`/`mouser`/`lcsc`/`element14` for part searches and datasheet fetching. Hand off to `jlcpcb`/`pcbway` for fabrication ordering and DFM rule validation. **Always run `spice`** for simulation verification during design reviews when any SPICE simulator is installed (check with `which ngspice ltspice xyce`). **Always run `emc`** for EMC pre-compliance risk analysis during design reviews when both schematic and PCB analysis are available. These are not optional — skipping them leaves value-computation errors and EMC risks undetected.

**Before analysis:** When the user asks to analyze or review a KiCad project, check whether a `datasheets/` directory exists in the project. If not, and DigiKey API keys are available (`DIGIKEY_CLIENT_ID`), offer to sync datasheets first: "I can download datasheets for your components before analysis — this enables pin-level verification and decoupling validation against manufacturer specs. Want me to sync them?" If the user declines or no API keys are set, proceed without datasheets — the analysis works without them but datasheet verification findings won't be available.

**If you see a `DS-001` finding in the analyzer output** (severity `high`, detector `audit_datasheet_coverage`), the review cannot make any verified claim. Stop and either (a) run the datasheet sync via `digikey` / `mouser` / `lcsc` / `element14` (whichever has credentials/stock), (b) populate MPNs on the BOM parts, or (c) state explicitly in the report that every pin-level, electrical, and regulator finding is *consistency only* — do not use the words "verified", "confirmed", or "per datasheet" anywhere. `DS-002` (datasheets missing but MPNs set) and `DS-003` (partial MPN coverage) are softer variants with the same implication for the parts they cite.

## Design Review Contract

When the user asks for a **design review**, **complete report**, **ready-to-fab assessment**, or anything equivalent, do not stop at running one or two analyzers and summarizing their findings. A design review in this skill has a stricter contract:

1. Read the full workflow in this `SKILL.md`, not just the analyzer command sections.
2. Read `references/report-generation.md` before writing the report.
3. Run every applicable analyzer for the files present in the project, then say explicitly which ones were and were not run.
4. Perform raw-file and datasheet cross-verification before claiming anything is "verified".
5. Triage likely analyzer false positives before elevating them into blockers.
6. If a required step could not be done, state it as a review gap, not as silent omission.

Treat this as the minimum bar. Analyzer JSON alone is not the final review.

### Minimum Review Checklist

For a full design review, explicitly account for each item below in the report:

- `datasheets/` present, synced, or verification gap stated
- `kcd analyze sch <project> --json`
- `kcd analyze pcb <project> --full --json`
- `kcd analyze cross <project> --json`
- EMC pre-compliance via the `emc` skill when both schematic and PCB exist
- SPICE simulation when any simulator is installed
- `kcd analyze thermal <project> --json` when both schematic and PCB exist
- `kcd analyze gerbers <gerber_dir> --json` when fabrication outputs exist
- `kcd analyze lifecycle <project> --json` when network access and MPN coverage allow it
- prior-review / prior-run delta check (`kcd analyze diff`)
- raw schematic/PCB spot-verification elevated to full verification for critical parts
- explicit report sections for blockers, verification basis, false positives, and skipped analyses

If an item is not applicable, say why. If it was skipped, say why. If it failed, say how that limits confidence.

### Common Review Failure Modes

These are the failure modes this contract is meant to prevent:

- Stopping after schematic + PCB + EMC output and calling it a complete review
- Reporting analyzer findings without checking whether they are expected layout artifacts
- Claiming "verified" without direct datasheet evidence or structured extraction evidence
- Omitting thermal, lifecycle, prior-review delta, or gerber checks without disclosure
- Writing a report that lacks a verdict, blockers table, verification basis, or skipped-analysis notes
- Reading only the first part of this skill and missing the design-review workflow later in the file

## PDF Schematic Analysis

This skill also handles **PDF schematics** — reference designs, dev board schematics, eval board docs, application notes, and datasheet typical-application circuits. Common use cases:

- Analyze a manufacturer's reference design to understand the circuit
- Extract a subcircuit (power supply, USB interface, sensor front-end) to incorporate into your own KiCad design
- Compare a PDF reference design against your own schematic
- Extract a full BOM from a PDF schematic
- Validate component values in a PDF against current datasheets

**Workflow:** Read the PDF pages visually → identify components and connections → extract structured data → translate to KiCad symbols and nets → validate against datasheets.

For the full methodology — component extraction, notation conventions, net mapping, subcircuit extraction, KiCad translation, and validation — read `references/pdf-schematic-extraction.md`.

For deep validation of extracted circuits against datasheets (verifying values, checking patterns, detecting errors), use the methodology in `references/schematic-analysis.md`.

## Analyzers

kcd's analyzers extract comprehensive structured JSON from KiCad files in a
single pass. Run the relevant `kcd analyze` command first, then reason about
the output.

The full analyzer JSON is in the envelope's `data` field (and in the artifact
file kcd writes to `$KCD_RENDER_CACHE`). Read the field you need directly —
the schema has specific field names (documented below and in
`references/output-schema.md`) that are easy to get wrong.

**When the JSON surprises you** — an unexpected shape, or a field returning
`None` that "should" have a value — consult `references/output-schema.md`,
which documents the exact field names and types for every top-level key,
before assuming a bug.

**JSON field cheat sheet** — the most common mistakes when reading analyzer
output by hand:

| What you want | Correct path and field | Common mistake |
|---------------|-----------------------|----------------|
| Pins on a net | `nets[<name>].pins[].component / .pin_number / .pin_name / .pin_type` | `ref`, `pin`, `type`, `number` |
| Unnamed-net pretty display | `nets[<name>].display_name` — when set, a `Ref.PinName` hint for an `__unnamed_N` net whose only named IC pin tells the story (e.g. `__unnamed_36 → U1.VBOOT`). Absent means the analyzer couldn't disambiguate. | Ignoring `display_name` and pasting raw `__unnamed_36` into the report |
| IC pin map | `ic_pin_analysis[]` is a **list** of IC entries; each has `.reference` and `.pins[]` with `.pin_number / .pin_name / .pin_type / .net / .connected_to[]` | Treating it as `{ref: {...}}` or `pins[].number` |
| Detected circuits | Every pattern-matched circuit (power regulators, RC filters, crystal oscillators, bridges, …) lives in `findings[]` — filter with `finding_schema.get_findings(data, Det.POWER_REGULATORS)` etc. **Do not read from `subcircuits[]`**: that's an IC-neighborhood grouping (`{center_ic, ic_value, neighbor_components, …}`), not a categorized detection index | Looking for `subcircuits.power_regulators`, `subcircuits.rc_filters`, or any `subcircuits[type]` key — these never existed in v1.3 output |
| Zone net | `pcb.zones[].net` is an **integer net ID**, not a string. Use `f"{net!r}"` or convert first | `f"{net:20s}"` — crashes with `ValueError: Unknown format code 's' for object of type 'int'` |
| Footprint position | `pcb.footprints[].x / .y` at top level (no `.position` wrapper) | `footprints[].position.x` |
| Findings | `findings[]` flat list — each has `rule_id`, `detector`, `severity`, `summary`, `report_context`. Filter with `finding_schema.get_findings(data, Det.*)` or `group_findings(data)` | Looking for keyed dicts like `signal_analysis.power_regulators[]` (pre-v1.3 format, removed) |

See `references/output-schema.md` for the full schema with common extraction
patterns.

### Schematic Analyzer
```bash
kcd analyze sch <project> --json
kcd analyze sch <project> --out custom-path.json --json   # custom artifact path
```
Wraps the schematic analyzer in the standard JSON envelope, lifts findings
with severity >= warning into envelope `warnings[]`, and saves the raw JSON
as an artifact. Outputs structured JSON (~60-220KB depending on board
complexity) with:
- **Components & BOM**: inventory with reference, value, footprint, lib_id, type classification, MPN, datasheet; deduplicated BOM with quantities
- **Nets**: full connectivity map with pin-to-net mapping, wire counts, no-connects
- **Detected subcircuits** (pattern-matched circuits — all emitted as `findings[]` entries with matching `Det.*` detectors; use `get_findings(data, Det.POWER_REGULATORS)` etc. to fetch):
  - Power regulators — LDO/switching/inverting topology, Vout estimation via datasheet-verified Vref lookup (~60 families) with heuristic fallback and fixed-output suffix parsing, `vref_source` (`lookup`/`heuristic`/`fixed_suffix`) and `vout_net_mismatch` fields
  - Voltage dividers, RC/LC filters (cutoff frequency), feedback networks, crystal circuits (load cap analysis, IC pin-based detection)
  - Op-amp circuits (configuration, gain, integrator/compensator), transistor circuits (net-name-aware load classification: motor/heater/fan/solenoid/valve/pump/relay/speaker/buzzer/lamp; FET level shifter topology)
  - Bridge circuits (H-bridge, 3-phase, cross-sheet detection), protection devices (ESD/TVS), current sense, decoupling analysis
  - Domain-specific: RF chains, RF matching networks, BMS, Ethernet (BFS PHY-to-connector tracing), HDMI/DVI interfaces, memory interfaces, key matrices (net-name and topology-based), isolation barriers, addressable LED chains (WS2812/SK6812/APA102), battery chargers (TP4056/MCP73831/BQ2404x), motor drivers (A4988/TMC2209/DRV8301), ESD protection coverage audit, debug interfaces (SWD/JTAG with MCU tracing), power path (load switches/ideal diodes/USB PD controllers), ADC signal conditioning (external ADCs + voltage references with anti-aliasing cross-ref), reset/supervisor circuits (voltage supervisors/watchdogs/RC reset networks), clock distribution (clock generators/PLLs/oscillator output tracing), display/touch interfaces (SSD1306/ILI9341/ST7789/FT6236/GT911), sensor fusion (IMU/environmental/magnetometer with interrupt validation and bus clustering), level shifters (IC-based + discrete BSS138 with supply domain mapping), audio circuits (amplifiers/codecs with I2S/class-D detection), LED driver ICs (PWM/matrix/constant-current), RTC circuits (battery backup/crystal pairing), LED lighting audit (current limiting validation), thermocouple/RTD interfaces (MAX31855/MAX31865), power sequencing validation (power tree/enable chain/PG daisy chain analysis)
- **IC pinout analysis**: pin-level connectivity, IC function classification (3-tier: library prefix, part number keywords, description fallback)
- **Power analysis**: PDN impedance (1kHz–1GHz with MLCC parasitics), power budget, power sequencing (EN/PG chains), sleep current audit (resistive paths + regulator Iq with EN detection), voltage derating, inrush estimation
- **Design analysis**: ERC warnings, power domains, bus detection (I2C/SPI/UART/CAN/RS-485 with COPI/CIPO/SDI/SDO), differential pairs (suffix-pair matching for USB/LVDS/Ethernet/HDMI/MIPI/PCIe/SATA/CAN/RS-485), cross-domain signals (voltage equivalence), BOM optimization, test coverage, assembly complexity, USB compliance
- **Quality checks**: annotation completeness, label validation, PWR_FLAG audit, footprint filter validation, sourcing audit, property pattern audit, generic transistor symbol detection (flags Q_NPN_*/Q_PNP_*/Q_NMOS_*/Q_PMOS_* symbols with datasheet availability check)
- **Structural**: MCU alternate pin summary, ground domain classification, bus topology, wire geometry, spatial clustering, pin coverage, hierarchical label validation

Supports modern `.kicad_sch` (KiCad 6+) and legacy `.sch` (KiCad 4/5). Hierarchical designs parsed recursively.

**Legacy format:** For KiCad 5 legacy `.sch` files, the analyzer parses `.lib` files (cache libraries and project libs) to populate pin data. Pin-to-net mapping, signal analysis, and subcircuit detection all work when `.lib` files are available. Coverage is typically 92–100% — components whose `.lib` files are missing (standard KiCad system libs not in the repo) will lack pin data. Built-in fallbacks cover 40+ common symbols (R, C, L, D, LED, transistors, MOSFETs, crystals, switches, polarized caps, connectors up to 20-pin, resistor packs) with mil-based pin offsets and automatic wire-snap correction for version-mismatched pin positions.

### Supplementary Data for Legacy Designs

When `kcd analyze sch` returns incomplete data (components with missing pins due to unavailable `.lib` files), use additional project files to recover full analysis capability. The most valuable source is the `.net` netlist file, which provides explicit pin-to-net mapping that closes any remaining gaps.

For detailed parsing instructions, data recovery workflows, and a priority matrix of supplementary sources (netlist, cache library, PCB cross-reference, PDF exports), read `references/supplementary-data-sources.md`.

**Verify analyzer output against reality.** The analyzer can silently produce plausible-looking but incorrect results — wrong voltage estimates, missing MPNs, wrong pin-to-net mappings. These don't cause script errors; they just produce bad data that flows into your report. In testing across multiple boards, every project had at least one misleading analyzer output. Cross-reference against the raw `.kicad_sch` file:

1. **Component count** — grep for `(symbol (lib_id` blocks, subtract power symbols. Must match analyzer count exactly.
2. **Pin-to-net mapping** — verify the analyzer's pin-to-net mapping against the raw schematic for each component. Read the symbol block, trace wires/labels to confirm connections. Cross-reference IC pin assignments against the manufacturer's datasheet pin table. This is the highest-value verification step — a wrong pin mapping produces a non-functional board and is invisible to DRC/ERC.
3. **Physical correctness (not just consistency)** — consistency checks (schematic=PCB=analyzer all agree) are necessary but not sufficient. They only confirm the design is internally coherent — not that it matches the real-world part. The most dangerous case: a transistor symbol encodes a pinout assumption (like `Q_NPN_BEC` = pin 1=B, 2=E, 3=C) that doesn't match the actual part. Everything passes consistency checks, but the board is wrong. To catch this:
   - For transistors (BJT/MOSFET) in SOT-23, SOT-223, TO-252 and similar packages, the KiCad `lib_id` suffix encodes a pin ordering assumption. SOT-23 BJTs exist in at least 6 pinout variants (BEC, BCE, EBC, ECB, CBE, CEB); SOT-23 MOSFETs in GDS, GSD, SGD, DSG. If no MPN is specified, there's no way to verify the assumption — flag this as a critical ambiguity.
   - When an MPN is specified, verify the symbol's pin-to-pad assignment against the datasheet's pinout diagram for that specific package.
   - This principle extends beyond transistors — any component where multiple pin orderings exist for the same package (voltage regulators with different pin assignments, connectors with vendor-specific pinouts) needs MPN-level verification.
   - **When verification isn't possible, assess plausibility.** Not all unverified choices carry equal risk. Some align with strong conventions (the most common SOT-23 NPN pinout is BCE; 2N2222 in SOT-23 is almost always BCE); others go against convention or are genuinely ambiguous (SOT-23 MOSFETs have no dominant standard). When an MPN is missing and you can't verify, use domain knowledge — typical pinouts for that device type and package, manufacturer conventions, what the majority of parts in that category do — to assess whether the assumed pinout is likely correct, unusual, or a coin flip. Report the confidence level: "matches the most common convention" is different from "could go either way." This same reasoning applies to passive values (is 4.7kΩ a typical pull-up value for this bus?), circuit topologies (is this a standard application circuit?), and component selection (is this part commonly used for this purpose?).
4. **Net trace** — trace power rails and critical signal nets end-to-end through wires/labels. Verify the analyzer's pin list is complete for each net.
5. **Regulator Vout** — check the `vref_source` field. `"lookup"` means datasheet-verified (~60 families); `"heuristic"` means it's a guess that needs manual verification. The `vout_net_mismatch` field flags estimated Vout differing >15% from the output rail name voltage.
6. **Hierarchical connectivity** — on multi-sheet designs, verify sub-sheet connections are reflected in the net data.

See `references/schematic-analysis.md` Step 2 for the full verification checklist. If the script fails or returns unexpected results, see `references/manual-schematic-parsing.md` for the complete fallback methodology.

### PCB Layout Analyzer
```bash
kcd analyze pcb <project> --json
kcd analyze pcb <project> --full --json   # deep pass: track/via coords, impedance, return paths
```
Outputs structured JSON (~50-300KB depending on board complexity) with:
- **Core**: footprint inventory (pads, courtyards, net assignments, extended attrs, schematic cross-reference), track/via statistics, zone summaries, board outline/dimensions, routing completeness
- **Zones & copper presence**: zone outline vs filled polygon bounding boxes, fill ratio, cross-layer copper presence at every pad (which components have zone copper on the opposite layer and which don't), same-layer foreign zone detection
- **Via analysis**: type breakdown (through/blind/micro), annular ring checks, via-in-pad detection, BGA/QFN fanout patterns, current capacity, stitching via identification, tenting
- **Signal integrity**: per-net trace length, layer transition tracking (ground return paths), trace proximity/crosstalk (with `--proximity`)
- **Power & thermal**: current capacity per net, power net routing summary, ground domain identification (AGND/DGND), zone stitching via density, thermal pad detection and via counting
- **Manufacturing**: placement analysis (courtyard overlaps, edge clearance), decoupling cap distances, DFM scoring (JLCPCB standard/advanced tier), tombstoning risk (0201/0402 thermal asymmetry), thermal pad via adequacy, silkscreen documentation audit

Add `--full` to include individual track/via coordinates, per-segment trace impedance (microstrip Z0 from stackup), pad-to-pad routed distances, return path continuity analysis, and via stub lengths. The `--full` output feeds the `spice` skill's parasitic extraction (`extract_parasitics.py`) for PCB-aware simulation. Supports KiCad 5 legacy format.

**Zone fills must be current.** The copper presence analysis uses KiCad's filled polygon data, which is computed when the user runs Edit → Fill All Zones (shortcut `B`) and stored in the `.kicad_pcb` file. If the board was modified after the last fill, the filled polygon data may be stale and the copper presence results will be inaccurate. When reviewing copper presence data, note whether the `fill_ratio` seems reasonable — a zone with 0 filled area or `is_filled: false` likely hasn't been filled.

**Zone outline ≠ actual copper.** The zone `outline_bbox` is the user-drawn boundary; `filled_bbox` is where copper actually exists after clearances, keepouts, and priority cuts. The `copper_presence` section shows which components have zone copper on the opposite layer — use this for capacitive touch pad isolation, antenna keep-out, and thermal analysis instead of inferring copper presence from zone outlines.

**Copper-sensitive components need deeper checks.** For capacitive touch pads and antennas, confirming "no opposite-layer copper" is necessary but not sufficient. The copper absence could be accidental — one zone refill after a routing change could add copper and kill touch sensitivity or detune the antenna. Check for explicit **keepout zones** (rule areas) that enforce the copper-free area as a DRC rule. Also measure same-layer GND clearance around touch pads and compare against the controller's app note minimum. For touch pads, compare trace lengths across all pads — significant asymmetry shifts baseline readings per channel. Report physical details (pad size, position, clearance, trace width/length) for all copper-sensitive components. See `references/pcb-layout-analysis.md` → Copper-Sensitive Components for the full checklist.

**Verify after every run:** Confirm footprint count and board outline dimensions against the raw `.kicad_pcb` file. Verify pad-to-net assignments for IC footprints against the schematic's pin-to-net mapping — this catches library footprint errors where pad numbering doesn't match the symbol pinout. If the script fails, see `references/manual-pcb-parsing.md` for the fallback methodology.

### PCB Rich Format and Assembly Checks

All PCB analysis sections now produce findings with the rich format (detector, rule_id, category, severity, confidence, summary, recommendation, report_context). Additionally, 7 new assembly/DFM checks run automatically:

- **FD-001**: Fiducial marker presence (>= 3 per SMD side)
- **TE-001**: Test point coverage across signal nets
- **OR-001**: Passive component orientation consistency
- **SK-001**: Silkscreen text overlapping exposed pads
- **VP-001**: Via-in-pad without tenting (--full mode)
- **BV-001**: Via clearance from board edges (--full mode)
- **KO-001**: Keepout zone violations
- **CP-001**: Same-layer foreign zone under a component. Severity is `warning` when the foreign zone is a non-ground net or the component has no GND pad; severity is `info` when the foreign zone is GND and the component has a GND pad (the common case of a bypass cap sitting over the ground pour — expected layout, not a clearance issue).

### Cross-Domain Analysis

```bash
kcd analyze cross <project> --json
```

Runs the schematic and PCB analyzers internally, then cross-checks them.
Checks: CC-001 connector current capacity, EG-001 ESD protection gaps,
DA-001 decoupling adequacy, XV-001..003 schematic/PCB sync.

### Connectivity Graph (--full mode)

When `--full` is used with `kcd analyze pcb`, the output includes a `connectivity_graph` section with per-net copper connectivity analysis via union-find over pads, tracks, vias, and zone fills. This enables deterministic plane split detection and return path validation in the cross-domain analyzer. Each net entry shows island count, component-to-island mapping, gap locations, and disconnected pad pairs.

### Gerber & Drill Analyzer
```bash
kcd analyze gerbers <gerber_directory/> --json
kcd analyze gerbers <gerber_directory/> --out custom-path.json --json
```
Outputs: layer identification (X2 attributes), component/net/pin mapping (KiCad 6+ TO attributes), aperture function classification, trace width distribution, board dimensions, drill classification (via/component/mounting), layer completeness, alignment verification, pad type summary (SMD/THT ratio). Add `--full` for complete pin-to-net connectivity dump. ~10KB JSON.

The gerber analyzer produces a `findings` list with rich format findings: GR-001 missing layers, GR-002 alignment issues, GR-003 drill problems, GR-004 paste aperture mismatches, GR-005 open board outlines.

If the script fails or returns unexpected results, see `references/manual-gerber-parsing.md` for the complete fallback methodology for parsing raw Gerber/Excellon files directly.

**Artifacts.** Every `kcd analyze` command saves the raw analyzer JSON to
`$KCD_RENDER_CACHE/<name>-analyze-<verb>.json` and registers it as an
envelope artifact, so a re-read is cheap and `kcd analyze diff` can compare
two runs. Pass `--out <path>` to write the JSON somewhere specific. These
files are expensive to regenerate (large schematics take time) — keep them
around during a review session; they're not worth committing to git.

### Harmonized Output Format

All analyzers produce a uniform output envelope:

```json
{
    "analyzer_type": "schematic|pcb|emc|cross_analysis|thermal|gerber|lifecycle|spice",
    "schema_version": "1.3.0",
    "summary": {
        "total_findings": 42,
        "by_severity": {"error": 3, "warning": 15, "info": 24}
    },
    "findings": [
        {"rule_id": "...", "detector": "...", "severity": "...", "confidence": "...", "evidence_source": "...", "summary": "...", ...}
    ],
    "trust_summary": {
        "total_findings": 42,
        "trust_level": "high|mixed|low",
        "by_confidence": {"deterministic": 20, "heuristic": 18, "datasheet-backed": 4},
        "by_evidence_source": {"datasheet": 4, "topology": 10, "heuristic_rule": 18, ...},
        "provenance_coverage_pct": 96.5
    }
}
```

The `findings` list is the single authoritative source for all findings.
Filter `data.findings` by `rule_id` prefix, `detector`, or `severity`
yourself. Severities are `error`, `warning`, or `info`; confidence is
`deterministic`, `heuristic`, or `datasheet-backed`. (`kcd analyze` already
lifts `warning`/`error`/`critical` findings into the envelope `warnings[]`.)

### Comparing Runs

To see what changed between two design revisions, save each analyzer run with
`--out` and diff them:

```bash
kcd analyze sch <project> --out base.json --json
# ... revise the design ...
kcd analyze sch <project> --out head.json --json
kcd analyze diff base.json head.json --json
```

`kcd analyze diff` auto-detects the analyzer type and reports component,
signal, BOM, connectivity, and finding deltas with a severity classification
(`none` / `minor` / `major` / `breaking`).

### Output JSON Schema Quick Reference

**Schematic analyzer top-level keys:**
```
analyzer_type, schema_version, summary, findings, trust_summary,
file, kicad_version, file_version, title_block, statistics,
bom, components, nets, subcircuits, ic_pin_analysis, design_analysis,
connectivity_issues, hierarchy_context, hierarchy_warning,
net_classifications, rail_voltages
```
Optional (present when non-empty): `pdn_impedance`, `sleep_current_audit`, `voltage_derating`, `power_budget`, `power_sequencing`, `bom_optimization`, `test_coverage`, `assembly_complexity`, `usb_compliance`, `inrush_analysis`, `sheets` (multi-sheet only), `missing_info`, `bom_lock`, `project_settings`

Key nested structures:
- `statistics`: `{total_components, unique_parts, dnp_parts, total_nets, total_wires, total_no_connects, component_types, power_rails, missing_mpn, ...}`
- `bom[]`: `{reference, references[], value, footprint, mpn, manufacturer, datasheet, quantity, dnp, ...}`
- `components[]`: `{reference, value, footprint, lib_id, lib_name, type, category, mpn, datasheet, dnp, in_bom, parsed_value, ...}`
- `nets{net_name}`: `{pins[], wires, labels[], ...}` — each pin: `{component, pin_number, pin_name, pin_type, ...}` (NOT `ref` or `pin`)
- `subcircuits[]`: IC-neighborhood groupings (`{center_ic, ic_value, neighbor_components, ...}`), NOT a categorized detection index — see the JSON field cheat sheet at the top of this file.
- **Detected subcircuits live in `findings[]`** — power regulators, voltage dividers, RC/LC filters, feedback networks, opamp/transistor/bridge/crystal circuits, current sense, decoupling, protection, buzzer/speaker, Ethernet/HDMI/memory interfaces, RF chains/matching, BMS, key matrices, isolation barriers, addressable LED chains, and design observations all emit as findings with matching `Det.*` detectors. Use `get_findings(data, Det.POWER_REGULATORS)` etc. to fetch them. The pre-v1.3 `signal_analysis` wrapper and its top-level detection lists are gone.

**PCB analyzer top-level keys:**
```
analyzer_type, schema_version, summary, findings, trust_summary,
file, kicad_version, file_version, statistics, layers, setup,
nets, net_name_to_id, board_outline, component_groups, footprints,
tracks, vias, zones, keepout_zones, connectivity, net_lengths
```
Optional: `power_net_routing`, `decoupling_placement`, `ground_domains`, `layer_transitions`, `silkscreen`, `board_metadata`, `dimensions`, `groups`, `net_classes`, `dfm_summary`, `placement_density`, `copper_presence_summary`, `board_thickness_mm`, `trace_proximity` (with `--proximity`). Sections previously at top level (`thermal_analysis`, `thermal_pad_vias`, `tombstoning_risk`, `placement_analysis`, `current_capacity`, `copper_presence`, `dfm`) are now in `findings[]`. With `--full`, the output also includes a `connectivity_graph` section (see "Connectivity Graph" above).

Key nested structures:
- `net_lengths` is a **list** (not dict): `[{net, net_number, total_length_mm, segment_count, via_count, layers{}}, ...]` sorted by length descending
- `power_net_routing` is a **list**: `[{net, track_count, total_length_mm, min_width_mm, max_width_mm, widths_used[]}, ...]`
- `footprints[]`: `{reference, value, footprint, layer, pads[], sch_path, sch_sheetname, sch_sheetfile, connected_nets[], ...}`
- `statistics`: `{footprint_count, copper_layers_used, smd_count, tht_count, zone_count, via_count, routing_complete, ...}`

**Gerber analyzer top-level keys:**
```
analyzer_type, schema_version, summary, findings, trust_summary,
directory, generator, layer_count, statistics, completeness, alignment,
drill_classification, pad_summary, board_dimensions, gerbers, drills
```

**Workflow:** When analyzing a KiCad project, scan the project directory for all available file types and run **every applicable analyzer** — not just the one the user mentioned. A complete analysis uses all the data available.

**Before starting the workflow below for a design review:** read `references/report-generation.md`. The report structure, verification basis rules, skipped-analysis disclosure, and false-positive triage expectations there are part of the review workflow, not optional polish added at the end.

1. **Scan the project directory** for `.kicad_sch`, `.kicad_pcb`, `.kicad_pro`, gerber directories, and `.net`/`.xml` netlist files.
2. **Sync datasheets** (see Datasheet Acquisition below) — this is a prerequisite for verification, not optional. Without datasheets, all subsequent verification is reduced to internal consistency checks — confirming the design agrees with itself, not that it's correct. Run the sync before reading any analyzer output. If sync fails or no API keys are available, use fallback methods (Datasheet property URLs, individual downloads via `digikey` skill, ask the user). If critical IC datasheets can't be obtained, note this prominently in the report as a verification gap.
3. **Run the core analyzers.** If the schematic exists, run `kcd analyze sch`. If the PCB exists, run `kcd analyze pcb --full`. If gerbers exist, run `kcd analyze gerbers`.
4. **Run cross-domain analysis** — when both schematic and PCB exist, run `kcd analyze cross`. This catches dangerous cross-domain bugs (connector current vs trace width, ESD gaps, decoupling adequacy, schematic/PCB sync).
5. **Run EMC pre-compliance** — when both schematic and PCB exist, hand off to the `emc` skill. This is **required** during design reviews, not optional. The EMC skill runs 44 rule checks covering ground plane integrity, decoupling, switching harmonics, PDN impedance, diff pair skew, ESD paths, and more. Include results in the EMC section of the report.
6. **Run SPICE simulation** — first run `which ngspice ltspice xyce`. If any simulator is installed, SPICE is **required** before writing the report. Hand off to the `spice` skill with the schematic analysis JSON. This validates filter frequencies, divider ratios, opamp gains, and more against actual simulation results. SPICE takes <1 second on most boards and catches value-computation errors (wrong resistor ratio, wrong cap for cutoff frequency) that no static analyzer finds. If both schematic and PCB analysis exist, use `--parasitics` for high-impedance circuits (>100K feedback dividers, LC filters, RF matching networks). Include results in the Simulation Verification section of the report. **Output schema:** top-level keys are `summary`, `simulation_results`, `workdir`, `total_elapsed_s`, `simulator`. Each entry in `simulation_results[]` has: `subcircuit_type`, `components` (list of refs, e.g. `["R5", "C3"]`), `reference` (joined refs, e.g. `"R5/C3"`), `status` (`pass`/`warn`/`fail`/`skip`), `expected` (dict of metric values), `simulated` (dict of measured values), `delta` (dict of error percentages).
7. **Run thermal analysis** — when both schematic and PCB exist, run `kcd analyze thermal`. Estimates junction temperatures from package θJA and board thermal via correction. Include results in the Thermal Hotspot section of the report.
8. **Run lifecycle audit** (when network access and MPNs are available) — run `kcd analyze lifecycle`. Checks component obsolescence status via distributor APIs. Include results in the Component Lifecycle section of the report, or note "Lifecycle audit not performed — [reason: no API keys / no network / no MPNs]."
9. **Read the `.kicad_pro`** project file directly (it's JSON) for design rules, net classes, and DRC/ERC settings.
10. **Check for prior design reviews** — scan the project directory for existing review files (`*review*.md`, `*design-review*.md`). If found, read the most recent one. If a prior analyzer JSON is available, run `kcd analyze diff` on current vs previous and include the delta in the "Previous Review Delta" section.
11. **Verify each output** against the raw files and datasheets before using the data in your report.
12. **Produce a unified report** covering schematic analysis, PCB layout analysis, cross-domain findings, EMC risk assessment, simulation verification, thermal hotspots, and cross-reference findings. See `references/report-generation.md` for the report template.
13. **Disclose all review gaps explicitly** — if thermal, lifecycle, gerber, datasheet extraction, or prior-review delta were not performed, add a short "Not performed / limits" section to the report instead of omitting them silently.

The more data sources you combine, the more confident the analysis. A schematic-only review misses layout issues; a PCB-only review misses design intent. Always use everything available.

### Analysis Depth

Default to thorough analysis unless the user asks for a quick review. The reason: the bugs that kill boards are the ones that look correct at a glance. A spot-check might confirm 5 ICs are correct while the 6th has pins 3 and 4 swapped — and that's the one that kills the board. Thoroughness principles:

- **Verify all components, not a sample.** Pin-to-net errors on "simple" parts (reversed diode, wrong resistor in a divider, connector with wrong pin ordering) are just as fatal as swapped IC pins. Cover the full design.
- **Use datasheets as ground truth — not KiCad library symbols.** The analyzer, raw schematic, and KiCad library files all tell you what the design *says* — only the manufacturer's PDF datasheet tells you what it *should* say. A library symbol with a wrong pin mapping is the most dangerous class of bug precisely because everything is internally consistent: schematic, PCB, and analyzer all agree, but the board doesn't work. Verifying a pin assignment against the `.kicad_sym` file is circular — it's the source of the potential error. Download datasheets before starting verification (see "Datasheet Acquisition" below), open the actual PDF for each IC, extract the pin function table, and cite page/section numbers when reporting verification results.
- **Assess plausibility, not just verifiability.** When something can't be verified (missing MPN, missing datasheet), don't stop at "unverified." Use domain knowledge to assess whether the design choice aligns with common conventions or looks unusual. A 10kΩ I2C pull-up is unremarkable; a 100Ω I2C pull-up warrants a closer look even without a datasheet to check against. An SOT-23 NPN with BCE pinout matches the most common convention; one with CEB is unusual enough to flag. The goal is to distinguish "unverified but probably fine" from "unverified and suspicious." This applies to pinouts, passive values, circuit topologies, and component selection.
- **Think beyond what the analyzer detects.** The analyzer only finds patterns it's programmed for. When a section has no automated data, consider whether that's because the design doesn't need it (fine — say so briefly) or because the analyzer can't detect it (reason about it manually). Not every section needs a paragraph — "Not applicable: battery-powered, no mains input" is sufficient. But don't let empty data create blind spots in areas that matter for the specific design.

### Datasheet Acquisition

Datasheets are what separate a consistency check from a correctness check. Without them, you can confirm the design agrees with itself — but not that it matches the real-world parts. Obtain datasheets early in the workflow.

**Automated sync (preferred):** Hand off to a distributor skill early in the
workflow to download datasheets for all components with MPNs into a shared
`datasheets/` directory. Try the preferred source first; if some parts fail,
try others — they share the same directory and skip already-downloaded files.

Source priority: **`digikey`** (best — direct PDF URLs), **`element14`**
(reliable — no bot protection), **`lcsc`** (LCSC-only parts), **`mouser`**
(last resort — often blocks downloads).

**Check for existing datasheets:** Before downloading, look for:
- `<project>/datasheets/` with `manifest.json` (from a previous sync)
- `<project>/docs/` or `<project>/documentation/`
- PDF files in the project directory whose names contain MPNs
- `Datasheet` property URLs embedded in the KiCad symbols

**Fallback methods when automated sync isn't available or misses parts:**
1. Use the `Datasheet` property URL from the schematic symbol — many KiCad libraries include direct PDF links
2. Use the `digikey` skill to search by MPN and download individual datasheets
3. Use web search to find the manufacturer's datasheet page
4. **Ask the user** — if a critical component's datasheet can't be found automatically, tell the user which parts are missing and ask them to provide the datasheets. Don't silently skip verification because a datasheet wasn't available. Example: "I couldn't find datasheets for U3 (XYZ1234) and U7 (ABC5678). Can you provide them? I need them to verify the pinout and application circuit."

**Structured datasheet extraction (for large designs or repeated reviews):** Pre-extract datasheet specs into cached JSON for faster, more consistent pin verification. This is especially valuable for designs with 10+ ICs where re-reading PDFs from scratch each time is slow. The **`datasheets` skill** owns this pipeline — hand off to it for page selection, extraction, and caching.

After reading the selected pages and producing an extraction JSON, score and cache it using `datasheet_score` and `datasheet_extract_cache` modules. Extractions are stored in `datasheets/extracted/<MPN>.json` and reused across reviews. The **`datasheets` skill** owns the full extraction pipeline (schema, page selection, scoring rubric, consumer API) — see `skills/datasheets/SKILL.md` and its reference guides.

**What to extract from each datasheet** (note page/section/figure/equation numbers for citations):
- Pin function table (pin number → name → function)
- Absolute maximum ratings (voltage, current, temperature — including max continuous current through VCC/GND pins, which constrains inrush)
- Recommended application circuit and required external components
- Required component values (and the equations that derive them)
- Thermal characteristics

**For passives:** While individual resistor/capacitor datasheets are rarely needed, verify the component values against the IC datasheets that specify them. The IC's datasheet says "use a 10µF input cap" — verify the schematic actually has 10µF there, not 1µF.

**Anti-pattern: verification without datasheets.** The most common failure mode in design review is verifying component connections against KiCad library symbols instead of manufacturer datasheets. This is circular — if the library symbol has a wrong pin mapping, the schematic, PCB, and analyzer output will all agree with each other (and with the wrong pinout). Only the datasheet reveals the error. This is especially dangerous for custom/community library symbols (e.g., `sacmap:TPS61023`) where there's no upstream KiCad library as a secondary check. If you find yourself verifying a pinout by reading the `.kicad_sym` file or the analyzer's pin data and confirming it matches the schematic — stop. That's a consistency check, not a correctness check. Open the actual PDF datasheet, find the pin function table, and verify against that. Cite the datasheet page/section/figure number in your report so the designer can confirm your work.

### Schematic + PCB Cross-Reference

When both files exist, cross-reference them. This catches the most expensive bugs — swapped pins, missing nets, and footprint mismatches pass DRC/ERC but produce non-functional boards.

1. **Component count**: Schematic count (excluding power symbols) vs PCB footprint count.
2. **Net consistency**: Verify schematic net names appear in PCB net declarations. Missing nets suggest incomplete routing or un-synced changes.
3. **Pin-net assignments**: Compare schematic pin-to-net mapping against PCB pad-to-net mapping. Mismatches reveal swapped pins or library errors. Higher-risk areas:
   - Custom/community library symbols (may not match datasheet pinout)
   - Multi-unit symbols (op-amps, gate arrays) — unit-to-pin assignment errors
   - QFN/BGA packages — pad numbering mistakes
   - Transistors without MPNs — pinout ambiguity (see verification step 3)
   - Polarized components — anode/cathode orientation
   - Connectors — pin 1 orientation
4. **Footprint match**: Schematic `Footprint` property vs actual PCB footprint (e.g., SOT-23 vs SOT-23-5).
5. **DNP consistency**: DNP components in schematic should not have routing on PCB.
6. **Value/MPN consistency**: Values and MPNs match between schematic and PCB properties.

The PCB analyzer's `sch_path`, `sch_sheetname`, and `sch_sheetfile` fields in each footprint enable automated cross-referencing.

### Diff-Aware Design Comparison

Compare two analysis JSON outputs to see what changed between design revisions (e.g., base branch vs PR, v1 vs v2). Use when the user says things like "compare designs", "what changed", "diff my schematic", "show changes from main", or "diff base vs head". Full reference: `references/diff-analysis.md`.

```bash
# Save each analyzer run with --out, then diff the two JSON files
kcd analyze sch <project> --out base.json --json
kcd analyze sch <project> --out head.json --json
kcd analyze diff base.json head.json --json
```

Auto-detects analyzer type (schematic, PCB, EMC, SPICE). Reports:
- **Components**: new, removed, value/footprint/MPN changes
- **Signal analysis**: parameter shifts per detection type, driven by `detection_schema.SCHEMAS` identity and value fields
- **BOM**: added/removed line items, quantity changes
- **Connectivity/ERC**: new/resolved single-pin nets, floating nets, multi-driver nets, ERC warnings
- **EMC findings**: new/resolved findings with severity, risk score delta, per-net score changes
- **SPICE results**: status transitions (pass->fail regressions, fail->pass fixes), Monte Carlo concern changes
- **Severity classification**: `none` (no changes), `minor` (statistics only), `major` (component/signal/finding changes), `breaking` (SPICE regressions, new CRITICAL EMC findings, new ERC warnings)

### Thermal Hotspot Estimation

Estimates junction temperatures of power-dissipating components by combining schematic power data with PCB thermal infrastructure (copper pour, thermal vias, package type). Use when the user says "check thermals", "thermal analysis", "will this overheat", "junction temperature", "power dissipation", or "thermal design".

```bash
kcd analyze thermal <project> --json
kcd analyze thermal <project> --ambient 40 --json   # custom ambient (default 25 deg C)
```

Models each power component (LDO, switching regulator, shunt resistor) as a point heat source. Computes Tj = T_ambient + P_diss × Rθ_JA_effective, where Rθ_JA comes from a package lookup table (SOT-223: 60°C/W, QFN-5x5: 25°C/W, etc.) and is corrected for PCB thermal vias and copper pour. Rules:

| Rule | Condition | Severity |
|------|-----------|----------|
| TS-001 | Tj exceeds absolute maximum | CRITICAL |
| TS-002 | Tj within 15°C of absolute maximum | HIGH |
| TS-003 | Tj > 85°C (may affect nearby passives) | MEDIUM |
| TS-004 | P > 0.5W with no thermal vias | MEDIUM |
| TS-005 | Significant power, within safe limits | INFO |
| TP-001 | MLCC within 10mm of hot component | LOW |
| TP-002 | Electrolytic cap within 10mm of hot component | MEDIUM |

Thermal findings and assessments include the rich format envelope (detector, rule_id, summary, evidence_source, report_context). Rule IDs: TS-001..005 (safety), TP-001..002 (proximity), TH-DET (assessments).

### Interactive "What-If" Parameter Sweep

Instantly see the impact of component value changes on circuit behavior without re-running the full analyzer. Use when the user says "what if I change", "what happens if", "try a different value", "swap R5 to 4.7k", "parameter sweep", "what value gives me X", or wants to explore design trade-offs. Full reference: [`references/what-if.md`](references/what-if.md).

```bash
# Single value change
kcd analyze whatif <project> R5=4.7k --json

# Sweep: comma list or log range
kcd analyze whatif <project> R5=1k,2.2k,4.7k,10k --json
kcd analyze whatif <project> R5=1k..100k:10 --json

# Tolerance corner analysis (worst-case)
kcd analyze whatif <project> R5=4.7k+-5% C3=100n+-10% --json

# Suggest component-value fixes (feedback dividers, RC filters, crystal caps)
kcd analyze whatif <project> --suggest-fixes --json
```

Patches component values, recalculates derived fields (filter cutoff, divider ratio, opamp gain, crystal load, current sense range, regulator Vout), and shows before/after comparison with percentage deltas. Pass at least one `REF=VALUE` change or `--suggest-fixes`. Supports single changes, multi-point sweeps (comma or log-range), tolerance corner analysis, and inverse fix suggestions with E-series snapping.

### Component Lifecycle & Temperature Audit

Queries distributor APIs to check component lifecycle status (active, NRND, EOL, obsolete) and operating temperature range coverage. Use when the user says "check for obsolete parts", "lifecycle audit", "are any parts end of life", "temperature audit", "will this work at industrial temp range", or during production readiness reviews.

```bash
# Basic lifecycle check
kcd analyze lifecycle <project> --json

# With temperature range validation (preset or custom)
kcd analyze lifecycle <project> --temp-range industrial --json
kcd analyze lifecycle <project> --temp-range "-40,105" --json
```

Reads the analyzer JSON BOM section, extracts unique MPNs, queries distributors (LCSC no-auth, DigiKey, element14, Mouser) for lifecycle status and operating temperature. Temperature presets: `commercial` (0/70°C), `industrial` (-40/85°C), `extended` (-40/105°C), `automotive` (-40/125°C), `military` (-55/125°C). Also checks datasheet extraction cache for temperature data before making API calls.

The lifecycle audit produces rich format findings: LC-001 (obsolete/discontinued), LC-002 (last time buy), LC-003 (NRND), LC-004 (unknown status), LC-005 (single source), LC-006 (long lead time), LT-001 (temperature violation).

**Requires network access** — unlike the core analyzers, this script calls distributor APIs. Same environment variables as the distributor skills (DIGIKEY_CLIENT_ID/SECRET, MOUSER_SEARCH_API_KEY, ELEMENT14_API_KEY). LCSC requires no credentials.

### Schematic Analyzer Rule IDs

All schematic rule findings appear in `findings[]`. The following rule IDs are produced by the schematic analyzer:

| Rule | Detector | Condition | Severity |
|------|----------|-----------|----------|
| SS-001 | `audit_sourcing_gate` | MPN coverage < 50% | high |
| SS-002 | `audit_sourcing_gate` | MPN coverage 50–80% | warning |
| SS-003 | `audit_sourcing_gate` | MPN coverage 80–100% | info |
| NT-001 | `analyze_connectivity` | Single-pin net: signal pin | warning |
| NT-001 | `analyze_connectivity` | Single-pin net: power_out or passive pin | info |
| RS-001 | `audit_rail_sources` | Rail has a declared source (direct, PWR_FLAG, or bridged jumper) | info or warning |
| RS-002 | `audit_rail_sources` | Rail depends on user closing an open jumper | high |
| LB-001 | `detect_label_aliases` | Net has >= 2 distinct global/hierarchical labels (power nets excluded) | info |
| PP-001 | `audit_power_pin_dc_paths` | IC power_in pin reaches a rail only through a capacitor (2-hop BFS) | high |

SS-001 is a pre-fab blocker — a `high` finding that should be resolved before ordering. NT-001 severity depends on pin type: signal pins (digital I/O, bidirectional) are `warning`; power_out and passive pins are `info`. RS-001 severity varies by confidence level in the detected source. PP-001 uses a 2-hop BFS over the net graph, rejecting capacitor edges, to confirm a direct DC path from a power rail to each IC power_in pin.

## Reference Files

Detailed methodology and format documentation lives in reference files. Read these as needed — they provide deep-dive content beyond what the scripts output automatically.

| Reference | Lines | When to Read |
|-----------|-------|-------------|
| `schematic-analysis.md` | 1133 | Deep schematic review: datasheet validation, design patterns, error taxonomy, tolerance stacking, GPIO audit, motor control, battery life, supply chain |
| `pcb-layout-analysis.md` | 447 | Advanced PCB: impedance calculations, differential pairs, return paths, copper balance, edge clearance, copper-sensitive components (capacitive touch, antennas), custom analysis scripts |
| `output-schema.md` | 293 | Full analyzer JSON schema with field names, types, and common extraction patterns |
| `file-formats.md` | 379 | Manual file inspection: S-expression structure, field-by-field docs for all KiCad file types, version detection |
| `gerber-parsing.md` | 729 | Gerber/Excellon format details, X2 attributes, analysis techniques |
| `pdf-schematic-extraction.md` | 315 | PDF schematic analysis: extraction workflow, notation conventions, KiCad translation |
| `supplementary-data-sources.md` | 288 | Legacy KiCad 5 data recovery: netlist parsing, cache library, PCB cross-reference |
| `net-tracing.md` | 120 | Manual net tracing: coordinate math, Y-axis inversion, rotation transforms |
| `manual-schematic-parsing.md` | 289 | Fallback when schematic script fails |
| `manual-pcb-parsing.md` | 467 | Fallback when PCB script fails |
| `manual-gerber-parsing.md` | 621 | Fallback when Gerber script fails |
| `report-generation.md` | 614 | Report template (critical findings at top), analyzer output field reference (schematic/PCB/gerber), severity definitions, writing principles, domain-specific focus areas, known analyzer limitations |
| `standards-compliance.md` | 638 | IPC/IEC standards tables: conductor spacing (IPC-2221A Table 6-1), current capacity (IPC-2221A/IPC-2152), annular rings, hole sizes, impedance, via protection (IPC-4761), creepage/clearance (ECMA-287/IEC 60664-1). Consider for all boards; auto-trigger for professional/industrial designs, high voltage, mains input, or safety isolation. |
| `design-intent.md` | — | Design intent resolution, target market / certification / power constraints that gate findings by context |
| `diff-analysis.md` | — | How `kcd analyze diff` compares two analyzer runs and emits severity-ranked change reports |
| `what-if.md` | — | How `kcd analyze whatif` patches component values, recalculates derived fields, and suggests fixes for feedback dividers / crystal load caps / cap derating |
| `config-reference.md` | — | `.kicad-happy.json` schema — project config for suppressions, design intent, risk scoring |
| `datasheet-verification.md` | — | Automated cross-check of schematic connections against structured datasheet extractions (pin voltage, required externals, decoupling adequacy) |

For the analyzer engine's internals (data structures, signal-analysis patterns, detector libraries), see `src/kcd/analyzers/README.md` in the kcd repo.

## File Types Quick Reference

| Extension | Format | Purpose |
|---|---|---|
| `.kicad_pro` | JSON | Project settings, net classes, DRC/ERC severity, BOM fields |
| `.kicad_sch` | S-expr | Schematic sheet (symbols, wires, labels, hierarchy) |
| `.kicad_pcb` | S-expr | PCB layout (footprints, tracks, vias, zones, board outline) |
| `.kicad_sym` | S-expr | Symbol library (schematic symbols with pins, graphics) |
| `.kicad_mod` | S-expr | Single footprint (in `.pretty/` directory) |
| `.kicad_dru` | Custom | Custom design rules (DRC constraints) |
| `fp-lib-table` / `sym-lib-table` | S-expr | Library path tables |
| `.sch` / `.lib` / `.dcm` | Legacy | KiCad 5 schematic, symbol library, descriptions |
| `.net` / `.xml` | S-expr/XML | Netlist export, BOM export |
| `.gbr` / `.g*` / `.drl` | Gerber/Excellon | Manufacturing files (copper, mask, silk, outline, drill) |

For version detection and detailed field-by-field format documentation, read `references/file-formats.md`.

## Analysis Strategies

### Deep Schematic Analysis

For a thorough datasheet-driven schematic review — identifying subcircuits, fetching datasheets, validating component values against manufacturer recommendations, comparing against common design patterns, detecting errors, and suggesting improvements — read `references/schematic-analysis.md`. Use this reference whenever the user asks to review, validate, or analyze a schematic in depth.

**Fetching datasheets**: When the analysis requires datasheet data, use the DigiKey API as the preferred source (see the `digikey` skill) — it returns direct PDF URLs via the `DatasheetUrl` field without web scraping. Search by MPN from the schematic's component properties. Fall back to web search only for parts not on DigiKey.

### Deep PCB Analysis

For advanced layout analysis beyond what the PCB analyzer script provides — impedance calculations from stackup parameters, DRC rule authoring, power electronics design review techniques, differential pair validation, return path analysis, copper balance assessment, board edge clearance rules, and manual script-writing patterns — read `references/pcb-layout-analysis.md`.

Most routine PCB analysis (via types, annular ring, placement, connectivity, thermal vias, current capacity, signal integrity, DFM scoring, tombstoning risk, thermal pad vias) is handled automatically by `kcd analyze pcb`. Use the reference for deeper manual investigation.

### Design Intent

For interpreting auto-detected design intent and calibrating review severity by product class and target market (hobby vs consumer vs industrial vs medical vs automotive vs aerospace), read `references/design-intent.md`. Check the `design_intent` object in analysis output to understand the design context.

### Probing Analyzer JSON

During a review you will often inspect specific corners of the analyzer output (pin-nets, rail voltages, specific finding contents, etc.) — by reading the envelope `data` field or the saved artifact JSON, and cross-checking with `kcd inspect ref` / `kcd inspect pcb` / the raw `.kicad_sch`. One practice materially improves the user's ability to follow along:

**Announce what you're checking before each probe.** One concise sentence before you look — the user should be able to read only the narrative and understand the review flow without opening every tool call.

- Good: "Checking whether U3's EN pin is tied to +BATT directly or through a divider." then the lookup.
- Good: "Verifying the detected TPS61023 topology matches the datasheet (buck-boost expected)." then the lookup.

The narrative matters most for probes that investigate *why* something looks wrong — those are the moments a user loses context fastest.

**Defensive patterns for JSON-shape uncertainty.** Analyzer output has heterogeneous shapes (lists of dicts, dicts keyed by ref, optional sections, nested paths). Scripts that assume the wrong shape crash mid-probe.

- Before slicing, check type: `x[:3]` on a dict raises `KeyError: slice(None, 3, None)`. Use `list(x.values())[:3]` or `list(x.items())[:3]` for dicts.
- Before `min()` / `max()`, check non-empty: `min([])` raises `ValueError: min() iterable argument is empty`. Use `min(items, default=None)` or guard with `if items:`.
- Use `.get("key", default)` not `["key"]` when a section may be absent (many sections are optional based on what the analyzer found).
- `isinstance(x, list)` vs `isinstance(x, dict)` — `components` is a list of dicts, `nets` is a dict keyed by net name. Check the schema reference before iterating.
- When a finding field can be a list of strings OR a list of dicts (rare but happens in legacy-shape sections), handle both: `r = c if isinstance(c, str) else c.get("reference", "")`.
- Pads/components with missing data: `pad.get("abs_x")` can be `None`; guard before arithmetic.

Small investment, much lower friction.

### Quick Review Checklists

**Schematic** — verify: decoupling caps on every IC VCC/GND pair, I2C pull-ups, reset pin circuits, unconnected pins have no-connect markers, consistent net naming across sheets, ESD protection on external connectors, power sequencing (EN/PG), adequate bulk capacitance.

**PCB** — verify: power trace widths for current (IPC-2221), via current capacity, creepage/clearance for high voltage, decoupling cap proximity to IC power pins, continuous ground plane (no splits under signals), controlled impedance traces (USB/DDR), board outline closed polygon, silkscreen readability, thermal via count for every exposed-pad IC (report the count and compare against the datasheet's recommended range — this is one of the most common QFN/DFN layout errors), keepout zone enforcement for copper-sensitive components (touch pads and antennas — confirming copper absence isn't enough because it could be accidental; check that keepout zones exist as DRC rules), differential pair length deltas with protocol-specific tolerance (compute the delta and cite the spec — raw lengths alone don't tell the designer if there's a problem), pad-to-net cross-reference at PCB level for all ICs/transistors/connectors (catches library footprint pin numbering errors that are invisible to DRC/ERC — the most dangerous class of PCB bug). Consider `references/standards-compliance.md` for IPC/IEC standard values — conductor spacing and current capacity are relevant for most boards; creepage/clearance and via protection apply to mains-connected or safety-isolated designs.

**Common bugs (ranked by board-killing potential)**: swapped IC pins (library symbol vs datasheet pinout — invisible to DRC/ERC), transistor pinout ambiguity (SOT-23 without MPN — symbol assumes a pin ordering that may not match the real part; assess plausibility against common conventions when verification isn't possible), wrong footprint pad numbering, missing nets from un-synced schematic→PCB, wrong package variant (SOT-23 vs SOT-23-5), floating digital inputs, missing bulk caps, reversed polarity, incorrect feedback divider values, wrong crystal load caps, USB impedance mismatch, QFN thermal pad missing vias, connector pinout errors, unusual passive values (a value that's technically valid but uncommon for the application — e.g., a non-standard pull-up resistance, an unusual decoupling capacitor value).

### Report Generation

When producing a design review report, read `references/report-generation.md` for the standard report template, severity definitions, writing principles, and domain-specific focus areas. The report format covers: overview, component summary, power tree, analyzer verification (spot-checks), signal/power/design analysis review, quality & manufacturing, prioritized issues table, positive findings, and known analyzer gaps. Always cross-reference analyzer output against the raw schematic before reporting findings.

### Design Comparison
When comparing two designs, diff: component counts/types, net classes/design rules, track widths/via sizes, board dimensions/layer count, power supply topology, KiCad version differences.

## Security Architecture

All analysis scripts process untrusted input (user-provided KiCad files,
third-party PDF datasheets, distributor API responses). The parsing architecture
mitigates prompt injection and code execution risks:

- **Deterministic parsers**: S-expression files (`.kicad_sch`, `.kicad_pcb`) are
  parsed by a dedicated recursive-descent parser (`sexp_parser.py`) — not
  `eval()`, `exec()`, or any code execution primitive. The parser produces
  Python lists/strings only.
- **Structured JSON boundary**: All analyzer output is structured JSON with a
  fixed schema. External content (component values, net names, datasheet text)
  is treated as data fields, never as instructions or code.
- **PDF processing**: Datasheet PDFs are processed by `pdftotext` (external
  binary, list-based args — no shell injection) and page content is passed to
  the LLM for structured extraction. Extracted data is validated against a
  5-dimension quality rubric before caching.
- **No shell commands from input**: No analyzer constructs shell commands from
  file content. Subprocess calls use list-based arguments exclusively.
- **Read-only by default**: Analysis scripts never modify input files. BOM
  write-back requires an explicit `--write` flag.
- **Distributor API scope**: Network requests are limited to known distributor
  APIs (DigiKey, Mouser, LCSC, element14) for datasheet downloads and component
  lookups. Only MPNs are sent — no design data leaves the local machine.
