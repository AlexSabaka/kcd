"""Project file resolution.

Users can point kcd at:
    - a `.kicad_pro` file directly
    - a directory containing one
    - the project name (we search for matching `.kicad_pro`)

This module normalizes those into a `Project` with reliable paths for sch/pcb.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Project:
    """Resolved KiCad project paths."""

    root: Path
    """Directory containing the .kicad_pro file."""

    pro: Path
    """Absolute path to the .kicad_pro file."""

    name: str
    """Project name (filename stem)."""

    @property
    def sch(self) -> Path:
        """Path to the root schematic file (<name>.kicad_sch)."""
        return self.root / f"{self.name}.kicad_sch"

    @property
    def pcb(self) -> Path:
        """Path to the PCB file (<name>.kicad_pcb)."""
        return self.root / f"{self.name}.kicad_pcb"


def resolve(target: str | Path) -> Project:
    """Resolve `target` (file path, directory, or name) to a Project.

    Raises FileNotFoundError if no `.kicad_pro` can be found.
    """
    raw = str(target)
    p = Path(raw).expanduser()
    # `Path.expanduser()` consults `$HOME`. Some subprocess envs (e.g. the MCP
    # shim's child process) don't propagate $HOME, leaving leading `~` literal.
    # Fall back to `Path.home()` directly when that happens.
    if raw.startswith("~/") and str(p).startswith("~/"):
        p = Path.home() / raw[2:]
    elif raw == "~" and str(p) == "~":
        p = Path.home()
    p = p.resolve()

    if p.is_file() and p.suffix == ".kicad_pro":
        return _from_pro(p)

    if p.is_dir():
        pros = sorted(p.glob("*.kicad_pro"))
        if len(pros) == 1:
            return _from_pro(pros[0])
        if len(pros) > 1:
            raise FileNotFoundError(
                f"Multiple .kicad_pro files in {p}; pass one explicitly: "
                + ", ".join(str(x.name) for x in pros)
            )
        raise FileNotFoundError(f"No .kicad_pro file in {p}")

    # Try interpreting as a path with implicit suffix
    candidates = [
        p.with_suffix(".kicad_pro"),
        p.parent / f"{p.name}.kicad_pro",
    ]
    for c in candidates:
        if c.is_file():
            return _from_pro(c)

    raise FileNotFoundError(f"Cannot resolve KiCad project from: {target}")


def _from_pro(pro: Path) -> Project:
    return Project(root=pro.parent, pro=pro, name=pro.stem)


def resolve_or_active(target: str | Path | None) -> Project:
    """Like `resolve`, but auto-derive from KiCad's active board if `target` is None.

    For IPC commands the agent often has no project path — it just wants to
    operate on whatever board KiCad is showing right now. This helper bridges
    that: if `target` is missing, ask kipy which board is open and resolve
    the project from its filename.

    Raises:
        FileNotFoundError: target was given but couldn't be resolved.
        kcd.core.output.CommandError(code="project_required", ...) when target
            is None and KiCad either isn't running or has 0/>1 boards open.
    """
    if target is not None and str(target).strip() != "":
        return resolve(target)

    # Lazy import to avoid top-level dep on adapters from core
    from kcd.adapters.kipy_pcb import list_open_documents
    from kcd.core.output import CommandError

    try:
        docs = list_open_documents()
    except Exception as e:  # noqa: BLE001
        # Wrap any kipy/IPC failure in CommandError so the envelope ladder
        # surfaces a clean "project_required" rather than dumping an
        # IpcUnavailable trace.
        raise CommandError(
            "project_required",
            f"No --project given and KiCad isn't reachable to auto-detect: {e}",
        ) from e

    boards = [d for d in docs if d.get("kind") == "board" and d.get("path")]
    if len(boards) == 0:
        raise CommandError(
            "project_required",
            "No --project given and no board is open in KiCad. "
            "Open a .kicad_pcb file or pass --project explicitly.",
        )
    if len(boards) > 1:
        paths = ", ".join(b["path"] for b in boards)
        raise CommandError(
            "project_required",
            f"No --project given and multiple boards open ({paths}); pass --project explicitly.",
        )
    return resolve(boards[0]["path"])
