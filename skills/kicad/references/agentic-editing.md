# Agentic Editing & Iteration

`SKILL.md` covers the **review** half of kcd — the read-only analyzers and
the design-review contract. This reference covers the **editing** half: the
mutating surface that carries a board from diagnosis toward fab, and the
KiCad/IPC constraints that govern it.

Read this before any session that *changes* a project. Editing is not
review: a mutation that lands wrong is worse than a finding you missed.

---

## 1. The edit loop

Every mutation follows the same measure → mutate → measure shape. Never
mutate blind, and never leave the board half-changed — the human may be away.

1. **Snapshot, labelled.** `kcd snapshot create <proj> -m "swap U1 to AP2112K"`.
   A good message is how you find this rollback point later. Mutating
   commands auto-snapshot too, but a named snapshot at the *start* of a
   multi-step plan is your anchor.
2. **Measure the baseline.** `kcd drc <proj> --json` (and `kcd analyze pcb`
   for connectivity/zone state). This is the "before" number.
3. **See the BEFORE.** `kcd render pcb <proj> --region-ref <REF> --out
   before.png` — crop to where the change will happen (§3).
4. **Mutate — one change.** A single `kcd edit …` / `kcd route …` command.
   One mutation per loop iteration; do not batch.
5. **See the AFTER.** Re-render the same region. Confirm the change landed
   where intended and did not collide with a neighbour.
6. **Reroute / refill stranded copper.** A move or reroute leaves debt —
   dangling track ends, stale zone fills (§4). Resolve it now.
7. **Measure the delta.** `kcd drc <proj> --since <snapshot-ref>` — this
   reports *only* the by-(type,severity) counts that changed versus the
   snapshot. A tiny payload that tells you exactly what the edit moved,
   without re-reading the whole report.
8. **Keep or revert.** Keep the change only if the delta is net-positive
   (errors down, no new violation types). Otherwise
   `kcd snapshot restore <proj> <ref> --yes` and try again.

`drc --since` is the loop's measuring tape. `analyze diff base.json
head.json` does the same at the analyzer level (component/signal/finding
deltas) when you saved analyzer runs with `--out`.

---

## 2. KiCad ceilings (10.0.2) — KiCad's limits, not kcd's

These are hard constraints of KiCad itself. kcd cannot work around them; it
can only report them honestly. Know them before you mutate.

- **No headless forward annotation (F8).** A schematic edit does **not**
  propagate to the PCB. KiCad 10 exposes no headless "Update PCB from
  Schematic". `kcd sync --check` reports the drift truthfully but cannot
  push it. A symbol/footprint change made on the schematic side is
  *stranded there* until a human runs F8 in the GUI — or you make the
  matching change board-side directly (`edit swap-fp`, `edit move-fp`).
- **Dual-editor IPC segfault.** Having both the schematic editor and the
  PCB editor open at once crashes KiCad 10.0.2's IPC routing. **Run
  PCB-editor-only for every IPC mutating command.** Confirm what is open
  with `kcd project current` before mutating.
- **`board.save()` persists everything.** Every IPC mutation calls
  `board.save()`, and kipy 0.7.1 has no dirty-check API — so the save
  also persists *any unsaved changes the human left open in the PCB
  editor*. Tell the user to save or revert in the editor before you drive
  an IPC edit session.

**IPC vs offline — which commands need KiCad open:**

| Surface | Commands | KiCad state |
|---|---|---|
| PCB IPC | `edit move-fp`/`delete-fp`/`track *`/`via add`/`zone *`/`pcb-text *`, `route track`, `inspect pcb`, `net pcb`/`net of` | KiCad **open**, PCB editor only |
| Offline schematic | `edit value`/`ref`/`footprint`/`prop`/`delete`/`wire *`/`netlabel *`/`add-symbol`/`symbol`/`net`/`text *` | Works closed; if the schematic editor is open, accept its "file changed — reload" prompt |
| Offline board-file | `edit designrules`, `edit swap-fp` | KiCad **closed** — both refuse with `project_open_in_kicad` (override: `--force`) because KiCad would overwrite the edit on its next save |

---

## 3. Render for editing

Renders are for *seeing*; `drc` / `analyze` are for *measuring*. Never
eyeball a pour or a connection from a render — confirm it with a checker.

- **`kcd render pcb <proj> --side top|bottom|both`.** kicad-cli composites
  layers flat with no opacity, so rendering both coppers lets a ground
  pour render as an opaque slab that hides everything. `--side top`
  (default) is a clean single-side view; `--side both` stacks them with
  the back copper faded (`--back-opacity`).
- **Region crop — `--region-ref <REF>` / `--region-bbox x1,y1,x2,y2`.** A
  whole-board render is too coarse for placement work. Sizing the window
  (`--region-window`, mm):
  - **~20-24 mm** — neighbourhood scale: did the part land in the right
    area, are there gross collisions.
  - **~6-10 mm** — fine-placement: 0402 pads, 0.15 mm dangling stubs,
    sub-mm clearances.
  The crop is calibrated to the board-outline bbox, so the reported
  `region_mm` centre equals the footprint's true coordinates.
- **`render sch` / `render 3d`** — schematic SVG/PDF/PNG, photorealistic
  3D. SVG is greppable; request PNG when you need to *see* it.

---

## 4. Mutating-tool catalog

One line each. Every mutating command auto-snapshots before and
auto-renders after (unless `--no-snapshot` / `--no-render`).

**Foundation**
- `snapshot create|list|restore|diff` — git-backed per-project snapshots.
  `restore` is destructive within the project; `--yes` skips its prompt.

**PCB — IPC (KiCad open, PCB editor only)**
- `edit move-fp` — move/rotate a footprint. **Refills copper zones** after
  the move so a moved pad re-bonds to the pour (`data.zones_refilled`).
- `edit delete-fp` — delete a footprint (orphan cleanup).
- `edit track delete|modify` — delete or re-width/re-layer/re-net tracks.
- `edit via add` — add a through-via on a net.
- `edit zone add|delete` — add/delete a rectangular copper pour; both
  refill zones as a side effect.
- `edit pcb-text add|set` — add or edit PCB silkscreen text.
- `route track` — route one track segment. **No snap-to-copper** — route
  to verified endpoints, not estimates, or it leaves dangling far-ends.
- `route freeroute` — FreeRouting orchestration via a `.dsn`/`.ses`
  round-trip.

**PCB — offline `.kicad_pcb` (KiCad closed)**
- `edit swap-fp` — swap a placed footprint for a different library
  footprint. The IPC path can't do this; this rewrites the board file.
  Identical-pad-layout only (same pad numbers; each pad keeps its net) —
  a mismatch is a clean `pad_set_mismatch`. This is the **F8 bypass**:
  it pushes a footprint change to the board KiCad 10 can't forward-annotate.

**Schematic — offline (kicad-skip / `.kicad_pro`)**
- `edit value|ref|footprint|prop|delete` — component-field edits.
- `edit wire add|delete`, `edit netlabel add|delete` — structural edits.
- `edit add-symbol` — place a component.
- `edit symbol` — swap a placed symbol for a different library part.
  Resolves derived (`extends`) symbols correctly — regulator/MCU variants
  return their inherited pins, and `--pin-map` is validated against the
  real pin sets (`bad_pin_map` enumerates the valid pins).
- `edit net` — rename a net (labels + power symbols). Its PCB drift check
  is reliable — it normalizes the hierarchical `/` prefix, so
  `pcb.stale` genuinely reflects whether the board still carries the old
  net.
- `edit text titleblock|set` — schematic title block / free graphic text.
  NOT PCB silk — use `edit pcb-text` for that.
- `edit designrules` — set a `.kicad_pro` DRC constraint.

**Export**
- `export gerber|drill|bom|step|pos|pdf` — fab outputs. `export gerber`
  ships a complete package (gerbers **and** drills).

**Zone-fill staleness — the friction every placement move generates.**
A moved pad or a reroute leaves zone fills computed for the old geometry.
`edit move-fp` and `edit zone add|delete` refill automatically;
`route track` / `edit track *` do **not**, and there is no standalone
refill primitive. After a track edit, re-fill by re-running a zone op, or
accept and document the staleness. Always verify with `drc`
(`unconnected_items`, `track_dangling`) and `analyze pcb` zone
`is_filled` / `fill_ratio` — never eyeball it.

---

## 5. Artifacts & the filesystem split

Every analyzer/render/edit command registers artifacts in the envelope's
`artifacts[]` with a `path` — but that path is on the **kcd host**
(`$KCD_RENDER_CACHE`, default `/tmp/kcd/...`).

In a sandboxed or MCP environment the agent runs in a different container
from the kcd host, so **that path may not be readable** with `bash`/`grep`.
To consume command output:

- Read the **inline envelope `data`** — it is folded to fit and is always
  reachable.
- For an oversized result the harness spills a copy the agent *can* read
  (in Claude's environment, under `/mnt/user-data/...`).
- Do not assume the `/tmp/kcd/...` artifact path is reachable — treat it
  as a host-side handle, not an agent-side file.

---

## 6. Verification discipline

- **Snapshot before every mutation.** Not just at session start — before
  each change. Cheap, and the only way back.
- **Back every kept change with a delta.** `drc --since <snapshot>` for
  rule violations, `analyze diff` for analyzer-level change. "It looks
  right" is not evidence.
- **`snapshot restore` is the safety net — test it deliberately.** Know it
  works before you need it. Never end a session on a half-rerouted board:
  either finish the loop or restore.
- **Editing does not relax the review rails.** The `DS-001` consistency
  discipline, plausibility assessment, and datasheet-as-ground-truth rules
  from `SKILL.md` apply to an edit session too — a swap to the wrong part
  passes DRC just as silently as a bad pin map.
