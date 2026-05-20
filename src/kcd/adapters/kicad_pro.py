"""`.kicad_pro` project-file editing (offline JSON).

KiCad's `.kicad_pro` is a JSON document. kcd's design-rule edits live here:
`board.design_settings.rules` holds the board constraint minimums that drive
DRC. This is the only place kcd *writes* `.kicad_pro` — everything else reads
it. Round-trip is semantic, not byte-identical; KiCad reformats on save.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from kcd.core.output import CommandError

# board.design_settings.rules — the constraint minimums (KiCad 10). This dict
# doubles as the validation whitelist and the value-coercion schema: a key not
# here is rejected, and the type decides how the raw `--value` string parses.
# Distances are millimetres. The `allow_blind_buried_vias` / `allow_microvias`
# flags are NOT under `rules` (they sit directly on `design_settings`) — out of
# scope here.
_RULE_TYPES: dict[str, type] = {
    "max_error": float,
    "min_clearance": float,
    "min_connection": float,
    "min_copper_edge_clearance": float,
    "min_groove_width": float,
    "min_hole_clearance": float,
    "min_hole_to_hole": float,
    "min_microvia_diameter": float,
    "min_microvia_drill": float,
    "min_resolved_spokes": int,
    "min_silk_clearance": float,
    "min_text_height": float,
    "min_text_thickness": float,
    "min_through_hole_diameter": float,
    "min_track_width": float,
    "min_via_annular_width": float,
    "min_via_diameter": float,
    "solder_mask_to_copper_clearance": float,
    "use_height_for_length_calcs": bool,
}

_BOOL_TRUE = {"true", "yes", "1", "on"}
_BOOL_FALSE = {"false", "no", "0", "off"}


def _coerce(key: str, value: str) -> float | int | bool:
    """Coerce the raw `--value` string to the type rule `key` expects."""
    typ = _RULE_TYPES[key]
    if typ is bool:
        low = value.strip().lower()
        if low in _BOOL_TRUE:
            return True
        if low in _BOOL_FALSE:
            return False
        raise CommandError(
            "bad_value",
            f"{key} is a flag — expected true/false, got {value!r}.",
        )
    try:
        return typ(value)
    except ValueError:
        raise CommandError(
            "bad_value",
            f"{key} expects a {typ.__name__} value, got {value!r}.",
        ) from None


def set_design_rule(pro_path: Path, key: str, value: str) -> dict[str, Any]:
    """Set a `board.design_settings.rules` constraint in a `.kicad_pro` file.

    `value` is the raw CLI string; it is coerced to the type the rule expects
    (millimetre float, int, or bool). The nested `board → design_settings →
    rules` path is created when absent — a freshly-templated project may not
    carry it.

    Raises:
        CommandError("unknown_rule"): `key` is not a known constraint.
        CommandError("bad_value"): `value` won't coerce to the rule's type.
        CommandError("bad_project_file"): the `.kicad_pro` isn't valid JSON.
    """
    if key not in _RULE_TYPES:
        valid = ", ".join(sorted(_RULE_TYPES))
        raise CommandError(
            "unknown_rule",
            f"Unknown design rule {key!r}. Valid rules: {valid}.",
        )
    coerced = _coerce(key, value)

    try:
        data = json.loads(pro_path.read_text())
    except json.JSONDecodeError as e:
        raise CommandError(
            "bad_project_file", f"{pro_path.name} is not valid JSON: {e}"
        ) from e

    rules = (
        data.setdefault("board", {})
        .setdefault("design_settings", {})
        .setdefault("rules", {})
    )
    before = rules.get(key)
    rules[key] = coerced

    pro_path.write_text(json.dumps(data, indent=2) + "\n")
    return {
        "rule": key,
        "before": before,
        "after": coerced,
        "path": str(pro_path),
    }
