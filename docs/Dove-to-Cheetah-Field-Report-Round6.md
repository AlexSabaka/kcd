# R6 Field Report — kcd toolset & kicad skill

**What's missing, what could be better, what would save time/tokens.**

## R5 fixes — final verdicts
- **R5-4 gerber drill bundling** ✓ · **R5-1 render crop** ✓ · **R5-2 region/zoom** ✓ *and calibrated to the micron* (your highest-risk item — no offset) · **R5-5 analyze_diff graceful** ✓ · **R5-6 cross insufficient_data** ✓ · **R5-7 edit pcb-text add/set** ✓.
- **B2 fold — partial.** Findings sample correctly; six list-sections elide. Still fully inline: `nets`+`net_name_to_id` (duplicated 80-entry maps), `layers`, full `silkscreen`, and 44-element lists in *both* `ground_domains` and `copper_presence`. Over the <50 KB target on this board.
- **R5-3 connectivity** ✓ but the **`statistics.routing_complete: true` sibling is still stale** in the same payload.

## Capstone
Closed visual loop **see→move→see→reroute→measure** works end-to-end: C22 moved off the MX1508, **−6 DRC errors** verified, courtyard + hole-clearance cleared. The board can now be driven diagnosis→improvement with the human only on KiCad-locked steps — *for placement*. Symbol/footprint identity is still locked behind the gaps below.

## New bugs/gaps found this round (priority order for Cheetah)
1. **Symbol `extends` not resolved** (high, self-contained). `lib_show` returns `pins: []` and `edit_symbol` can't target *any* derived symbol — which is most of KiCad's library (every regulator variant, many MCUs). This alone blocks the U1 fix at step one. Device:R (base) works; all AP2112K variants return zero pins.
2. **No PCB-side footprint-swap** (high, the real U1 enabler). Need `edit_swap_fp <ref> <new_fp>` with pad→net remap on the board, bypassing the F8 forward-annotation KiCad 10 won't do over IPC.
3. **`edit_net` drift check is a false-green** (medium). Compares bare label names against prefixed PCB nets (`/ELRS_TX`), so reports `old_net_present:false, stale:false` when drift genuinely exists. Normalize the leading `/`.
4. **No snap-to-copper / no zone-refill primitive** (medium). Every `move_fp` strands stubs; `route_track` reconnects the net but leaves dangling far-ends, and a moved pad can't re-bond to the GND pour without manually adding a via. This is the +3 dangling warnings my capstone generated — it'll happen on *every* placement move at scale.
5. **`edit_symbol` `bad_pin_map` should enumerate valid target pins** (low, pure UX). It sent me guessing twice.
6. **`analyze_cross` doc/behavior mismatch** (low). Fast-fails in 5 ms; skill says it "runs the analyzers internally."

## What would save you (me) the most time/tokens
- **`analyze_pcb` is still the token hog.** Finish B2: spill the net maps + layers + the duplicated copper/ground lists. Dedupe `nets`/`net_name_to_id`. That one change is the biggest token win in the toolset.
- **A `region_window` hint in the render docs.** I burned a render learning that 20–24 mm is neighborhood-scale and you need ~8–10 mm to see 0402 pads / 0.15 mm stubs. One sentence saves a round-trip every placement task.
- **DRC delta mode.** I re-pulled the full 190-violation payload three times to compute deltas by hand. A `kcd drc --since <snapshot>` (or `drc_diff`) returning only the by-type counts changed would save a large read each measure step.
- **`lib_show` on the actual placed ref.** `inspect_ref` enriches from the schematic but doesn't show resolved pins; having pin resolution there (once `extends` works) would collapse my two-call lib_show detour.
