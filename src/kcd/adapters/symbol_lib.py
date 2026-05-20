"""Symbol-library access — read `.kicad_sym` files.

kicad-skip parses `.kicad_sch` but not standalone `.kicad_sym` libraries, so
kcd resolves and reads them itself. This is the Wave-3 enabler for Waves 4-5:
`edit add-symbol` and lib_id-aware net rename need a symbol *definition* for a
part not already instantiated in the project.

Resolution scope: KiCad's standard symbol directory (`config.symbol_dir`) plus
a project's own `sym-lib-table`. Custom *globally*-registered libraries are out
of scope — for a part already placed in the project, kicad-skip's `clone()`
covers it without any library access.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from kcd.core import config as cfg_mod
from kcd.core import sexp
from kcd.core.output import CommandError
from kcd.core.project import Project

_SYMBOL_DIR_VAR = re.compile(r"\$\{KICAD[0-9]*_SYMBOL_DIR\}")


def resolve_lib_file(nickname: str, proj: Project | None = None) -> Path:
    """Resolve a library nickname to its `.kicad_sym` file.

    Checks the project's `sym-lib-table` first (when `proj` is given and the
    table lists `nickname`), then falls back to
    `<symbol_dir>/<nickname>.kicad_sym`.

    Raises:
        FileNotFoundError: the nickname resolves to no existing file.
    """
    if proj is not None:
        table = proj.root / "sym-lib-table"
        if table.is_file():
            uri = _lib_table_uri(table, nickname)
            if uri is not None:
                resolved = _expand_uri(uri, proj)
                if resolved.is_file():
                    return resolved

    symbol_dir = cfg_mod.load().symbol_dir
    if symbol_dir is not None:
        candidate = symbol_dir / f"{nickname}.kicad_sym"
        if candidate.is_file():
            return candidate

    raise FileNotFoundError(
        f"Symbol library {nickname!r} not found — looked in the project "
        f"sym-lib-table and the standard symbol directory "
        f"({symbol_dir or 'not located; set KCD_SYMBOL_DIR'})."
    )


def find_symbol(lib_id: str, proj: Project | None = None) -> dict[str, Any]:
    """Resolve `lib_id` (`"Library:Symbol"`) to its definition + metadata.

    Returns ``{lib_id, library, name, source_file, pins, properties,
    definition}`` — `definition` is the parsed S-expr subtree Waves 4-5 splice
    into a project's `lib_symbols`.

    Raises:
        CommandError(code="invalid_lib_id"): `lib_id` isn't `Library:Symbol`.
        FileNotFoundError: the library file can't be located.
        LookupError: the library exists but has no such symbol.
    """
    if lib_id.count(":") != 1 or lib_id.startswith(":") or lib_id.endswith(":"):
        raise CommandError(
            "invalid_lib_id",
            f"lib_id must be 'Library:Symbol', got {lib_id!r}.",
        )
    nickname, name = lib_id.split(":")
    lib_file = resolve_lib_file(nickname, proj)
    tree = sexp.parse(lib_file.read_text())
    for node in tree:
        if (
            isinstance(node, list)
            and len(node) >= 2
            and node[0] == "symbol"
            and node[1] == name
        ):
            return {
                "lib_id": lib_id,
                "library": nickname,
                "name": name,
                "source_file": str(lib_file),
                "pins": _extract_pins(node),
                "properties": _extract_properties(node),
                "definition": node,
            }
    raise LookupError(
        f"Symbol {name!r} not found in library {nickname!r} ({lib_file})."
    )


def list_libraries(proj: Project | None = None) -> list[dict[str, str]]:
    """List available symbol libraries as `[{nickname, path}]`, sorted.

    The standard symbol directory plus, when `proj` is given, the entries of
    its `sym-lib-table` (project entries override a same-nickname standard one).
    """
    libs: dict[str, str] = {}
    symbol_dir = cfg_mod.load().symbol_dir
    if symbol_dir is not None and symbol_dir.is_dir():
        for f in sorted(symbol_dir.glob("*.kicad_sym")):
            libs[f.stem] = str(f)
    if proj is not None:
        table = proj.root / "sym-lib-table"
        if table.is_file():
            for nickname, uri in _lib_table_entries(table):
                libs[nickname] = str(_expand_uri(uri, proj))
    return [{"nickname": k, "path": v} for k, v in sorted(libs.items())]


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _lib_table_entries(table_path: Path) -> list[tuple[str, str]]:
    """Return `(nickname, uri)` for every `(lib ...)` in a `sym-lib-table`."""
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
    """Substitute KiCad path variables in a `sym-lib-table` URI."""
    result = uri
    if proj is not None:
        result = result.replace("${KIPRJMOD}", str(proj.root))
    symbol_dir = cfg_mod.load().symbol_dir
    if symbol_dir is not None:
        result = _SYMBOL_DIR_VAR.sub(str(symbol_dir), result)
    return Path(result)


def _field(node: list, key: str) -> str | None:
    """Value of the first `(key VALUE ...)` child of `node`, as a string."""
    for child in node:
        if isinstance(child, list) and len(child) >= 2 and child[0] == key:
            return str(child[1])
    return None


def _extract_properties(symbol_node: list) -> dict[str, str]:
    props: dict[str, str] = {}
    for child in symbol_node:
        if isinstance(child, list) and len(child) >= 3 and child[0] == "property":
            props[str(child[1])] = str(child[2])
    return props


def _extract_pins(symbol_node: list) -> list[dict[str, str]]:
    """Pins of a `.kicad_sym` symbol.

    A symbol's pins live inside its nested unit sub-symbols
    (`(symbol "R_1_1" (pin ...))`), not directly under the top symbol.
    """
    pins: list[dict[str, str]] = []
    for child in symbol_node:
        if isinstance(child, list) and child and child[0] == "symbol":
            for sub in child:
                if isinstance(sub, list) and sub and sub[0] == "pin":
                    pins.append(_pin_info(sub))
    return pins


def _pin_info(pin_node: list) -> dict[str, str]:
    # (pin <electrical-type> <graphic-style> (at ...) (length ...)
    #      (name "X" ...) (number "N" ...))
    elec_type = ""
    if len(pin_node) >= 2 and not isinstance(pin_node[1], list):
        elec_type = str(pin_node[1])
    return {
        "number": _field(pin_node, "number") or "",
        "name": _field(pin_node, "name") or "",
        "type": elec_type,
    }
