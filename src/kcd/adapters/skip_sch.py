"""kicad-skip based schematic adapter (offline S-expression editing).

We use this for schematic operations that kipy doesn't (yet) expose cleanly:
reading/editing symbol values, references, properties, and footprint
assignments.

Reference: https://github.com/psychogenic/kicad-skip
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from kcd.core.project import Project


class SchEditError(RuntimeError):
    pass


def _load(sch_path: Path):
    try:
        from skip import Schematic
    except ImportError as e:
        raise SchEditError(
            "kicad-skip is not installed. Install with: pip install kicad-skip"
        ) from e
    if not sch_path.exists():
        raise SchEditError(f"Schematic file not found: {sch_path}")
    return Schematic(str(sch_path))


def list_symbols(sch_path: Path) -> list[dict[str, Any]]:
    """Return all symbols in the schematic with reference, value, and lib_id."""
    sch = _load(sch_path)
    out: list[dict[str, Any]] = []
    for sym in sch.symbol:
        out.append({
            "reference": _prop(sym, "Reference"),
            "value": _prop(sym, "Value"),
            "footprint": _prop(sym, "Footprint"),
            "lib_id": _lib_id(sym),
            "datasheet": _prop(sym, "Datasheet"),
        })
    return out


def find_symbol(sch_path: Path, reference: str) -> dict[str, Any]:
    """Find a symbol by reference designator."""
    sch = _load(sch_path)
    for sym in sch.symbol:
        if _prop(sym, "Reference") == reference:
            return _symbol_to_dict(sym)
    raise SchEditError(f"Symbol {reference!r} not found in {sch_path.name}")


def set_value(sch_path: Path, reference: str, new_value: str) -> dict[str, Any]:
    """Change a symbol's Value property. Returns the symbol's new state."""
    sch = _load(sch_path)
    for sym in sch.symbol:
        if _prop(sym, "Reference") == reference:
            sym.property.Value.value = new_value
            sch.write(str(sch_path))
            return _symbol_to_dict(sym)
    raise SchEditError(f"Symbol {reference!r} not found in {sch_path.name}")


def set_reference(sch_path: Path, old_ref: str, new_ref: str) -> dict[str, Any]:
    """Rename a symbol's Reference."""
    sch = _load(sch_path)
    for sym in sch.symbol:
        if _prop(sym, "Reference") == old_ref:
            sym.property.Reference.value = new_ref
            sch.write(str(sch_path))
            return _symbol_to_dict(sym)
    raise SchEditError(f"Symbol {old_ref!r} not found in {sch_path.name}")


def set_footprint(sch_path: Path, reference: str, footprint: str) -> dict[str, Any]:
    """Set the Footprint property (lib:fp form, e.g. `Resistor_SMD:R_0805_2012Metric`)."""
    sch = _load(sch_path)
    for sym in sch.symbol:
        if _prop(sym, "Reference") == reference:
            sym.property.Footprint.value = footprint
            sch.write(str(sch_path))
            return _symbol_to_dict(sym)
    raise SchEditError(f"Symbol {reference!r} not found in {sch_path.name}")


def set_property(sch_path: Path, reference: str, field: str, value: str) -> dict[str, Any]:
    """Set or create an arbitrary property on a symbol (e.g. MPN, Manufacturer).

    kicad-skip 0.2.5 has no public `add_property` / `setProperty` method. The
    earlier `hasattr(sym, "setProperty")` branch was a bug trap: kicad-skip's
    `ParsedValueWrapper.__getattr__` returns `None` on unknown attrs instead of
    raising, so `hasattr` is truthy and we'd end up calling `None(field, value)`
    → `TypeError`. Instead, use `PropertyCollection.__contains__` (the `in`
    operator) for existence-check, and `PropertyString.clone()` to add a new
    property — clone auto-appends to `sym.property`. `Reference` is always
    present per KiCad schematic rules so it's a stable template.
    """
    sch = _load(sch_path)
    for sym in sch.symbol:
        if _prop(sym, "Reference") == reference:
            if field in sym.property:
                sym.property[field].value = value
            else:
                new_prop = sym.property.Reference.clone()
                new_prop.name = field
                new_prop.value = value
            sch.write(str(sch_path))
            return _symbol_to_dict(sym)
    raise SchEditError(f"Symbol {reference!r} not found in {sch_path.name}")


def delete_symbol(sch_path: Path, reference: str) -> dict[str, Any]:
    """Remove a symbol from the schematic."""
    sch = _load(sch_path)
    for sym in sch.symbol:
        if _prop(sym, "Reference") == reference:
            info = _symbol_to_dict(sym)
            try:
                sym.delete()
            except AttributeError:
                # Older kicad-skip: remove from parent collection
                sch.symbol.remove(sym)
            sch.write(str(sch_path))
            return info
    raise SchEditError(f"Symbol {reference!r} not found in {sch_path.name}")


def sheet_index(proj: Project) -> list[dict[str, Any]]:
    """Return the project's sheets in kicad-cli page order.

    Each entry: ``{"page": int, "uuid": str, "name": str, "file": Path | None,
    "svg_filename": str}``.

    Page 1 is always the root .kicad_sch. Pages 2..N correspond to sheet
    instances in the hierarchy — the `.kicad_pro` file's `sheets` array
    lists them in page order as `[[uuid, display_name], ...]`, where each
    UUID matches a `(sheet ... (uuid ...))` block somewhere in the project's
    .kicad_sch files. The block's `Sheetfile` property names the actual file.

    `svg_filename` is what kicad-cli will write for that page:
        - page 1 → `<project_name>.svg`
        - page N → `<project_name>-<sheet_display_name>.svg`

    Behavior on degenerate inputs: if `.kicad_pro` is missing or has no
    `sheets` key, fall back to a single root entry. If a sub-sheet UUID
    doesn't match anything in the .kicad_sch hierarchy (orphan), `file` is
    `None` — callers should treat that as "render-all fallback".

    Caveat: kicad-cli 10.0.2's `sch export svg --pages` flag is broken — it
    always renders only page 1 regardless of input. So callers can use this
    index to *filter artifact attribution* by file, but can't (yet) tell
    kicad-cli to render fewer pages. Worth filing upstream when there's time.
    """
    try:
        pro_data = json.loads(proj.pro.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return _fallback_sheet_index(proj)

    entries = pro_data.get("sheets") or []
    if not entries:
        return _fallback_sheet_index(proj)

    # Build a uuid → Sheetfile map by scanning every .kicad_sch in the
    # project root for (sheet ...) instances. A regex over the raw s-expr
    # is enough here — we only need the per-sheet block's UUID + Sheetfile,
    # no nested-paren depth tracking required because both fields land at
    # the same outer level inside the (sheet ...) block.
    sheet_re = re.compile(
        r'\(sheet\b(?P<body>(?:[^()]|\([^()]*\))*)',
        re.DOTALL,
    )
    uuid_re = re.compile(r'\(uuid\s+"([^"]+)"\)')
    sheetfile_re = re.compile(r'\(property\s+"Sheetfile"\s+"([^"]+)"')

    uuid_to_file: dict[str, str] = {}
    for sch_file in proj.root.glob("*.kicad_sch"):
        try:
            text = sch_file.read_text()
        except OSError:
            continue
        for m in sheet_re.finditer(text):
            body = m.group("body")
            u = uuid_re.search(body)
            f = sheetfile_re.search(body)
            if u and f:
                uuid_to_file[u.group(1)] = f.group(1)

    out: list[dict[str, Any]] = []
    for i, entry in enumerate(entries):
        page = i + 1
        uuid = entry[0] if len(entry) > 0 else ""
        name = entry[1] if len(entry) > 1 else ""
        if page == 1:
            sch_file: Path | None = proj.sch
            svg_name = f"{proj.name}.svg"
        else:
            filename = uuid_to_file.get(uuid)
            sch_file = (proj.root / filename) if filename else None
            # kicad-cli composes sub-sheet SVG names as `<root>-<sheetname>.svg`
            # using the display name from .kicad_pro (the second element of
            # each sheets entry). Names with path separators or unusual chars
            # may get sanitized by kicad-cli; we use the raw form and trust
            # the common case — callers can fall back to "render all" via the
            # `None`-file branch when this doesn't match.
            svg_name = f"{proj.name}-{name}.svg"
        out.append({
            "page": page,
            "uuid": uuid,
            "name": name,
            "file": sch_file,
            "svg_filename": svg_name,
        })
    return out


def _fallback_sheet_index(proj: Project) -> list[dict[str, Any]]:
    return [{
        "page": 1,
        "uuid": "",
        "name": "",
        "file": proj.sch,
        "svg_filename": f"{proj.name}.svg",
    }]


def snapshot_sheet_mtimes(proj: Project) -> dict[Path, int]:
    """Capture mtime_ns of every .kicad_sch in the project root.

    Paired with `_post_edit_sch` artifact filtering: we want to know which
    sheet file(s) the edit actually touched so we can attribute the right
    rendered SVG(s) and skip the ones that didn't change.
    """
    out: dict[Path, int] = {}
    for sch_file in proj.root.glob("*.kicad_sch"):
        try:
            out[sch_file] = sch_file.stat().st_mtime_ns
        except OSError:
            continue
    return out


def list_nets(sch_path: Path) -> list[dict[str, Any]]:
    """Return all named nets (labels + global_labels) in the schematic."""
    sch = _load(sch_path)
    out: dict[str, dict[str, Any]] = {}
    for label in getattr(sch, "label", []):
        name = label.value if hasattr(label, "value") else str(label)
        out.setdefault(name, {"name": name, "kind": "label", "count": 0})
        out[name]["count"] += 1
    for glabel in getattr(sch, "global_label", []):
        name = glabel.value if hasattr(glabel, "value") else str(glabel)
        out.setdefault(name, {"name": name, "kind": "global", "count": 0})
        out[name]["count"] += 1
    for power in getattr(sch, "power", []) or []:
        try:
            name = power.property.Value.value
            out.setdefault(name, {"name": name, "kind": "power", "count": 0})
            out[name]["count"] += 1
        except Exception:
            continue
    return list(out.values())


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _prop(sym: Any, field: str) -> str:
    try:
        return getattr(sym.property, field).value
    except Exception:
        return ""


def _symbol_to_dict(sym: Any) -> dict[str, Any]:
    return {
        "reference": _prop(sym, "Reference"),
        "value": _prop(sym, "Value"),
        "footprint": _prop(sym, "Footprint"),
        "datasheet": _prop(sym, "Datasheet"),
        "lib_id": _lib_id(sym),
    }


def _lib_id(sym: Any) -> str | None:
    # kicad-skip's lib_id attribute overrides __bool__ to return a str, which
    # breaks `getattr(...) and ...` short-circuits. Read it through try/except
    # so a missing/odd lib_id degrades to None instead of raising TypeError.
    try:
        return str(sym.lib_id.value)
    except (AttributeError, TypeError):
        return None
