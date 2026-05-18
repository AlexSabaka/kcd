# Standup report: `kcd` is live

**From Cheetah 🐆 (via Sabaka 🐕) → Dove 🕊️**
**Date:** 2026-05-18
**Repo:** https://github.com/AlexSabaka/kcd

## TL;DR

Your PoC stood up cleanly on first try. End-to-end validated against a real KiCad 10.0.2 demo on macOS (Arduino_Pro_Mini template, M-series, Python 3.13). 9/9 smoke tests pass; the offline (`kicad-skip`) and online (`kipy` IPC) paths both work; auto-snapshot + auto-render envelope is solid. Three small patches landed mid-session — none of them invalidate your architecture, all three are concrete bugs revealed by first contact with real KiCad/kicad-skip versions. One real KiCad-upstream segfault discovered, with a clean workaround.

## What was validated end-to-end

| Path | Status | Notes |
|---|---|---|
| `snapshot create / list / restore` | ✓ | Git-backed store works; `.kcd/git-dir` initialized lazily; restore is destructive within project dir as designed |
| `inspect sch` (kicad-skip) | ✓ | After lib_id patch — see "Patches" below |
| `inspect ref` (offline) | ✓ | Schematic path works; PCB enrichment gracefully degrades to `pcb: null` + structured warning when KiCad isn't open. Boundary design holds. |
| `edit value` (offline kicad-skip) | ✓ | Auto-snapshot fires, returns `snapshot_before`, auto-render produces SVG, grep verifies new value in SVG, restore round-trip cleanly reverts |
| `render sch` (kicad-cli SVG) | ✓ | Lands in `/tmp/kcd/<project>.svg` as documented |
| `inspect pcb` (kipy IPC read) | ✓ | Returns 5 footprints with reference/value/x_mm/y_mm |
| `edit move-fp` (kipy IPC write) | ✓ | After workaround — see "KiCad bug" below |
| `drc` (kicad-cli subprocess) | ✓ | Structured violations with position + UUID + severity |

## What I couldn't reach this session

- `add_track` — same API shape as `move-fp` (which we did validate), so *probably* works on kipy 0.7.1; no test fixture covers it.
- `freerouting` end-to-end — env var setup verified, but no real DSN round-trip.
- `render 3d` / `render pcb` — should work via kicad-cli, untested.
- `export *` — code-complete, untested against this template.
- `erc` — untested.

## Patches (3 commits, ~25 LOC total)

1. **`Fix lib_id read against kicad-skip 0.2.5`** (`adapters/skip_sch.py`). kicad-skip 0.2.5 ships a `lib_id` attribute whose `__bool__` returns a `str`, which breaks the old `getattr(...) and str(...)` short-circuit with `TypeError: __bool__ should return bool, returned str`. Replaced with a `_lib_id()` helper that try/excepts around `sym.lib_id.value` and degrades to `None`. Surfaced the instant `inspect sch` hit a real schematic.

2. **`Wrap inspect sch in the result envelope`** (`commands/inspect.py`). Adapter errors were escaping as Python tracebacks instead of the documented `{ok: false, error: {...}}` shape — same envelope-contract that `edit.py` already honors. Mirrored its try/except pattern.

3. **`Catch unexpected kipy errors in edit move-fp`** (`commands/edit.py`). The `IpcUnavailable` + `LookupError` catches let `ConnectionError` (and pynng-side fallout from KiCad crashes) escape as tracebacks. Added a broad `Exception` tail so any kipy or KiCad-side failure surfaces as `{ok: false, error: {code: "ipc_failed", ...}}`.

All three are envelope-contract fixes, not architectural changes. The original design held.

## KiCad upstream bug (10.0.2, macOS arm64)

Discovered while testing `edit move-fp` with both the **Schematic Editor and PCB Editor open simultaneously** on the same project: KiCad's IPC router sends the `UpdateItems` request to `_eeschema.kiface` (which doesn't own footprints) instead of `_pcbnew.kiface`. The eeschema handler hits a null pointer in `API_HANDLER_EDITOR::checkForBusy()` and segfaults with `EXC_BAD_ACCESS at 0x0`.

**Workaround:** keep only the PCB Editor open for PCB IPC operations. Confirmed: same `move-fp` call succeeds with eeschema closed.

Worth filing on `gitlab.com/kicad/code/kicad` with the crash trace. Sabaka can do this offline.

## Findings worth strategy attention

- **Repo posture: README ↔ CLI drift.** README's quick-reference advertises `add-symbol|add-power`, `net trace|of|components`, `route diff-pair|unroute`, `export drill|pos` — none are mounted in `cli.py`. v1 truth is what `cli.py` exposes (snapshot, render, inspect, edit, net, drc, erc, export, route — with the listed subcommands of each). Either trim the README to match, or these become v0.2 todos. Recommendation: trim now, expand README as features land.
- **Missing `docs/agents.md`.** README links it; project's `.claude/CLAUDE.md` already covers that ground. Either redirect the link or move the project CLAUDE.md content into `docs/agents.md` so non-Claude agents can find it. Low priority.
- **kipy 0.5 → 0.7.1 reality.** The brief assumed kipy ≥0.5; pip resolved to 0.7.1. Imports and call shapes still work (`Track`, `Vector2.from_xy`, `board.update_items`, `board.create_items`). One cosmetic side effect: `fp.layer` stringifies as the int ID (`"3"`, `"34"`) rather than a name (`"F.Cu"`, `"B.Cu"`). Worth a small adapter shim in `kipy_pcb._footprint_to_dict` if pretty layer names matter for agent prompts.
- **Old-format project quirk.** Arduino_Pro_Mini template was created in pre-10 KiCad and triggers a "will be converted" warning. Under that condition, `fp.library_id.library_nickname` access fails (we degrade to `""`). Real projects shouldn't see this; the demo project might be unrepresentative.
- **Python 3.14 wheel gap.** No `kicad-python` 3.14 wheels yet — had to fall back to 3.13. Worth noting in install docs.

## What to test next round (priorities, in order)

1. **`add_track` against a populated PCB.** Same API shape as `move-fp`, untested. Easiest way: route a single VCC track on the Arduino_Pro_Mini template (it has 7 unrouted nets — `kcd drc` output names them).
2. **FreeRouting end-to-end.** Manual DSN export from KiCad → `kcd route freeroute` → import .ses → re-run DRC. This validates the v1 routing claim.
3. **`erc`** and **`export bom`** — quick wins, kicad-cli subprocess so no IPC dependency.
4. **File the KiCad bug.** Standalone repro: open the Arduino_Pro_Mini template in both editors, run `kcd edit move-fp` against any ref. The crash dump from this session is the smoking gun.

## What is NOT yet recommended

- Building the MCP wrapper. Sabaka asked about Claude Desktop integration; my recommendation is to stay CLI-first (Claude Code handles kcd via bash today) until there's a concrete reason Claude Desktop has to drive it. The kcd JSON envelope is already designed for an MCP wrapper if/when one is needed — should be ~a-day's-work for a thin shim, no architectural changes required.
- Filling in the v2 stubs (diff-pair length tuning, full hierarchical net tracing, headless DSN export). They're still upstream-blocked in the same ways your brief flagged.

## Ship state

Five commits on `main`, pushed to `origin`:

```
3364ebb Catch unexpected kipy errors in edit move-fp
53f4443 Wrap inspect sch in the result envelope
fbb0437 Fix lib_id read against kicad-skip 0.2.5
6c49f0e Point repo URLs at AlexSabaka
1144dd0 Initial scaffolding
```

🐆
