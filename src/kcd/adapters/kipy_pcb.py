"""kipy-based PCB operations (live IPC, KiCad 10+).

These functions require KiCad to be running with the PCB file open and the
IPC API enabled. They return plain dicts (not kipy proto objects) so callers
can serialize cleanly to JSON.

API reference: https://docs.kicad.org/kicad-python-main/board.html
"""

from __future__ import annotations

import re
from pathlib import Path as _Path
from typing import Any

from kcd.core.ipc import IpcUnavailable, connect, get_board


def _layer_name(layer: Any) -> str:
    """Return the canonical KiCad layer name (e.g. `"F.Cu"`) for a kipy enum value.

    kipy 0.7.1 surfaces footprint/track `layer` as a `BoardLayer` proto enum
    whose `str()` produces only the int value ("3" / "34") — useless for an
    agent that thinks in named layers. Resolve through the proto enum's
    `Name(int)` method to get e.g. `"BL_F_Cu"`, then strip the `BL_` prefix
    and translate the proto's underscore separator back to KiCad's dot
    notation: `BL_F_Cu` → `F.Cu`, `BL_B_SilkS` → `B.SilkS`.

    Falls back to `str(layer)` if anything goes sideways — better to surface
    a raw int than to crash mid-serialization.
    """
    try:
        from kipy.proto.board.board_types_pb2 import BoardLayer  # type: ignore[import-untyped]
        proto_name = BoardLayer.Name(int(layer))
        if proto_name.startswith("BL_"):
            return proto_name[3:].replace("_", ".")
        return proto_name
    except Exception:
        return str(layer)


def list_open_documents() -> list[dict[str, Any]]:
    """Enumerate documents currently open in KiCad.

    Returns one entry per (PCB | schematic | project) document. Agents use
    this as the bootstrap step: "what is KiCad working on right now?" — so
    subsequent commands can default `--project` from this answer instead of
    requiring the path up front.

    Each document type is probed independently — KiCad routes
    GetOpenDocuments to the kiface that owns that type, so e.g. asking for
    DOCTYPE_SCHEMATIC when only the PCB editor is loaded returns
    `ApiError(no handler available)`. We treat that as "zero open" and move
    on, so a single loaded editor still produces a useful answer.

    Raises:
        IpcUnavailable: KiCad isn't reachable at all (kipy connect failed),
            or *every* doc-type probe failed (likely only the project
            manager is running, no editors at all).
    """
    from kipy.errors import ApiError  # type: ignore[import-untyped]
    from kipy.proto.common.types import DocumentType  # type: ignore[import-untyped]

    kicad = connect()
    out: list[dict[str, Any]] = []
    last_api_error: ApiError | None = None
    any_responded = False

    probes: list[tuple[DocumentType.ValueType, str]] = [
        (DocumentType.DOCTYPE_PCB, "board"),
        (DocumentType.DOCTYPE_SCHEMATIC, "schematic"),
        (DocumentType.DOCTYPE_PROJECT, "project"),
    ]
    for doc_type, kind in probes:
        try:
            docs = kicad.get_open_documents(doc_type)
        except ApiError as e:
            last_api_error = e
            continue
        any_responded = True
        for d in docs:
            if kind == "board":
                # `board_filename` is the basename only (e.g. "foo.kicad_pcb").
                # `project.path` is the project root dir — join them so the agent
                # gets an absolute path that `resolve()` can consume directly.
                project_dir = d.project.path if d.HasField("project") else ""
                full_path = (
                    str(_Path(project_dir) / d.board_filename)
                    if project_dir
                    else d.board_filename
                )
                out.append(
                    {
                        "kind": "board",
                        "path": full_path,
                        "filename": d.board_filename,
                        "project_dir": project_dir,
                    }
                )
            elif kind == "schematic":
                # `sheet_path.path_human_readable` is the SHEET-HIERARCHY
                # path (e.g. "/", "/SubA/"), NOT the filesystem path —
                # confirmed in kipy's proto comments: "The path converted
                # to a human readable form such as '/', '/child', or
                # '/child/grandchild'". On some setups it even comes
                # through empty (Dove session-5 close).
                #
                # Reconstruct the actual .kicad_sch file path from the
                # project specifier — same pattern the board branch above
                # uses with project.path + board_filename. KiCad always
                # names the root schematic <project-name>.kicad_sch inside
                # the project dir. Hierarchical sub-sheets are separate
                # files in the same dir but kipy doesn't tell us which
                # individual sheet the editor is currently focused on,
                # only the hierarchy.
                project_dir = d.project.path if d.HasField("project") else ""
                project_name = d.project.name if d.HasField("project") else ""
                full_path = (
                    str(_Path(project_dir) / f"{project_name}.kicad_sch")
                    if project_dir and project_name
                    else ""
                )
                sheet_hier = getattr(d.sheet_path, "path_human_readable", "") or ""
                out.append(
                    {
                        "kind": "schematic",
                        "path": full_path,
                        "filename": (
                            f"{project_name}.kicad_sch" if project_name else ""
                        ),
                        "project_dir": project_dir,
                        "sheet_path": sheet_hier,
                    }
                )
            else:
                out.append(
                    {"kind": "project", "name": d.project.name, "path": d.project.path}
                )

    if not any_responded and last_api_error is not None:
        raise IpcUnavailable(
            "KiCad is running but no editor is exposing documents. "
            "Open the .kicad_pcb or .kicad_sch file in its editor and retry. "
            f"(Underlying: {last_api_error})"
        ) from last_api_error
    return out


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
            layer = _layer_name(fp.layer)
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
    # KiCad's internal order isn't stable: modifying a footprint pushes it
    # to the head of get_footprints(). Diffing two `inspect pcb` outputs to
    # find "what changed" then becomes noise. Sort by reference designator
    # with numeric-suffix awareness so R1, R2, R10 land in agent-friendly
    # order (not R1, R10, R2). Dove session-3 #19.
    out.sort(key=lambda fp: _ref_sort_key(fp["reference"]))
    return out


def list_tracks() -> list[dict[str, Any]]:
    """Return serialized track segments on the open board."""
    board = get_board()
    out: list[dict[str, Any]] = []
    for t in board.get_tracks():
        try:
            out.append({
                "net": _net_name(t),
                "layer": _layer_name(t.layer),
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
    """Move a footprint to a new position; optionally rotate.

    Caveat: calls `board.save()` after the move. kipy 0.7.1 has no
    `is_dirty()` / `has_unsaved_changes()` API, so this *will* persist
    whatever in-editor changes the user has alongside the footprint
    move. The CLI surface (`kcd edit move-fp`) emits a warning to
    that effect on every call; see `.claude/CLAUDE.md`'s "External-edit
    caveats" section for the user-facing version.
    """
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


def revert_board() -> None:
    """Force KiCad to discard in-memory board state and reload from disk.

    Sends `RevertDocument` via kipy — the IPC-side equivalent of KiCad's
    File → Revert. Used by `snapshot.restore` to keep the editor in sync
    after kcd writes the project files: without this, KiCad's editor keeps
    the pre-restore state in memory and the next mutating IPC call
    (`move_footprint`, etc.) calls `board.save()` and writes that stale
    memory back on top of the restored file, silently undoing the user's
    revert (Dove session-3 #18).

    Raises:
        IpcUnavailable: KiCad isn't reachable (no editor open, kipy down).
            Callers should treat this as "nothing in memory to sync, the
            disk is already correct."
    """
    board = get_board()
    board.revert()


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
        "layer": _safe(lambda: _layer_name(fp.layer), ""),
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


_REF_SORT_RE = re.compile(r"^([A-Za-z_]+)(\d+)(.*)$")


def _ref_sort_key(ref: str) -> tuple[str, int, str]:
    """Numeric-suffix-aware sort key for reference designators.

    `R1, R2, R10` instead of `R1, R10, R2`. Mixed-prefix sorts by prefix
    first (so all Cs land before all Rs, regardless of number). Refs that
    don't match the standard `<letters><digits><suffix?>` shape sort to
    the bottom via the `"~"` prefix (greater than ascii letters).
    """
    m = _REF_SORT_RE.match(ref or "")
    if m:
        return (m.group(1), int(m.group(2)), m.group(3))
    return ("~" + (ref or ""), 0, "")


def _nm_to_mm(nm: int) -> float:
    return nm / 1_000_000.0


def _mm_to_nm(mm: float) -> int:
    return int(round(mm * 1_000_000.0))


def _safe(fn, default):
    try:
        return fn()
    except Exception:
        return default
