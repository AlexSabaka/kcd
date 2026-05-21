"""Footprint-library access — resolve a `Library:Footprint` to its `.kicad_mod`.

The footprint analogue of `symbol_lib.py`. KiCad resolves footprint libraries
via `fp-lib-table`: a library nickname maps to a `.pretty` *directory*, and a
footprint name to `<dir>/<name>.kicad_mod`. `edit swap-fp` needs the parsed
`(footprint ...)` definition to graft onto the board.

Resolution scope mirrors `symbol_lib.py`: the project's own `fp-lib-table`
plus KiCad's standard footprint directory (`config.footprint_dir`). Custom
*globally*-registered libraries are out of scope.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from kcd.core import config as cfg_mod
from kcd.core import sexp
from kcd.core.output import CommandError
from kcd.core.project import Project

_FOOTPRINT_DIR_VAR = re.compile(r"\$\{KICAD[0-9]*_FOOTPRINT_DIR\}")


def resolve_footprint(lib_id: str, proj: Project | None = None) -> dict[str, Any]:
    """Resolve `lib_id` (`"Library:Footprint"`) to its `.kicad_mod` definition.

    Returns ``{lib_id, library, name, source_file, definition, pads}`` —
    `definition` is the parsed `(footprint ...)` S-expr, `pads` the set of
    pad-number strings it declares.

    Raises:
        CommandError(code="invalid_lib_id"): not `Library:Footprint`.
        FileNotFoundError: the library directory or `.kicad_mod` is missing.
    """
    if lib_id.count(":") != 1 or lib_id.startswith(":") or lib_id.endswith(":"):
        raise CommandError(
            "invalid_lib_id",
            f"footprint must be 'Library:Footprint', got {lib_id!r}.",
        )
    nickname, name = lib_id.split(":")
    pretty_dir = _resolve_pretty_dir(nickname, proj)
    mod_file = pretty_dir / f"{name}.kicad_mod"
    if not mod_file.is_file():
        raise FileNotFoundError(
            f"Footprint {name!r} not found in library {nickname!r} ({mod_file})."
        )
    definition = sexp.parse(mod_file.read_text())
    return {
        "lib_id": lib_id,
        "library": nickname,
        "name": name,
        "source_file": str(mod_file),
        "definition": definition,
        "pads": pad_numbers(definition),
    }


def pad_numbers(footprint: list) -> set[str]:
    """The set of pad-number strings declared in a `(footprint ...)` node.

    Unnumbered mechanical pads carry an empty string; duplicate numbers
    (the same electrical node split across pads) collapse — both are correct
    for the identical-pad-layout comparison `edit swap-fp` makes.
    """
    pads: set[str] = set()
    for child in footprint:
        if isinstance(child, list) and len(child) >= 2 and child[0] == "pad":
            pads.add(str(child[1]))
    return pads


# ---------------------------------------------------------------------------
# Internal — fp-lib-table resolution (same table format as sym-lib-table)
# ---------------------------------------------------------------------------

def _resolve_pretty_dir(nickname: str, proj: Project | None) -> Path:
    """Resolve a footprint-library nickname to its `.pretty` directory."""
    if proj is not None:
        table = proj.root / "fp-lib-table"
        if table.is_file():
            uri = _lib_table_uri(table, nickname)
            if uri is not None:
                resolved = _expand_uri(uri, proj)
                if resolved.is_dir():
                    return resolved

    footprint_dir = cfg_mod.load().footprint_dir
    if footprint_dir is not None:
        candidate = footprint_dir / f"{nickname}.pretty"
        if candidate.is_dir():
            return candidate

    raise FileNotFoundError(
        f"Footprint library {nickname!r} not found — looked in the project "
        f"fp-lib-table and the standard footprint directory "
        f"({footprint_dir or 'not located; set KCD_FOOTPRINT_DIR'})."
    )


def _lib_table_entries(table_path: Path) -> list[tuple[str, str]]:
    """Return `(nickname, uri)` for every `(lib ...)` in an `fp-lib-table`."""
    try:
        tree = sexp.parse(table_path.read_text())
    except (OSError, ValueError):
        return []
    out: list[tuple[str, str]] = []
    for node in tree:
        if isinstance(node, list) and node and node[0] == "lib":
            name = _field(node, "name")
            uri = _field(node, "uri")
            if name and uri:
                out.append((name, uri))
    return out


def _lib_table_uri(table_path: Path, nickname: str) -> str | None:
    for name, uri in _lib_table_entries(table_path):
        if name == nickname:
            return uri
    return None


def _expand_uri(uri: str, proj: Project | None) -> Path:
    """Substitute KiCad path variables in an `fp-lib-table` URI."""
    result = uri
    if proj is not None:
        result = result.replace("${KIPRJMOD}", str(proj.root))
    footprint_dir = cfg_mod.load().footprint_dir
    if footprint_dir is not None:
        result = _FOOTPRINT_DIR_VAR.sub(str(footprint_dir), result)
    return Path(result)


def _field(node: list, key: str) -> str | None:
    """Value of the first `(key VALUE ...)` child of `node`, as a string."""
    for child in node:
        if isinstance(child, list) and len(child) >= 2 and child[0] == key:
            return str(child[1])
    return None
