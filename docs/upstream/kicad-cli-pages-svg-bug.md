# Upstream bug draft — kicad-cli `sch export svg --pages` ignores page list

**Target:** https://gitlab.com/kicad/code/kicad — issue tracker
**Suggested title:** `sch export svg --pages flag ignored — always renders page 1`
**Suggested labels:** `area:cli`, `severity:normal`
**Affects:** KiCad 10.0.2 (kicad-cli `Application: kicad-cli`, version `10.0.2`)
**Observed on:** macOS 24.4.0 (Apple Silicon)
**Status as of 2026-05-19:** unfiled. Reproducer below is ready to paste.

This draft was authored by **Dove 🕊️ + Cheetah 🐆** during session-4 validation of `kcd`
(an agentic harness around kicad-cli + kipy). The bug surfaced because per-sheet rendering
attribution falls back to mtime filtering as a workaround. We have no GitLab account
attached to the agent; Sabaka should file when convenient.

## Summary

`kicad-cli sch export svg --pages <n>` accepts any value for `--pages` (no validation
error, no warning) but always renders **only page 1** regardless of the value passed.
This is a "flag accepted, value ignored" class bug — the CLI returns a successful exit
code and the expected SVG filename pattern, just with the wrong content. Downstream
tooling that relies on multi-page exports has to compensate (typically by rendering
*all* pages and filtering on the consumer side, or by post-hoc mtime attribution).

## Reproducer

Uses KiCad's bundled `complex_hierarchy` demo (ships out of the box on every install).
Any project with ≥ 2 entries in the `.kicad_pro` `sheets` array reproduces the same
behavior.

```bash
# Adjust path for your platform; this is the macOS app-bundle location.
PROJ=/Applications/KiCad/KiCad.app/Contents/SharedSupport/demos/complex_hierarchy

# Ask only for page 2 (the sub-sheet) — expect page 2's SVG in /tmp/sch-bug/.
mkdir -p /tmp/sch-bug
kicad-cli sch export svg \
    --pages 2 \
    --output /tmp/sch-bug/ \
    "$PROJ/complex_hierarchy.kicad_sch"

ls /tmp/sch-bug/
```

**Expected:** one SVG corresponding to page 2 of the hierarchy. Naming convention
based on existing kicad-cli output: `complex_hierarchy-<sheetname>.svg` or similar.

**Observed (KiCad 10.0.2):** the root-sheet SVG (`complex_hierarchy.svg`) is written.
No sub-sheet SVG appears. Exit code is `0`.

The bug class is "flag accepted, value ignored" rather than "flag rejected": even
nonsense input (`--pages 99`, `--pages 1,2`, `--pages all`) is accepted silently and
still produces only page 1.

## Why it matters

Tooling that drives kicad-cli programmatically (agentic harnesses, build pipelines,
linters) needs per-page renders to do anything sheet-aware: surface the right SVG
after editing a sub-sheet symbol, generate per-sheet review docs, etc.

The current workaround in `kcd` (this harness) is mtime-based attribution: render
every page with no `--pages`, then look at which SVGs' mtimes bumped during the
kicad-cli invocation, then filter against a separately-derived index of which
sheet file the edit actually touched. That works, but it's substantially more
moving parts than `--pages 2` would be; the code is at
[`src/kcd/commands/edit.py::_post_edit_sch`](https://github.com/<...>/kcd/blob/main/src/kcd/commands/edit.py)
(`snapshot_sheet_mtimes` + `sheet_index` + post-render mtime diff).

If `--pages` worked, callers could request just the touched page and skip the
extra bookkeeping.

## Suspected location

`kicad-cli sch export svg` argument parsing in
[`kicad/kicad/cli/command_export_sch_svg.cpp`](https://gitlab.com/kicad/code/kicad/-/blob/master/kicad/cli/command_export_sch_svg.cpp)
(or the closest equivalent path for the current tree). Either the option isn't being
threaded into the exporter, or the exporter only consults the page-1 branch.

We haven't dug into the source; flagging the file purely as a starting point.

## Environment

```
kicad-cli --version
Application: kicad-cli
Version: 10.0.2-0
Date: 2025-XX-XX
Wx: 3.2.X
Boost: 1.X.X
OCC: 7.X.X
Curl: 8.X.X
ngspice: 44
Compiler: Clang
Platform: macOS 24.4.0, 64-bit, Little Endian
```

(Fill in exact build metadata at file-time; the version string above is the floor.)

## Suggested triage

- Severity: **normal** — workaround exists (render all pages, filter), correctness
  not affected (the page-1 SVG that IS written is itself correct).
- Area: `area:cli`.
- Component: schematic-export.
- Probable scope: argument handler for `--pages`; verify each branch of
  `kicad-cli sch export svg` actually reads the parsed value.

## Cross-reference

Surfaced by Dove 🕊️ (Claude Desktop) during validation of the kcd agentic harness,
2026-05-19. See `docs/Dove-to-Cheetah-Standup-Report-post-η-ν.md` in this repo for
the original observation in context.
