"""Offline `.kicad_pcb` editing — the board-file counterpart of `skip_sch`.

kipy 0.7.1 cannot swap a footprint's definition over IPC (no footprint-library
API, immutable definitions), so `edit swap-fp` rewrites the `.kicad_pcb`
S-expression directly. This module is that surgery, kept narrow: it swaps one
placed footprint for a library footprint with an identical pad-number set.

Strategy — *old-instance base*: the placed footprint is already a valid board
instance, so its identity fields (`uuid`, `path`, `at`, properties, `attr`)
are kept verbatim; only the geometry/pads/model are grafted from the new
library footprint, and each new pad inherits the matching old pad's net.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from kcd.adapters.footprint_lib import pad_numbers
from kcd.core import sexp
from kcd.core.output import CommandError

# Footprint children kept from the *old* board instance — its identity and
# placement. Everything else is the part definition and comes from the new
# library footprint. `attr` is kept so per-instance intent (DNP,
# exclude-from-bom) survives the swap.
_INSTANCE_KEPT = frozenset({
    "layer", "uuid", "at", "path", "sheetname", "sheetfile", "property", "attr",
})

# `.kicad_mod` children NOT copied into a board instance — file/library
# headers, or fields supplied by the kept instance set above.
_LIBRARY_SKIP = frozenset({
    "version", "generator", "generator_version",
    "layer", "uuid", "at", "property", "attr",
})


def find_footprint_node(tree: list, ref: str) -> list | None:
    """The `(footprint ...)` node whose Reference property equals `ref`."""
    for child in tree:
        if (
            isinstance(child, list) and child and child[0] == "footprint"
            and _reference(child) == ref
        ):
            return child
    return None


def swap_footprint(
    pcb_path: Path, ref: str, new_lib_id: str, new_def: list
) -> dict[str, Any]:
    """Swap footprint `ref` on `pcb_path` for the `new_def` library footprint.

    `new_def` is a parsed `.kicad_mod` `(footprint ...)`. The new footprint
    must declare the same pad numbers as the placed one — each new pad
    inherits the old pad's net by number. The `.kicad_pcb` is rewritten in
    place; the caller is responsible for snapshotting first.

    Raises:
        CommandError(not_found): no footprint `ref` on the board.
        CommandError(pad_set_mismatch): the pad-number sets differ.
    """
    tree = sexp.parse(pcb_path.read_text())
    old = find_footprint_node(tree, ref)
    if old is None:
        raise CommandError("not_found", f"No footprint {ref!r} on the board.")

    old_lib_id = str(old[1]) if len(old) >= 2 else ""
    old_pads = pad_numbers(old)
    new_pads = pad_numbers(new_def)
    if old_pads != new_pads:
        raise CommandError(
            "pad_set_mismatch",
            f"{ref} has pads {sorted(old_pads)} but {new_lib_id} has "
            f"{sorted(new_pads)} — swap-fp only swaps footprints with an "
            "identical pad-number set.",
        )

    old_nets = _pad_nets(old)

    result: list = ["footprint", sexp.Quoted(new_lib_id)]
    for child in old[2:]:
        if isinstance(child, list) and child and child[0] in _INSTANCE_KEPT:
            result.append(copy.deepcopy(child))
    for child in new_def[2:]:
        if not isinstance(child, list) or not child:
            continue
        if child[0] in _LIBRARY_SKIP:
            continue
        grafted = copy.deepcopy(child)
        if grafted[0] == "pad":
            _graft_net(grafted, old_nets.get(str(grafted[1])))
        result.append(grafted)
    _set_property(result, "Footprint", new_lib_id)

    for i, child in enumerate(tree):
        if child is old:
            tree[i] = result
            break
    pcb_path.write_text(sexp.dumps(tree) + "\n")
    return {
        "ref": ref,
        "from_footprint": old_lib_id,
        "to_footprint": new_lib_id,
        "position": _at(old),
        "pads_remapped": len(old_nets),
    }


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _reference(footprint: list) -> str | None:
    """The footprint's Reference property value."""
    for child in footprint:
        if (
            isinstance(child, list) and len(child) >= 3
            and child[0] == "property" and str(child[1]) == "Reference"
        ):
            return str(child[2])
    return None


def _pad_nets(footprint: list) -> dict[str, list]:
    """Map `pad number -> its (net ...) node` for every pad that carries one."""
    out: dict[str, list] = {}
    for child in footprint:
        if isinstance(child, list) and len(child) >= 2 and child[0] == "pad":
            for sub in child:
                if isinstance(sub, list) and sub and sub[0] == "net":
                    out[str(child[1])] = sub
                    break
    return out


def _graft_net(pad: list, net_node: list | None) -> None:
    """Attach `net_node` (copied) to a pad — before its uuid if present.

    `None` means the source pad had no net (an unconnected pad); the new
    pad is then left netless.
    """
    if net_node is None:
        return
    net_copy = copy.deepcopy(net_node)
    for i, child in enumerate(pad):
        if isinstance(child, list) and child and child[0] == "uuid":
            pad.insert(i, net_copy)
            return
    pad.append(net_copy)


def _set_property(footprint: list, name: str, value: str) -> None:
    """Set the value of the `(property "<name>" ...)` child, if it exists."""
    for child in footprint:
        if (
            isinstance(child, list) and len(child) >= 3
            and child[0] == "property" and str(child[1]) == name
        ):
            child[2] = sexp.Quoted(value)
            return


def _at(footprint: list) -> list | None:
    """The footprint's `(at X Y [ROT])` values as numbers, or None."""
    for child in footprint:
        if isinstance(child, list) and child and child[0] == "at":
            return [_num(v) for v in child[1:]]
    return None


def _num(value: object) -> object:
    """Parse an S-expr atom to int/float when numeric, else leave it."""
    try:
        f = float(str(value))
    except (TypeError, ValueError):
        return value
    return int(f) if f.is_integer() else f
