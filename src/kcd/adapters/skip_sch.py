"""kicad-skip based schematic adapter (offline S-expression editing).

We use this for schematic operations that kipy doesn't (yet) expose cleanly:
reading/editing symbol values, references, properties, and footprint
assignments.

Reference: https://github.com/psychogenic/kicad-skip
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


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
    """Set or create an arbitrary property on a symbol (e.g. MPN, Manufacturer)."""
    sch = _load(sch_path)
    for sym in sch.symbol:
        if _prop(sym, "Reference") == reference:
            try:
                getattr(sym.property, field).value = value
            except AttributeError:
                # Property doesn't exist yet — kicad-skip supports adding
                if hasattr(sym, "setProperty"):
                    sym.setProperty(field, value)
                else:
                    raise SchEditError(
                        f"Cannot create property {field!r} — your kicad-skip version "
                        "may not support property creation. Add the field in KiCad first."
                    )
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
