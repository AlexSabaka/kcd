"""kipy-based PCB operations (live IPC, KiCad 10+).

These functions require KiCad to be running with the PCB file open and the
IPC API enabled. They return plain dicts (not kipy proto objects) so callers
can serialize cleanly to JSON.

API reference: https://docs.kicad.org/kicad-python-main/board.html
"""

from __future__ import annotations

from typing import Any

from kcd.core.ipc import IpcUnavailable, get_board


def list_footprints() -> list[dict[str, Any]]:
    """Return a serializable list of all footprints on the open board."""
    board = get_board()
    out: list[dict[str, Any]] = []
    for fp in board.get_footprints():
        try:
            ref = fp.reference_field.text.value
        except Exception:
            ref = "?"
        try:
            value = fp.value_field.text.value
        except Exception:
            value = ""
        try:
            pos = fp.position
            x_nm, y_nm = pos.x, pos.y
        except Exception:
            x_nm, y_nm = 0, 0
        try:
            layer = str(fp.layer)
        except Exception:
            layer = ""
        try:
            lib_id = f"{fp.library_id.library_nickname}:{fp.library_id.entry_name}"
        except Exception:
            lib_id = ""
        out.append({
            "reference": ref,
            "value": value,
            "library_id": lib_id,
            "layer": layer,
            "x_mm": _nm_to_mm(x_nm),
            "y_mm": _nm_to_mm(y_nm),
        })
    return out


def list_tracks() -> list[dict[str, Any]]:
    """Return serialized track segments on the open board."""
    board = get_board()
    out: list[dict[str, Any]] = []
    for t in board.get_tracks():
        try:
            out.append({
                "net": _net_name(t),
                "layer": str(t.layer),
                "width_mm": _nm_to_mm(t.width),
                "start": {"x_mm": _nm_to_mm(t.start.x), "y_mm": _nm_to_mm(t.start.y)},
                "end": {"x_mm": _nm_to_mm(t.end.x), "y_mm": _nm_to_mm(t.end.y)},
            })
        except Exception:
            # Non-segment tracks (arcs etc) — skip until we model them
            continue
    return out


def list_nets() -> list[dict[str, Any]]:
    """Return all nets on the open board with their pad counts."""
    board = get_board()
    out: list[dict[str, Any]] = []
    try:
        nets = board.get_nets()
    except AttributeError:
        return out
    for net in nets:
        out.append({
            "name": net.name,
            "code": getattr(net, "code", None),
        })
    return out


def find_footprint(reference: str) -> dict[str, Any]:
    """Find a footprint by reference designator. Returns full info or raises."""
    board = get_board()
    for fp in board.get_footprints():
        try:
            ref = fp.reference_field.text.value
        except Exception:
            continue
        if ref == reference:
            return _footprint_to_dict(fp)
    raise LookupError(f"Footprint {reference!r} not found on board")


def move_footprint(reference: str, x_mm: float, y_mm: float, rotation_deg: float | None = None) -> dict[str, Any]:
    """Move a footprint to a new position; optionally rotate."""
    board = get_board()
    for fp in board.get_footprints():
        try:
            ref = fp.reference_field.text.value
        except Exception:
            continue
        if ref == reference:
            from kipy.common_types import Vector2
            new_pos = Vector2.from_xy(_mm_to_nm(x_mm), _mm_to_nm(y_mm))
            fp.position = new_pos
            if rotation_deg is not None:
                from kipy.common_types import Angle
                fp.orientation = Angle.from_degrees(rotation_deg)
            board.update_items([fp])
            board.save()
            return _footprint_to_dict(fp)
    raise LookupError(f"Footprint {reference!r} not found on board")


def add_track(
    net_name: str,
    start_mm: tuple[float, float],
    end_mm: tuple[float, float],
    layer: str = "F.Cu",
    width_mm: float = 0.25,
) -> dict[str, Any]:
    """Add a single straight track between two points on a copper layer.

    NOTE: kipy track creation API is still settling. This implementation
    follows the 0.5+ shape. May need adjustment for your kipy version.
    """
    from kipy.board_types import Track
    from kipy.common_types import Vector2

    board = get_board()
    nets = {n.name: n for n in board.get_nets()}
    if net_name not in nets:
        raise LookupError(f"Net {net_name!r} not found on board")

    track = Track()
    track.start = Vector2.from_xy(_mm_to_nm(start_mm[0]), _mm_to_nm(start_mm[1]))
    track.end = Vector2.from_xy(_mm_to_nm(end_mm[0]), _mm_to_nm(end_mm[1]))
    track.width = _mm_to_nm(width_mm)
    track.layer = layer
    track.net = nets[net_name]

    board.create_items([track])
    board.save()
    return {
        "net": net_name,
        "layer": layer,
        "width_mm": width_mm,
        "start": {"x_mm": start_mm[0], "y_mm": start_mm[1]},
        "end": {"x_mm": end_mm[0], "y_mm": end_mm[1]},
    }


def run_drc_via_ipc() -> dict[str, Any] | None:
    """Trigger a DRC run via IPC if supported by this kipy version.

    Returns None if the operation is unavailable; callers should fall back to
    `kicad-cli pcb drc` in that case.
    """
    try:
        board = get_board()
        # kipy 0.6+ exposes board.run_drc(); earlier versions don't.
        if hasattr(board, "run_drc"):
            return board.run_drc()  # type: ignore[no-any-return]
    except IpcUnavailable:
        return None
    return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _footprint_to_dict(fp: Any) -> dict[str, Any]:
    """Serialize a kipy Footprint into a plain dict."""
    return {
        "reference": _safe(lambda: fp.reference_field.text.value, "?"),
        "value": _safe(lambda: fp.value_field.text.value, ""),
        "library_id": _safe(
            lambda: f"{fp.library_id.library_nickname}:{fp.library_id.entry_name}", ""
        ),
        "layer": _safe(lambda: str(fp.layer), ""),
        "x_mm": _safe(lambda: _nm_to_mm(fp.position.x), 0.0),
        "y_mm": _safe(lambda: _nm_to_mm(fp.position.y), 0.0),
        "rotation_deg": _safe(lambda: float(fp.orientation.degrees), 0.0),
        "do_not_populate": _safe(lambda: bool(fp.attributes.do_not_populate), False),
    }


def _net_name(track: Any) -> str:
    try:
        return track.net.name
    except Exception:
        return ""


def _nm_to_mm(nm: int) -> float:
    return nm / 1_000_000.0


def _mm_to_nm(mm: float) -> int:
    return int(round(mm * 1_000_000.0))


def _safe(fn, default):
    try:
        return fn()
    except Exception:
        return default
