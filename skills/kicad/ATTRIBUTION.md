# Attribution: skills/kicad/

This skill is vendored from upstream open-source work. Honor the originals.

## Vendored from

- **Source:** `aklofas/kicad-happy` — https://github.com/aklofas/kicad-happy
- **Commit:** `968f5c847121e1c36a4ed848f2bab87f9dfc1016` (v1.3.1, 2026-05-11)
- **License:** MIT (Copyright (c) 2025 Andrew Klofas)
- **Files vendored:** the entire `skills/kicad/` subtree from that commit —
  `SKILL.md`, all 30 files under `scripts/`, all 18 files under `references/`.

The upstream `LICENSE` and `MIT` headers in every file are preserved. Any kcd-side
modifications to vendored files are logged in `PATCHES.md`.

## Considered but not vendored

- **`mattpainter701/my-claude-setup`** — https://github.com/mattpainter701/my-claude-setup
  at commit `5e4b7054d466c393a11cb38f832b8489b6827633` (2026-04-24). MIT.

  Dove's session-5-prep brief proposed splitting the vendor between kicad-happy
  (scripts) and mattpainter (references). Per-doc diff at vendor time showed
  mattpainter's 12 reference docs are a **subset** of kicad-happy's 18, and where
  they overlap, mattpainter's versions document *older* analyzer behavior
  (predates kicad-happy's auto-cache-parsing feature, manual subcircuit-ID step,
  etc.). One file (`manual-gerber-parsing.md`) is byte-identical; the rest are
  either smaller in mattpainter, or contain only minor language tweaks
  (`pdf-schematic-extraction.md` differs by 4 lines, all phrasing).

  No material additions in mattpainter's tree justified a co-vendor. Mattpainter
  is correctly identified as a downstream curation that hasn't kept up with
  kicad-happy's updates. Sabaka chose the conservative path: vendor everything
  from kicad-happy as the originator, skip mattpainter entirely.

## License

Both upstreams are MIT. The kcd repo as a whole is MIT — compatible. Preserve
the `LICENSE` and per-file copyright headers on any vendored file you edit.

## Where to file issues

For **analyzer bugs** (wrong Vref lookup, false-positive findings, KiCad
version detection issues): file upstream at the kicad-happy issue tracker.

For **kcd integration bugs** (`kcd analyze *` envelope issues, subprocess
plumbing, packaging problems): file in the kcd issue tracker.

For **doc improvements to the references**: do both — submit the improvement
upstream to kicad-happy first; once merged, sync the file back into our
vendored tree and log it in `PATCHES.md` as a back-port.
