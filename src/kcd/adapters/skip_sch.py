"""kicad-skip based schematic adapter (offline S-expression editing).

We use this for schematic operations that kipy doesn't (yet) expose cleanly:
reading/editing symbol values, references, properties, and footprint
assignments.

Reference: https://github.com/psychogenic/kicad-skip
"""

from __future__ import annotations

import copy
import json
import re
import uuid as _uuid
from pathlib import Path
from typing import Any

from kcd.core import sexp
from kcd.core.project import Project


class SchEditError(RuntimeError):
    pass


class SymbolNotFound(LookupError):
    """Reference designator not present in the indicated sheet (or project).

    Subclasses `LookupError` (not `SchEditError`) so the envelope at
    `kcd.core.output.run_command` classifies it as ``error.code: "not_found"``
    rather than ``"edit_failed"``. The not-found case is honestly a lookup
    miss — agents discriminating "command broke" from "input was wrong" rely
    on the distinction (Dove session-4 #23).
    """


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
            "properties": _all_properties(sym),
        })
    return out


def find_symbol(sch_path: Path, reference: str) -> dict[str, Any]:
    """Find a symbol by reference designator."""
    sch = _load(sch_path)
    for sym in sch.symbol:
        if _prop(sym, "Reference") == reference:
            return _symbol_to_dict(sym)
    raise SymbolNotFound(f"Symbol {reference!r} not found in {sch_path.name}")


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


def add_wire(
    sch_path: Path,
    start: tuple[float, float],
    end: tuple[float, float],
) -> dict[str, Any]:
    """Add a wire segment between two points (mm). Returns the new wire's info."""
    sch = _load(sch_path)
    wire = sch.wire.new()
    wire.start_at([start[0], start[1]])
    wire.end_at([end[0], end[1]])
    sch.write(str(sch_path))
    return {
        "uuid": _elem_uuid(wire),
        "start": [start[0], start[1]],
        "end": [end[0], end[1]],
    }


def delete_wire(
    sch_path: Path,
    start: tuple[float, float],
    end: tuple[float, float],
) -> dict[str, Any]:
    """Delete the wire whose two endpoints match `start`/`end` (either
    direction). Raises SchEditError if no such wire exists."""
    sch = _load(sch_path)
    for wire in sch.wire:
        ends = _wire_endpoints(wire)
        if ends is not None and _endpoints_match(ends, start, end):
            wire.delete()
            sch.write(str(sch_path))
            return {"start": list(ends[0]), "end": list(ends[1])}
    raise SchEditError(
        f"No wire from {_fmt_xy(start)} to {_fmt_xy(end)} found in {sch_path.name}"
    )


def add_label(
    sch_path: Path,
    text: str,
    at: tuple[float, float],
    rotation: float = 0.0,
    is_global: bool = False,
) -> dict[str, Any]:
    """Add a local or global net label at a point. Returns the label's info."""
    sch = _load(sch_path)
    collection = sch.global_label if is_global else sch.label
    label = collection.new()
    label.value = text
    label.move(at[0], at[1], rotation)
    sch.write(str(sch_path))
    return {
        "uuid": _elem_uuid(label),
        "text": text,
        "at": [at[0], at[1], rotation],
        "kind": "global" if is_global else "local",
    }


def delete_label(
    sch_path: Path,
    text: str,
    at: tuple[float, float] | None = None,
) -> dict[str, Any]:
    """Delete net label(s) named `text` (local or global).

    Without `at`, an unambiguous single match is removed; if several labels
    share the name the call fails asking for `at` rather than guessing.
    Raises SchEditError when nothing matches.
    """
    sch = _load(sch_path)
    matches: list[tuple[str, Any, list[float]]] = []
    for kind, collection in (("local", sch.label), ("global", sch.global_label)):
        for label in list(collection):
            if _label_value(label) != text:
                continue
            pos = _label_xy(label)
            if at is not None and not _xy_eq(pos, at):
                continue
            matches.append((kind, label, pos))

    if not matches:
        where = f" at {_fmt_xy(at)}" if at is not None else ""
        raise SchEditError(f"No label {text!r}{where} found in {sch_path.name}")
    if at is None and len(matches) > 1:
        spots = "; ".join(_fmt_xy(p) for _, _, p in matches)
        raise SchEditError(
            f"{len(matches)} labels named {text!r} — pass --at to pick one ({spots})"
        )

    deleted: list[dict[str, Any]] = []
    for kind, label, pos in matches:
        label.delete()
        deleted.append({"text": text, "at": pos, "kind": kind})
    sch.write(str(sch_path))
    return {"deleted": deleted}


def add_symbol_from_clone(
    sch_path: Path,
    like_ref: str,
    new_ref: str,
    value: str | None = None,
    at: tuple[float, float] | None = None,
) -> dict[str, Any]:
    """Add a symbol by cloning an existing instance (`like_ref`).

    The fast path when the project already has the part type — kicad-skip
    deep-copies the symbol (regenerating UUIDs); we then re-reference,
    optionally re-value and reposition it. Raises SchEditError if `like_ref`
    isn't present.
    """
    sch = _load(sch_path)
    src = None
    for sym in sch.symbol:
        if _prop(sym, "Reference") == like_ref:
            src = sym
            break
    if src is None:
        raise SchEditError(f"Symbol {like_ref!r} not found in {sch_path.name}")

    clone = src.clone()
    clone.setAllReferences(new_ref)
    if value is not None:
        clone.property.Value.value = value
    if at is not None:
        clone.move(at[0], at[1])
    sch.write(str(sch_path))
    info = _symbol_to_dict(clone)
    info["source"] = "clone"
    return info


def add_symbol_from_library(
    sch_path: Path,
    project_name: str,
    lib_id: str,
    definition: list,
    pins: list[dict[str, str]],
    new_ref: str,
    value: str | None,
    at: tuple[float, float],
) -> dict[str, Any]:
    """Add a symbol of a part type not yet present in the project.

    Embeds the `lib_symbols` definition (from `symbol_lib.find_symbol`) when
    absent, then appends a fresh instance — all via raw S-expr (`core/sexp`),
    so a brand-new part type needs no existing instance to clone.
    """
    tree = sexp.parse(sch_path.read_text())
    root_uuid = _sexp_child_value(tree, "uuid") or ""
    lib_symbols = _sexp_child(tree, "lib_symbols")
    if lib_symbols is None:
        raise SchEditError(f"{sch_path.name} has no lib_symbols block")

    if not _sexp_has_symbol(lib_symbols, lib_id):
        entry = copy.deepcopy(definition)
        entry[1] = sexp.Quoted(lib_id)
        lib_symbols.append(entry)

    instance = _build_symbol_instance(
        lib_id, new_ref, value or "", at, pins, project_name, root_uuid
    )
    tree.append(instance)
    sch_path.write_text(sexp.dumps(tree))
    return {
        "reference": new_ref,
        "lib_id": lib_id,
        "value": value or "",
        "at": [at[0], at[1]],
        "source": "library",
    }


def swap_symbol(
    sch_path: Path,
    ref: str,
    new_lib_id: str,
    new_definition: list,
    new_pins: list[dict[str, str]],
) -> dict[str, Any]:
    """Swap symbol `ref` to a different library symbol (raw S-expr).

    Changes the instance's `lib_id`, embeds the new `lib_symbols` entry when
    absent, and rewrites the instance's `(pin ...)` entries to the new
    symbol's pin set. Does NOT move wires — the new symbol's pins sit at
    different coordinates, so the caller should warn about wires the swap
    leaves dangling.
    """
    tree = sexp.parse(sch_path.read_text())
    instance = None
    for node in tree:
        if (
            isinstance(node, list) and node and node[0] == "symbol"
            and _sexp_symbol_reference(node) == ref
        ):
            instance = node
            break
    if instance is None:
        raise SchEditError(f"Symbol {ref!r} not found in {sch_path.name}")

    lib_id_node = _sexp_child(instance, "lib_id")
    if lib_id_node is None or len(lib_id_node) < 2:
        raise SchEditError(f"Symbol {ref!r} has no lib_id")
    old_lib_id = str(lib_id_node[1])
    lib_id_node[1] = sexp.Quoted(new_lib_id)

    lib_symbols = _sexp_child(tree, "lib_symbols")
    if lib_symbols is None:
        raise SchEditError(f"{sch_path.name} has no lib_symbols block")
    if not _sexp_has_symbol(lib_symbols, new_lib_id):
        entry = copy.deepcopy(new_definition)
        entry[1] = sexp.Quoted(new_lib_id)
        lib_symbols.append(entry)

    _rewrite_pin_entries(instance, new_pins)
    sch_path.write_text(sexp.dumps(tree))
    return {
        "reference": ref,
        "from_lib_id": old_lib_id,
        "to_lib_id": new_lib_id,
        "pins": [p["number"] for p in new_pins],
    }


def rename_net(
    sch_path: Path,
    old: str,
    new: str,
    power_definition: list | None = None,
) -> dict[str, Any]:
    """Rename net `old` to `new` on one schematic sheet (raw S-expr).

    Renames every net-name carrier: local labels, global labels, and power
    symbols. A power symbol carries its net name in *both* its `Value` and
    its `lib_id` (`power:<name>`) — renaming only `Value` leaves a stale
    `lib_id` that a library resync reverts (field-report friction #4), so we
    repoint the `lib_id` and embed a matching `lib_symbols` entry.

    `power_definition` is the `power:<new>` library definition (from
    `symbol_lib.find_symbol`) when one exists; when None, the entry is
    derived from the schematic's embedded `power:<old>` definition.

    Raises:
        LookupError: no label, global label, or power symbol names `old` —
            the envelope classifies this as ``not_found``.
        SchEditError: a power symbol named `old` but no definition (neither
            passed nor embedded) is available to build the renamed entry.
    """
    tree = sexp.parse(sch_path.read_text())
    n_local = n_global = 0
    power_refs: list[str] = []
    old_power_lib_id: str | None = None

    for node in tree:
        if not isinstance(node, list) or not node:
            continue
        head = node[0]
        if head == "label" and len(node) >= 2 and str(node[1]) == old:
            node[1] = sexp.Quoted(new)
            n_local += 1
        elif head == "global_label" and len(node) >= 2 and str(node[1]) == old:
            node[1] = sexp.Quoted(new)
            n_global += 1
        elif head == "symbol":
            lib_id_node = _sexp_child(node, "lib_id")
            if lib_id_node is None or len(lib_id_node) < 2:
                continue
            lib_id = str(lib_id_node[1])
            if not lib_id.startswith("power:"):
                continue
            val_node = _sexp_value_property(node)
            if val_node is None or len(val_node) < 3 or str(val_node[2]) != old:
                continue
            lib_id_node[1] = sexp.Quoted("power:" + new)
            val_node[2] = sexp.Quoted(new)
            power_refs.append(_sexp_symbol_reference(node) or "?")
            old_power_lib_id = lib_id

    if not (n_local or n_global or power_refs):
        raise LookupError(f"No net named {old!r} found in {sch_path.name}")

    definition_source: str | None = None
    if power_refs:
        new_lib_id = "power:" + new
        lib_symbols = _sexp_child(tree, "lib_symbols")
        if lib_symbols is None:
            raise SchEditError(f"{sch_path.name} has no lib_symbols block")
        if _sexp_has_symbol(lib_symbols, new_lib_id):
            definition_source = "existing"
        else:
            if power_definition is not None:
                entry = copy.deepcopy(power_definition)
                definition_source = "library"
            else:
                template = _sexp_lib_symbol(lib_symbols, old_power_lib_id or "")
                if template is None:
                    raise SchEditError(
                        f"{sch_path.name} has no embedded {old_power_lib_id!r} "
                        "definition to derive the renamed power symbol from"
                    )
                entry = copy.deepcopy(template)
                definition_source = "derived"
            entry[1] = sexp.Quoted(new_lib_id)
            _patch_lib_symbol_value(entry, new)
            lib_symbols.append(entry)

    sch_path.write_text(sexp.dumps(tree))
    return {
        "old": old,
        "new": new,
        "labels": n_local,
        "global_labels": n_global,
        "power_symbols": power_refs,
        "power_lib_id": (
            {"from": old_power_lib_id, "to": "power:" + new} if power_refs else None
        ),
        "power_definition_source": definition_source,
    }


def symbol_pin_geometry(sch_path: Path, ref: str) -> dict[str, Any]:
    """Pin numbers and world positions for symbol `ref` (via kicad-skip).

    `wired_positions` are the positions of pins that currently have a wire
    attached — comparing them before/after a swap spots wires left dangling.
    """
    sch = _load(sch_path)
    numbers: list[str] = []
    positions: list[list[float]] = []
    wired: list[list[float]] = []
    for sym in sch.symbol:
        if _prop(sym, "Reference") != ref:
            continue
        for pin in _iter_symbol_pins(sym):
            try:
                loc = pin.location
                xy = [round(loc.x, 3), round(loc.y, 3)]
            except Exception:
                continue
            numbers.append(_safe_pin_attr(pin, "number"))
            positions.append(xy)
            try:
                if pin.attached_wires:
                    wired.append(xy)
            except Exception:
                pass
    return {"numbers": numbers, "positions": positions, "wired_positions": wired}


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


def locate(proj: Project, reference: str) -> tuple[Path, str]:
    """Find which sheet in `proj` contains `reference`.

    Walks the project's sheets in page order (via `sheet_index`), tries
    `find_symbol` on each `.kicad_sch` file, returns
    ``(sheet_path, sheet_display_name)`` for the first hit. Display name is
    the `.kicad_pro` sheet entry name, or ``"root"`` for page 1.

    Without this, the schematic edit + inspect surface was blind to anything
    living outside `proj.sch` — `inspect ref C7` on `pic_programmer` reported
    "not found" even though C7 sits on the `pic_sockets` sub-sheet
    (Dove session-3 #20).

    Raises:
        SymbolNotFound: No sheet in the project contains the reference.
    """
    for entry in sheet_index(proj):
        path = entry["file"]
        if path is None:
            continue
        try:
            find_symbol(path, reference)
        except SymbolNotFound:
            continue
        return path, (entry["name"] or "root")
    raise SymbolNotFound(
        f"Symbol {reference!r} not found in any sheet of {proj.name}"
    )


def list_symbols_all(proj: Project) -> list[dict[str, Any]]:
    """List every symbol on every sheet of `proj`, each tagged with its sheet.

    Aggregates `list_symbols` across the project in page order. Each
    returned dict gains a ``sheet`` key with the `.kicad_pro` display name
    (``"root"`` for page 1). Backbone for board-wide BOM / sourcing
    workflows that previously stopped at the root sheet.
    """
    out: list[dict[str, Any]] = []
    for entry in sheet_index(proj):
        path = entry["file"]
        if path is None:
            continue
        for sym in list_symbols(path):
            sym["sheet"] = entry["name"] or "root"
            out.append(sym)
    return out


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
    # Power nets: kicad-skip has no `sch.power` collection — power symbols
    # live in `sch.symbol` like any other, identified by a `power:` lib_id.
    # The net name is the symbol's Value.
    for sym in getattr(sch, "symbol", []) or []:
        try:
            lib_id = str(sym.lib_id.value)
        except (AttributeError, TypeError):
            continue
        if not lib_id.startswith("power:"):
            continue
        try:
            name = sym.property.Value.value
        except Exception:
            continue
        out.setdefault(name, {"name": name, "kind": "power", "count": 0})
        out[name]["count"] += 1
    return list(out.values())


def trace_net(sch_path: Path, net_name: str) -> dict[str, Any]:
    """Trace a named net through one schematic sheet.

    Walks kicad-skip's wire-graph connectivity outward from every symbol pin
    and collects the component pins electrically attached to `net_name` via a
    local label or a global label. Power nets (where `net_name` is declared
    by `power:*` symbols rather than a label) are reported as the declaring
    power symbols only — see the scope note below.

    Returns ``{net, found, kind, pins, symbols}`` where ``kind`` is a sorted
    list drawn from ``label`` / ``global`` / ``power``, ``pins`` is
    ``[{reference, pin, pin_name}, ...]``, and ``symbols`` is the sorted set
    of references touching the net.

    Scope / known limits (surface these to the caller):
      - One sheet file. Cross-sheet hierarchical joins are not resolved.
      - Power nets: kicad-skip cannot crawl connectivity *through* single-pin
        symbols, and power symbols are single-pin — so for a power net we can
        name the declaring `power:*` symbols but not the component pins on
        it. Use `kcd net of` for the PCB-side membership of a power net.
      - Unnamed / KiCad-auto-named nets (e.g. `Net-(R1-Pad2)`) are out of
        scope — only label / global-label / power nets.
    """
    sch = _load(sch_path)
    pins: list[dict[str, Any]] = []
    symbols: set[str] = set()
    kinds: set[str] = set()

    for sym in sch.symbol:
        ref = _prop(sym, "Reference")
        lib_id = _lib_id(sym) or ""
        if lib_id.startswith("power:"):
            # The power symbol's Value *is* the net name. Its single pin
            # can't be crawled (see scope note), so we record the anchor
            # only.
            if _prop(sym, "Value") == net_name:
                kinds.add("power")
                symbols.add(ref)
            continue
        for pin in _iter_symbol_pins(sym):
            try:
                local = {lbl.value for lbl in pin.attached_labels}
                glob = {lbl.value for lbl in pin.attached_global_labels}
            except Exception:
                continue
            if net_name in local:
                kinds.add("label")
            elif net_name in glob:
                kinds.add("global")
            else:
                continue
            symbols.add(ref)
            pins.append({
                "reference": ref,
                "pin": _safe_pin_attr(pin, "number"),
                "pin_name": _safe_pin_attr(pin, "name"),
            })

    return {
        "net": net_name,
        "found": bool(symbols),
        "kind": sorted(kinds),
        "pins": pins,
        "symbols": sorted(symbols),
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _elem_uuid(elem: Any) -> str:
    try:
        return str(elem.uuid.value)
    except Exception:
        return ""


def _wire_endpoints(wire: Any) -> tuple[tuple[float, float], tuple[float, float]] | None:
    try:
        s = wire.start.value
        e = wire.end.value
        return (float(s[0]), float(s[1])), (float(e[0]), float(e[1]))
    except Exception:
        return None


def _xy_eq(a: Any, b: Any, tol: float = 1e-3) -> bool:
    return abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) < tol


def _endpoints_match(
    ends: tuple[tuple[float, float], tuple[float, float]],
    start: tuple[float, float],
    end: tuple[float, float],
) -> bool:
    a, b = ends
    return (_xy_eq(a, start) and _xy_eq(b, end)) or (
        _xy_eq(a, end) and _xy_eq(b, start)
    )


def _label_value(label: Any) -> str | None:
    try:
        return label.value
    except Exception:
        return None


def _label_xy(label: Any) -> list[float]:
    try:
        v = label.at.value
        return [float(v[0]), float(v[1])]
    except Exception:
        return [0.0, 0.0]


def _fmt_xy(xy: tuple[float, float]) -> str:
    return f"{xy[0]},{xy[1]}"


def _sexp_child(node: list, key: str) -> list | None:
    """First child sub-list of `node` whose head is `key`."""
    for child in node:
        if isinstance(child, list) and child and child[0] == key:
            return child
    return None


def _sexp_child_value(node: list, key: str) -> str | None:
    child = _sexp_child(node, key)
    return str(child[1]) if child is not None and len(child) >= 2 else None


def _sexp_has_symbol(lib_symbols: list, lib_id: str) -> bool:
    for child in lib_symbols:
        if (
            isinstance(child, list)
            and len(child) >= 2
            and child[0] == "symbol"
            and child[1] == lib_id
        ):
            return True
    return False


def _sexp_lib_symbol(lib_symbols: list, lib_id: str) -> list | None:
    """The `(symbol "<lib_id>" ...)` entry in a `lib_symbols` block, or None."""
    for child in lib_symbols:
        if (
            isinstance(child, list)
            and len(child) >= 2
            and child[0] == "symbol"
            and child[1] == lib_id
        ):
            return child
    return None


def _sexp_value_property(symbol_node: list) -> list | None:
    """The `(property "Value" ...)` child of a `(symbol ...)` node.

    Works for both a placed instance and a `lib_symbols` definition — both
    carry the Value as a direct `property` child.
    """
    for child in symbol_node:
        if (
            isinstance(child, list)
            and len(child) >= 3
            and child[0] == "property"
            and child[1] == "Value"
        ):
            return child
    return None


def _patch_lib_symbol_value(def_node: list, value: str) -> None:
    """Set the `(property "Value" ...)` of a `lib_symbols` definition node."""
    val = _sexp_value_property(def_node)
    if val is not None and len(val) >= 3:
        val[2] = sexp.Quoted(value)


def _sexp_symbol_reference(symbol_node: list) -> str | None:
    """The Reference value of a `(symbol ...)` instance node."""
    for child in symbol_node:
        if (
            isinstance(child, list) and len(child) >= 3
            and child[0] == "property" and child[1] == "Reference"
        ):
            return str(child[2])
    return None


def _rewrite_pin_entries(instance: list, new_pins: list[dict[str, str]]) -> None:
    """Replace a symbol instance's `(pin ...)` children with a fresh set.

    Pin entries sit after the properties and before the `(instances ...)`
    block; new entries get freshly-minted UUIDs.
    """
    q = sexp.Quoted
    instance[:] = [
        c for c in instance if not (isinstance(c, list) and c and c[0] == "pin")
    ]
    pin_nodes = [
        ["pin", q(p["number"]), ["uuid", q(str(_uuid.uuid4()))]] for p in new_pins
    ]
    idx = next(
        (
            i for i, c in enumerate(instance)
            if isinstance(c, list) and c and c[0] == "instances"
        ),
        len(instance),
    )
    instance[idx:idx] = pin_nodes


def _build_symbol_instance(
    lib_id: str,
    ref: str,
    value: str,
    at: tuple[float, float],
    pins: list[dict[str, str]],
    project_name: str,
    root_uuid: str,
) -> list:
    """Construct a `(symbol ...)` instance node for a `.kicad_sch`."""
    q = sexp.Quoted
    x, y = str(at[0]), str(at[1])

    def prop(name: str, val: str, hide: bool = False) -> list:
        effects: list = ["effects", ["font", ["size", "1.27", "1.27"]]]
        if hide:
            effects.append(["hide", "yes"])
        return ["property", q(name), q(val), ["at", x, y, "0"], effects]

    node: list = [
        "symbol",
        ["lib_id", q(lib_id)],
        ["at", x, y, "0"],
        ["unit", "1"],
        ["exclude_from_sim", "no"],
        ["in_bom", "yes"],
        ["on_board", "yes"],
        ["dnp", "no"],
        ["uuid", q(str(_uuid.uuid4()))],
        prop("Reference", ref),
        prop("Value", value),
        prop("Footprint", "", hide=True),
        prop("Datasheet", "~", hide=True),
    ]
    for pin in pins:
        node.append(["pin", q(pin["number"]), ["uuid", q(str(_uuid.uuid4()))]])
    node.append([
        "instances",
        ["project", q(project_name),
            ["path", q("/" + root_uuid),
                ["reference", q(ref)], ["unit", "1"]]],
    ])
    return node


def _iter_symbol_pins(sym: Any):
    """Yield kicad-skip `SymbolPin` objects for a symbol.

    Tolerates kicad-skip's single-pin quirk: a symbol with exactly one
    `(pin ...)` comes back from `sym.pin` as a bare `ParsedValue` whose
    iteration yields raw strings, not pin objects. We detect real pins by
    the `SymbolPin` API (`attached_labels` + `location`) and skip the rest —
    single-pin symbols (power flags, test points) simply aren't traced.
    """
    try:
        raw = list(sym.pin)
    except Exception:
        return
    for p in raw:
        if hasattr(p, "attached_labels") and hasattr(p, "location"):
            yield p


def _safe_pin_attr(pin: Any, attr: str) -> str:
    try:
        return str(getattr(pin, attr))
    except Exception:
        return ""


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
        "properties": _all_properties(sym),
    }


def _all_properties(sym: Any) -> dict[str, str]:
    """Every property on the symbol as `{name: value}`.

    Canonical fields (Reference/Value/Footprint/Datasheet) are also exposed at
    the top level of the symbol dict for convenience, but user-added fields
    (MPN, Manufacturer, Stock, ...) only land here — agents that need to read
    arbitrary properties iterate this dict instead of guessing at attribute
    names.
    """
    try:
        return {p.name: p.value for p in sym.property}
    except Exception:
        return {}


def _lib_id(sym: Any) -> str | None:
    # kicad-skip's lib_id attribute overrides __bool__ to return a str, which
    # breaks `getattr(...) and ...` short-circuits. Read it through try/except
    # so a missing/odd lib_id degrades to None instead of raising TypeError.
    try:
        return str(sym.lib_id.value)
    except (AttributeError, TypeError):
        return None
