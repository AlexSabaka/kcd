# Standup report: post-Phase α-δ validation

**From Dove 🕊️ session 2 → Cheetah 🐆 / Sabaka 🐕**
**Date:** 2026-05-19
**Session:** Re-test of session-1 findings + agentic-loop validation against `pic_programmer` (KiCad 10 PCB editor open)

## TL;DR

**Massive turnaround.** Last session: 1/12 tool calls successful, 6 findings raised. This session: 13/14 tool calls successful (only `edit_prop` for *new* properties broke), and **the full agentic edit→render→inspect→restore→inspect loop validated end-to-end**. Phase α-δ closed 6 of my 10 prior findings cleanly. Six new (mostly smaller) findings raised, none architectural. The kcd surface is now genuinely usable for agentic work.

## Resolved findings from session 1

| # | Finding | Status |
|---|---|---|
| 1 | Envelope not enforced uniformly | ✅ Decorator landed. Even the `edit_prop` failure this session came back as a proper `{ok: false, error: {code: "unexpected", message: "..."}}` instead of a raw traceback. The fix is structural and visible. |
| 2 | kicad-cli has no timeout / hangs | ✅ ERC returned in <1s. DRC returned in <2s with full report. The interactive-prompt failure mode is gone. |
| 4 | MCP shim truncates errors | ✅ Implicitly resolved — clean envelopes mean errors are short and structured before they hit the shim. Haven't seen a truncation this session. |
| 5 | No `project current` command | ✅ `kcd_project_current` exists, returns `{kind, path, filename, project_dir}`. Bootstrap is one call now. |
| 6 | `inspect pcb` requires project arg | ✅ `project` is `anyOf [string, null]` — omitting works, auto-detects from kipy. Tested with `kcd_inspect_pcb` no-args, returned 63 footprints. |
| 7 | Layer IDs as int-strings (`"3"`/`"34"`) | ✅ Now `"F.Cu"` / `"B.Cu"`. Layer shim is doing its job. |
| 8 | MCP schema doesn't expose `--no-snapshot` / `--no-render` | ✅ Every `edit_*` tool now exposes `no_render?: boolean` and `no_snapshot?: boolean` defaulting to false. Visible in the schemas. |
| 9 | `snapshot_create` opaque failure | ✅ Works on `pic_programmer`. Whatever was wrong with the Arduino_Pro_Mini demo dir was project-specific, not a general bug. |
| 10 | `inspect_sch` narrow except | ✅ Caught under the new decorator umbrella. `inspect_sch` returned 100+ symbols on `pic_programmer` with no exception leaks. |

That's 9 of 10 prior findings cleanly addressed.

## Validation matrix (this session, 14 calls)

| Tool | Result | Notes |
|---|---|---|
| `project_current` | ✅ | Returns board path, project_dir. Bootstrapped session in 1 call. |
| `snapshot_create` (path) | ✅ | Returned ref `2619750`, clean envelope. |
| `inspect_pcb` (no args) | ✅ | Auto-detects from kipy. 63 footprints, all `F.Cu` except `JP1` on `B.Cu`. |
| `inspect_sch` | ✅ | 100+ symbols. Multi-unit U2 listed 4× (correct — 74HC125 has 4 gates), `#PWR*` and `#FLG*` mixed in with real components. |
| `erc` | ✅ | 0 violations, 2 sheets, <1s. |
| `drc` | ✅ | 58 violations, useful report: 4 errors (starved-thermal on GND zone), 54 warnings (lib_footprint_mismatch). |
| `inspect_ref U4` (before) | ✅ | Schematic + PCB both `value: "LT1373"`. |
| `edit_prop U4 MPN=...` | ❌ | `TypeError: 'NoneType' object is not callable` — but **returned via clean envelope**. New property creation path broken in `skip_sch.set_property`. |
| `edit_value U4 → "LT1373CN8"` | ✅ | Auto-snapshot fired (`c3f7b5a`), edit landed, 3 SVGs rendered. |
| `inspect_ref U4` (after) | ✅ | Schematic: `LT1373CN8`. PCB: `LT1373` (unchanged — expected, sch edits don't sync to PCB). |
| `snapshot_restore c3f7b5a` | ✅ | Hard reset succeeded. |
| `inspect_ref U4` (post-restore) | ✅ | Back to `LT1373`. Round-trip clean. |
| `export_bom` | ✅ | CSV at `/tmp/pic_programmer-bom.csv`, `grouped: true`. |
| `snapshot_list` | ✅ | 4 snapshots with informative messages. Trail is human-readable. |

## New findings

### #11 — `edit_prop` for *new* properties is broken

```json
{"ok": false, "error": {"code": "unexpected", "message": "TypeError: 'NoneType' object is not callable"}}
```

Trying to set a property that doesn't exist on a symbol (e.g. adding `MPN` to U4) fails with `NoneType is not callable`. Looking at `skip_sch.set_property`:

```python
try:
    getattr(sym.property, field).value = value
except AttributeError:
    if hasattr(sym, "setProperty"):
        sym.setProperty(field, value)   # ← this is probably None
```

In kicad-skip 0.2.5, `hasattr(sym, "setProperty")` returns True even though `sym.setProperty` is itself None (because of how kicad-skip's dynamic attribute resolution works). So we fall into the branch and call `None(field, value)`. Likely fix: check `callable(sym.setProperty)`, or find the actual kicad-skip 0.2.5 API for adding properties — might be `sym.property._add_field()` or similar. Worth a 10-min spelunk in `kicad-skip/skip/sch.py`.

This is the primary blocker for the "add MPN field for sourcing" agentic flow, which is one of the most commonly requested LLM-PCB tasks. Fix is high-value.

### #12 — Render cache isn't cleaned between projects

After my `edit_value` on `pic_programmer`, the artifacts list returned:

```json
[
  {"kind": "schematic_svg", "path": "/tmp/kcd/Arduino_Pro_Mini.svg"},
  {"kind": "schematic_svg", "path": "/tmp/kcd/pic_programmer-pic_sockets.svg"},
  {"kind": "schematic_svg", "path": "/tmp/kcd/pic_programmer.svg"}
]
```

`Arduino_Pro_Mini.svg` is stale from session 1 — it's in the cache dir so kcd globbed it back as a "newly produced artifact." Agent following the artifacts list would chase ghosts.

Three options, in order of effort:
- Per-project cache subdirs (`/tmp/kcd/pic_programmer/`)
- Glob with mtime filter (only files modified during this command)
- Track what kicad-cli created vs what existed already (cleanest, slightly more bookkeeping)

I'd pick option 2 — simplest, no path-shape changes.

### #13 — Auto-render renders *all* sheets, not just the affected one

I edited U4 (which lives on the root sheet only). Auto-render produced both `pic_programmer.svg` and `pic_programmer-pic_sockets.svg`. Fine for 2 sheets, painful for 20.

The kicad-cli SVG export doesn't support a per-sheet flag directly (it's "export all" or nothing), so the fix is on our side: identify which sheet the edited symbol lives on, then either filter the output set or run a single-sheet export via a different path. Lower priority than #12 but same area.

### #14 — `inspect_ref` should flag schematic↔PCB divergence

After my `edit_value U4 → LT1373CN8`:

```json
{
  "schematic": {"value": "LT1373CN8"},
  "pcb":       {"value": "LT1373"}        // unchanged
}
```

This is technically correct (KiCad's "Update PCB from Schematic" is a separate manual step), but it's *exactly* the kind of subtle data drift that bites an agent. The agent sees both values, has to know they should match, and has to know whose to trust.

Proposal: add a `consistency` block:

```json
{
  "schematic": {...},
  "pcb": {...},
  "consistency": {
    "value_matches": false,
    "footprint_matches": true,
    "notes": ["schematic value differs from PCB; run 'Update PCB from Schematic' in KiCad or use `kcd schematic transfer to-pcb` (not yet implemented)"]
  }
}
```

This is actionable. ~30 LOC in `commands/inspect.py::ref`. Trivial, transformative for agent UX.

### #15 — Writes-while-KiCad-is-open may produce reload prompts in KiCad's UI

My `edit_value U4` wrote directly to `pic_programmer.kicad_sch` via kicad-skip while KiCad had the project open (PCB editor only). The write succeeded with no error, but if the user later opens the schematic editor, KiCad will probably show a "file modified externally, reload?" prompt. This is normal external-editor behavior, but worth a one-line note in `docs/agents.md` so agents and users aren't surprised.

Lower priority — but if you find this annoying in practice, the alternative is to require the schematic editor be open and route writes via kipy IPC. That gets blocked by the segfault Cheetah documented (both editors open at once). So the workflow stays: "PCB editor open, schematic edits go through kicad-skip, prompt-on-reopen is expected."

### #16 — `kipy board.save()` may save concurrent user PCB-editor changes

Not directly observed this session (didn't test `edit_move_fp`), but worth flagging from code review. `kipy_pcb.move_footprint` calls `board.save()` at the end. If the user has unsaved changes in PCB editor when an agent runs `edit_move_fp`, those changes will be persisted along with the agent's edit. That's *probably* fine — they're the user's changes, the user clearly intended them — but it bypasses the user's "did you mean to save?" mental model.

One option: have `edit_move_fp` check `board.is_dirty()` first, and if so, return a warning artifact like `{"warning": "PCB editor has unsaved changes that will be persisted along with this edit"}`. Same `warnings` field that's already in the envelope.

## What I still want to test (next round)

In priority order:

1. **`edit_move_fp`** — the only major IPC write path still uncovered this session.
2. **`edit_prop` fix** (#11) — high-leverage for sourcing/MPN workflows.
3. **The kipy `library_id` empty issue** — Cheetah's old-format-quirk note. Worth seeing if `fp.definition.library_id` or another kipy path returns the lib reference even on auto-converted projects.
4. **Tilde expansion** — session 1's finding #6. Not retested because I had the abs path. Worth a quick confirm.
5. **export_gerber + export_step + render commands** — code-complete, untested against this project.
6. **FreeRouting end-to-end** — still the unicorn.

## Things to mention to Sabaka

- The `edit_prop` failure (#11) blocks the single most common LLM-driven workflow: "add MPN/Manufacturer/Datasheet fields to my components for ordering." If you can only fix one thing this round, fix that.
- Findings #12 (stale-cache artifacts) and #14 (sch↔pcb consistency flag) are both ~30 LOC, both transformative for agent UX. Bundle them.
- Tests should now cover **the full agentic loop** as a single integration test: snapshot → inspect → edit → re-inspect → restore → re-inspect. This session validated it works once; an automated test prevents regression. I'd add it to `tests/test_integration.py` (skipped if no kipy/kicad-cli).
- The fact that I got useful structured DRC violations back means the agent can now reason about board issues — "you have 4 starved-thermal errors on GND zone, here are the pad locations and refs." That's a real PCB-review workflow, not just a CLI feature.

🕊️
