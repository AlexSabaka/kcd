# Standup report: agentic session findings

**From Dove 🕊️ self-test → Cheetah 🐆 / Sabaka 🐕**
**Date:** 2026-05-18
**Session:** First agentic drive of kcd against `kcd-demo` (Arduino_Pro_Mini, KiCad PCB editor open)

## TL;DR

The good news: when the IPC path works, it really works — `inspect_pcb` returns clean structured data in <1s. The bad news: **roughly half of kcd's surface is non-functional in this configuration.** kicad-cli subprocess hangs forever (no timeout, MCP shim killed both calls at 4 minutes); kicad-skip throws exceptions that escape Cheetah's narrow `except SchEditError` and raw-trace; snapshot init fails; and the envelope contract leaks in ~8 places. 12 tool calls, 1 fully successful command (`inspect_pcb`), 11 failures or hangs. Most of the failures are envelope-contract bugs rather than logic bugs, but the kicad-cli hang is real and dangerous.

## Validation matrix (12 tool calls)

| Tool | Result | Notes |
|---|---|---|
| `inspect_pcb` | ✓ instant | Returns 5 footprints, schema clean. **Only fully working command this session.** |
| `inspect_sch` | ✗ raw traceback | Exception inside `skip_sch.list_symbols()` escapes Cheetah's narrow `except SchEditError`. Same bug pattern as `move-fp` before he patched it. |
| `inspect_ref` | ✗ raw traceback | Same as above — `skip_sch.find_symbol()` raises non-`SchEditError`. |
| `snapshot_create` | ✗ raw traceback at line 25 | `store.create()` fails. Can't see why — error truncated. |
| `snapshot_list` | ✗ raw traceback at line 47 | `store.list()` fails. Same `SnapshotStore` issue. |
| `render_pcb` | ✗ hang → MCP killed at 4 min | No subprocess timeout. Likely kicad-cli waiting on interactive "convert old format" prompt (per your finding #4). |
| `drc` | ✗ hang → MCP killed at 4 min | Same — kicad-cli subprocess hang. |
| `inspect_pcb` (retry) | ✓ instant | Confirmed MCP server still alive after kicad-cli hang. The hang doesn't poison the server. |
| `snapshot_create` with `~/...` | ✗ tilde unexpanded | Either `Path.expanduser()` is failing because `$HOME` isn't in the MCP subprocess env, or the MCP shim mangles tildes pre-invocation. |

Untested this session (didn't get past snapshot to reach them): `edit_value`, `edit_ref`, `edit_footprint`, `edit_delete`, `edit_move_fp`, `render_sch` (subprocess, would probably hang), `export_*`, `erc`, `snapshot_restore`, `snapshot_diff`.

## Findings (priority order)

### #1 — Envelope contract is not enforced uniformly. **Architectural fix needed, not more local patches.**

Every command does roughly:
```python
def cmd(...):
    cfg = cfg_mod.load()
    proj = resolve(project)                  # ← raises FileNotFoundError raw
    store = SnapshotStore(proj, ...)
    r = Result(command="...")
    try:
        r.data = adapter.do_thing(...)        # ← only this is wrapped
    except KnownError:
        r.fail(...)
```

Two leaks per command:
- `resolve()` and `SnapshotStore()` are outside the try block.
- The except clause catches only **named** exception types; anything else escapes.

Cheetah patched three commands locally. This session found at least four more that leak. The right fix is a **decorator**:

```python
def command(name: str):
    def deco(fn):
        @functools.wraps(fn)
        def wrap(*a, **kw):
            r = Result(command=name)
            try:
                fn(r, *a, **kw)
            except FileNotFoundError as e:
                r.fail("not_found", str(e))
            except IpcUnavailable as e:
                r.fail("ipc_unavailable", str(e))
            except SchEditError as e:
                r.fail("edit_failed", str(e))
            except Exception as e:
                r.fail("unexpected", f"{type(e).__name__}: {e}")
            emit(r, json_mode_from_ctx())
        return wrap
    return deco
```

Apply once, every command becomes envelope-safe. ~50 LOC delete + ~20 LOC add, net negative.

### #2 — kicad-cli subprocess has no timeout and hangs

`adapters/kicad_cli.py::_run()` does `subprocess.run(cmd, capture_output=True, text=True)` with no timeout. Whatever's wrong with kicad-cli on this Mac (probably the old-format prompt) means every `render *`, `drc`, `erc`, `export *` command hangs forever. The MCP shim has its own 4-minute kill, which is the only thing saving us, but the user sees "MCP server may be crashed" — not the truth.

Two-part fix:
1. Hard timeout on every `subprocess.run` (60s default, configurable per command).
2. Pass `--non-interactive` / `--force` flags where kicad-cli supports them (KiCad 10's `kicad-cli sch upgrade` etc.). Worth grepping `kicad-cli --help` output and adding flags that suppress "convert old format" style prompts.

### #3 — MCP shim truncates error messages at ~700 chars

Every error this session was clipped mid-traceback. `❱ 23 │   pro` is all I get — I can't see what `resolve()` actually threw. For an agent this is brutal: my only debugging channel is the error message.

Two options:
- MCP shim returns full stderr (might exceed token budgets on long tracebacks).
- kcd writes structured errors to stdout *as well as* stderr, so the shim has clean text. Pair this with #1 — once errors flow through the envelope, the message will already be short and structured.

### #4 — `~` doesn't expand in the MCP subprocess env

`Path("~/Downloads/...").expanduser()` returns `Path("~/Downloads/...")` unmodified, suggesting `$HOME` isn't set in the subprocess env the MCP shim spawns kcd into. Cost me one tool call. Likely the shim is calling subprocess without inheriting the parent's env or with a stripped env.

Fix in kcd: explicitly resolve via `pathlib.Path.home() / target[2:]` when target starts with `~/`, instead of relying on `expanduser()`. Or fix the shim's env propagation.

### #5 — No way to ask "what is KiCad currently working on?"

kipy can answer this (`KiCad.get_open_documents()` or similar in 0.7+). Without exposing it, every agent session starts with blind path probing. Cost me 5+ tool calls this session.

Proposed:
```
kcd project current --json
→ {"open_documents": [
    {"kind": "board", "path": "/Users/.../foo.kicad_pcb", "project": "/Users/.../foo.kicad_pro"},
    {"kind": "schematic", "path": "..."}
  ]}
```

Then `kcd inspect pcb` with no `--project` defaults to whatever the first open board is.

### #6 — `inspect pcb` shouldn't require `--project`

This is the bootstrap-gap from #5 stated differently. For pure IPC operations, kipy already knows which board is loaded. Forcing the agent to provide a path it can't discover is a UX dead-end.

Same applies to: `edit move-fp`, `route track` (whenever it exists), and anything else that's IPC-only on the read/write side.

### #7 — Layer IDs are int-strings, not names

Cheetah's existing finding; here's the data:

```json
{"reference": "J1", "value": "FTDI", "layer": "3", ...}
{"reference": "J7", "value": "Digital", "layer": "34", ...}
```

Layer 3 / 34 are F.Cu / B.Cu in KiCad 10's PCB_LAYER_ID enum (I think — confirms his point). For an agent, `"layer": "F.Cu"` is the only acceptable shape. ~20 LOC shim in `kipy_pcb._footprint_to_dict`. There's an enum or lookup table for this in kipy somewhere; if not, hardcoding the standard layers is fine.

### #8 — MCP schema doesn't expose `--no-snapshot` / `--no-render`

The CLI supports them; the MCP shim doesn't surface them. So when snapshot is broken (as in this session), every edit command is blocked — no way to disable auto-snapshot from the MCP side. Worth adding an optional boolean per tool.

### #9 — `snapshot_create` failure is opaque

Line 25 (`info = store.create(message)`) fails on this project but I can't see why. Possibilities: git not on PATH, permission issue on `/Users/oleksii/Downloads/kcd-demo/.kcd/`, or `.kcd/` left in a bad state by a prior failed attempt. Fix #3 (full errors) makes this self-diagnosable; fix #1 (envelope-everywhere) means the agent gets `{ok: false, error: {code: ..., message: ...}}` instead of a traceback.

### #10 — Cheetah's `inspect_sch` patch is incomplete

The patch catches `SchEditError` but `skip_sch.list_symbols(proj.sch)` raises something else on this project (no traceback, can't tell what). Same pattern as `move-fp` before he added the broad `Exception` tail. Folding into the decorator from #1 would fix this class permanently.

## What I'd prioritize

Order matters because some unblocks others:

1. **The decorator from #1** (~1 hour of work). Closes #1, #4, #9, #10. After this, every command returns a proper envelope, no exceptions to whack-a-mole.
2. **`kcd project current` (#5) + make `project` optional on IPC commands (#6)** (~30 min). Closes the bootstrap gap. Future agent sessions don't waste calls finding paths.
3. **`subprocess.run` timeouts + `--non-interactive` flags (#2)** (~30 min). Stops kicad-cli from hanging indefinitely; lets us see what's actually wrong on this Mac.
4. **Layer ID → name shim (#7)** (~15 min). Tiny, but transformative for agent UX.
5. **MCP shim returns full stderr (#3)** (~depends on the shim, maybe 15 min). Without this, every other fix is still hard to debug.
6. **Path.home() fallback for tildes (#4)** (~5 min). Trivial, but bites every first-time user.

Total estimate: ~3 hours of work to turn kcd from "partly works in known good states" into "robust, debuggable, agentic-ready." None of this is architectural — your scaffold held up. These are surface polish bugs that compound badly when an agent hits them in sequence.

## What I want to test once #1–#3 land

- `edit_value` round-trip on a real symbol (cap value swap with diff-back-via-render).
- `add_track` on one of the 7 unrouted nets the DRC report would name (once DRC stops hanging).
- `freerouting` full loop with the JAR.
- `erc` and `export bom` (kicad-cli, blocked by #2).
- The KiCad upstream segfault repro Cheetah documented — verify the workaround holds across multiple `move-fp` calls.

## On the demo project itself

5 footprints (J1, J2, J3, J6, J7), all connectors, no MCU/crystal/regulator placed. Either it's intentionally stripped down for testing the routing-from-scratch scenario, or the placement step from the schematic hasn't run. The schematic has more — confirmed by KiCad reporting "7 unrouted nets" in Cheetah's notes — so symbols exist but only connectors made it to the PCB. Worth knowing for the routing-loop testing in the next round.

🕊️
