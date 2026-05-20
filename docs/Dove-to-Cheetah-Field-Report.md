# kcd Toolset & KiCad Skill — Field Report

**Author:** Claude (agentic session)
**Test vehicle:** `Brushed_Flight_Controller` — ESP32-S3, 2× MX1508, 1S LiPo
**Task:** Investigate a real KiCad project end-to-end, diagnose issues, and execute a power-tree refactor (remove a misapplied 12 V buck, re-home the motor drivers onto the 1S battery rail, swap the LDO).
**Date:** 2026-05-19

---

## TL;DR

The **diagnosis** phase was fully agentic and went well — inspection + ERC/DRC gave me everything I needed to find the real bugs (a buck regulator that can't physically produce its rated output from 1S, a 10 V-max motor driver wired to a "+12 V" rail, a sub-10-mil cap footprint, solder-mask bridges, GND-pad track collisions, a drill-rule mismatch).

The **execution** phase split cleanly in two:

- **Edits the toolset can express** (symbol delete, value change, footprint change) went through cleanly and ERC stayed green the whole way.
- **Edits the toolset can't express** (symbol swap, wire cleanup, *schematic→PCB sync*, and every PCB-copper fix) had to be handed back to the human.

The single highest-leverage gap is **no forward annotation** (`Update PCB from Schematic`). Without it, every schematic edit an agent makes is stranded — the board never sees it. The screenshots from this session show the symptom directly: the schematic now reads `+BATT`, but the PCB still carries the old `+12V` net and the deleted `U3` footprint, because nothing can push the change across. That one gap, more than any other, is what kept this from being a fully autonomous refactor.

Second-biggest gap: **net-blindness**. I can enumerate symbols and pads but can't ask "what is on net X." I reverse-engineered connectivity from DRC error strings, which occasionally forced me to *guess* (e.g., whether `D1` was a buck catch diode or reverse-polarity protection — I inferred catch diode from placement + the `Net-(D1-K)` string, and it happened to be right, but that's not a reliable way to operate).

---

## What worked well — keep this

1. **Structured inspection** (`inspect_sch`, `inspect_pcb`, `inspect_ref`). Clean, parseable JSON with value/footprint/lib_id per part. I built a complete mental model of the BOM and the power tree from these alone. No complaints.

2. **ERC/DRC integration.** Returns a violation count, structured violations, *and* a path to the full report. This was the backbone of triage — I found solder-mask bridges, motor-output tracks crossing MX1508 GND pads, the 0.2 mm-drill-vs-0.3 mm-rule mismatch, and real net shorts straight out of the DRC payload.

3. **Git-backed snapshots.** This is exactly right for agentic editing and is the reason I could delete three components without fear. Short refs per snapshot, auto-snapshot-per-edit default, clean restore path. **Do not change this.** It is the safety substrate that makes everything else acceptable to attempt.

4. **Edit tools echo full post-edit state.** Every `edit_*` returned the updated symbol record, so I could self-verify each change landed. Good closed-loop design — I never had to re-inspect just to confirm an edit took.

5. **Honest capability boundaries in tool descriptions.** `edit_move_fp` proactively warns about the both-editors-open IPC segfault in KiCad 10.0.2. That warning kept me from triggering it. More descriptions should carry this kind of operational footgun note.

---

## What created friction

1. **Deferred tool loading via `tool_search`.** Understood as a context-budget tradeoff, but it cost round-trips and I couldn't see a tool's parameter schema until I'd loaded it (I had to load `edit_move_fp` just to learn its args). A resident manifest of signatures, or a one-shot "load all kcd tools," would smooth this.

2. **`project_current` returned an empty schematic entry** — `path`, `filename`, and `sheet_path` were all `""` while the board entry was fully populated. I inferred the `.kicad_pro` path from the board path. A populated schematic path (or an explicit `project_root` field) removes the guesswork.

3. **Adjacent filesystem MCP was sandboxed away from the project.** The filesystem server only allowed `/Volumes/2TB/repos/kcd`, not the project directory. Combined with the net-blindness below, this removed my only fallback — I couldn't read the raw `.kicad_sch` to trace nets myself. Either widen that sandbox to the project dir, or (better) expose connectivity as a first-class tool so the fallback isn't needed.

4. **The net rename worked, but it leaves a latent landmine.** To move the motor rail off `+12V` I edited the `Value` field of five `power:+12V` symbols. This is the *documented* KiCad mechanism — per the KiCad 8/9/10 manual, changing a power symbol's Value field reassigns the global net it connects to, and the Value field is also the visible label, so the net genuinely became `+BATT` and the glyphs now read `+BATT` (not the cosmetic mismatch I originally claimed). The real catch is invisible: the symbols' `lib_id` stays `power:+12V`. Day-to-day that's harmless, but if anyone later runs *Tools → Update Symbols from Library* with "Reset custom power symbols" enabled, KiCad overwrites the Value back to `+12V` and silently re-breaks the net. So a *correct* rename has to also repoint the symbol at `power:+BATT` (or a custom power symbol), not just edit the Value. Separately, this trick only works for power-symbol nets, not label-defined nets. Both reasons argue for a real `kcd_rename_net` primitive (see roadmap).

---

## The agentic gap — what forced human handoffs

This is the section that matters most for closing the loop. Each row is something I had to ask the human to do because no primitive existed.

| # | Couldn't do | What it forced | Proposed primitive |
|---|---|---|---|
| 1 | Push schematic → PCB | Human must run `Update PCB from Schematic`. PCB still shows the deleted `U3` footprint + orphaned `+12V` net (screenshot 2). | `kcd_sync_pcb_from_sch` (forward annotation); back-annotation too, eventually |
| 2 | Swap a symbol (change `lib_id`, remap pins) | Human did the NCP1117 → AP2112K symbol swap by hand | `kcd_edit_symbol(ref, new_lib_id, pin_map?)` |
| 3 | Add a component/symbol | Couldn't add the AP2112K, a reverse-polarity FET, or a fresh power flag | `kcd_add_symbol(lib_id, at, fields)` |
| 4 | Add / delete / edit wires & net labels | Dangling wire stubs left where U3/L1/D1 were (screenshot 1); couldn't reconnect or tidy anything | `kcd_edit_wire`, `kcd_add_netlabel` |
| 5 | Edit any PCB copper (tracks, vias, pours) | All 164 DRC errors are PCB-side; I fixed **zero** of them | `kcd_edit_track`, `kcd_resize_via`, `kcd_edit_zone` |
| 6 | Edit design/DRC rules | Couldn't reconcile the 0.2 mm-via vs 0.3 mm-rule mismatch programmatically | `kcd_edit_designrules` |
| 7 | Rename a net (sch + pcb) | Done via power-flag Value edits — works, but reverts on a library resync and only covers power nets | `kcd_rename_net(old, new)`, lib_id-aware |
| 8 | Edit sheet / block title text | Human renamed the "12 V Voltage Regulator APE1707" block by hand | general text/graphic edit, or a sheet-field editor |

**If only #1 and #2 existed, this session would have gone from "diagnose + partial edits, hand the rest back" to "execute the full schematic refactor and stage the PCB for sync."** Those two are the difference between a *suggestion engine* and an *agent*.

---

## Correctness notes / things to watch

- **The `+BATT` rename did take in the schematic** (screenshot 1 shows `+BATT` labels). The `+12V` still visible on the PCB (screenshot 2) is the **expected pending-sync state**, not a kcd bug. But it's the perfect illustration of gap #1: an agent that can edit the schematic but can't forward-annotate produces a *half-migrated, internally inconsistent* project — arguably worse than not touching it, if a human doesn't know to finish the sync.

- **`edit_value` on a power port changes the net *and* the visible label, but not the symbol identity** (`lib_id` stays put). This should be documented explicitly in the tool description so an agent knows it performed a net change, not a clean symbol swap — and, more importantly, so it flags the residual `lib_id` mismatch as a *library-resync revert hazard* rather than a mere cosmetic note. A later "Update Symbols from Library" with "Reset custom power symbols" enabled will silently undo the rename.

- **Both-editors-open segfault** is a KiCad bug, not kcd's — but the toolset is positioned to detect-and-warn (or auto-manage editor focus) rather than relying on the agent to remember the caveat.

---

## My own misses (not the tool's fault)

Owning these so the roadmap doesn't over-correct for things that are on the operator, not the tooling:

- **I didn't visually verify after structural edits — but the renders were partly out of reach.** kcd auto-renders on every mutating edit, so the SVGs *were* produced; they just land in `/tmp/kcd/`, which the `kcd-filesystem` MCP isn't scoped to read, so I couldn't open them. Had they been reachable, I'd have caught the dangling wire stubs after the deletes instead of the human finding them. The honest split: I should have at least *flagged* that I couldn't see the render output (on me); but the output being unreachable is a tooling gap (see Friction #3), not a habit problem. *Fix:* surface render artifacts where the agent can read them — widen the filesystem scope to `/tmp/kcd/`, or return the render SVG inline in the edit response.

- **I leaned on DRC strings to infer connectivity** when I should have stated the uncertainty more sharply and asked for a targeted netlist earlier, rather than reasoning from footprint coordinates.

---

## Recommended roadmap priority (opinion)

1. **Forward annotation (sch → pcb sync).** Nothing else closes the loop without it. **P0.**
2. **Net inspection** — "what's on net X," "what net is pin Y on." Kills the net-blindness that made me guess. **P0.**
3. **Symbol add + symbol swap.** Unlocks real schematic refactors end to end. **P1.**
4. **Wire / net-label editing.** Cleans up after structural edits; no more orphaned stubs. **P1.**
5. **PCB copper editing + design-rule editing.** Unlocks the entire DRC-fix half of the job — biggest surface area, hardest, but it's where the 164 errors live. **P2.**
6. **First-class net rename** (sch + pcb, lib_id-aware). **P2.**

---

## Closing

The foundation is genuinely good: inspection, rule-checking, and the snapshot safety net are the hard, unglamorous parts and they're solid. What's missing is **mutation breadth** and **the sync bridge**. Right now `kcd` is an excellent *read + diagnose + lightly-edit* tool. The gap to *autonomous refactor* is mostly the eight primitives above, and #1 (forward annotation) is the keystone — it's the difference between edits that stick and edits that strand.

---

*Revision note (2026-05-19): corrected Friction #4 and the related gap-table row and correctness note — the power-net rename via `Value` edits is the documented KiCad mechanism (net **and** label both change to `+BATT`); the real residual is the invisible `lib_id` mismatch, which is a library-resync revert hazard, not cosmetic debt. Also reframed the render-verification "miss" as substantially a tooling gap (auto-rendered SVGs land in `/tmp/kcd/`, outside the agent's filesystem sandbox) rather than pure operator habit. Core hardware diagnosis (12V buck on 1S, MX1508 10V max) re-verified and unchanged.*
