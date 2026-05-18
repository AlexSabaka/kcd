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
    p = Path(target).expanduser().resolve()

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
