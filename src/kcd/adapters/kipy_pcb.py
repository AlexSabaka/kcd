"""kipy-based PCB operations (live IPC, KiCad 10+).

These functions require KiCad to be running with the PCB file open and the
IPC API enabled. They return plain dicts (not kipy proto objects) so callers
can serialize cleanly to JSON.

API reference: https://docs.kicad.org/kicad-python-main/board.html
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path as _Path
from typing import Any

from kcd.core.ipc import IpcUnavailable, connect, get_board
from kcd.core.output import CommandError


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


def assert_board_is(expected_pcb: _Path) -> None:
    """Verify KiCad has the *expected* board open before whole-board IPC reads.

    `list_footprints()` / `list_pad_nets()` etc. return whatever board is
    active in KiCad's editor. Without this check, a whole-board command
    (`parity`, `sync --check`) run against project A while KiCad shows
    project B would silently compare A against B. Dove session-4 #25.

    No-op when KiCad has no board open at all — the caller's own IPC call
    then raises `IpcUnavailable` and degrades as it sees fit. Call this
    *inside* the caller's `try/except IpcUnavailable` so a fully-unreachable
    KiCad still degrades rather than erroring.

    Raises:
        CommandError(code="wrong_board_open"): a board is open and none of
            the open boards resolve to `expected_pcb`.
        IpcUnavailable: KiCad isn't reachable at all (propagated from
            `list_open_documents`).
    """
    open_docs = list_open_documents()
    open_boards = [d for d in open_docs if d.get("kind") == "board" and d.get("path")]
    if not open_boards:
        return
    expected = expected_pcb.resolve()
    if not any(_Path(b["path"]).resolve() == expected for b in open_boards):
        paths = ", ".join(b["path"] for b in open_boards)
        raise CommandError(
            "wrong_board_open",
            f"KiCad has {paths} open, not the requested {expected_pcb}. "
            "Switch KiCad to the right PCB and retry, or run with KiCad "
            "closed for a schematic-only result.",
        )


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
            # The library id lives on the footprint *definition*, not the
            # board instance — `FootprintInstance` has no `library_id` attr.
            lib_id = f"{fp.definition.id.library}:{fp.definition.id.name}"
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
    """Return all nets on the open board with pad and track counts.

    Counts come from a single pass over the board's pads and tracks. Nets
    declared on the board but with zero members (unrouted / unused) are
    still listed, so an agent sees the complete net set — a `pad_count` of
    0 is a signal, not an omission.

    kipy 0.7.1's `Net` exposes only `name` (no stable net code), so the net
    name is the join key throughout.
    """
    board = get_board()
    try:
        nets = board.get_nets()
    except AttributeError:
        return []

    pad_counts: Counter[str] = Counter()
    for pad in board.get_pads():
        pad_counts[_net_name(pad)] += 1
    track_counts: Counter[str] = Counter()
    for track in board.get_tracks():
        track_counts[_net_name(track)] += 1

    out: list[dict[str, Any]] = []
    for net in nets:
        name = net.name
        out.append({
            "name": name,
            "pad_count": pad_counts.get(name, 0),
            "track_count": track_counts.get(name, 0),
        })
    return out


def net_members(net_name: str) -> dict[str, Any]:
    """Return everything on the open board attached to `net_name`.

    Answers the agent's "what is on net X" question: every pad (with its
    owning footprint reference), track, via, and copper zone carrying the
    net. Pads have no back-reference to their footprint in kipy, so we map
    them by iterating footprints.

    Raises:
        LookupError: no net by that name exists on the board — lets the
            envelope classify it as `not_found` rather than an empty result
            that an agent might read as "net X exists but is unconnected".
    """
    board = get_board()
    if net_name not in {n.name for n in board.get_nets()}:
        raise LookupError(f"Net {net_name!r} not found on board")

    pads: list[dict[str, Any]] = []
    for fp in board.get_footprints():
        try:
            ref = fp.reference_field.text.value
        except Exception:
            ref = "?"
        try:
            fp_pads = list(fp.definition.pads)
        except Exception:
            fp_pads = []
        for pad in fp_pads:
            if _net_name(pad) == net_name:
                pads.append(_pad_to_dict(pad, ref))

    tracks = [t for t in list_tracks() if t["net"] == net_name]

    vias: list[dict[str, Any]] = []
    for via in board.get_vias():
        if _net_name(via) != net_name:
            continue
        try:
            vias.append({
                "x_mm": _nm_to_mm(via.position.x),
                "y_mm": _nm_to_mm(via.position.y),
            })
        except Exception:
            continue

    zones: list[dict[str, Any]] = []
    for zone in board.get_zones():
        try:
            zone_net = zone.net.name if zone.net is not None else ""
        except Exception:
            continue
        if zone_net != net_name:
            continue
        try:
            zones.append({
                "name": zone.name,
                "layers": [_layer_name(la) for la in zone.layers],
            })
        except Exception:
            continue

    return {
        "net": net_name,
        "pads": pads,
        "tracks": tracks,
        "vias": vias,
        "zones": zones,
    }


def list_pad_nets() -> list[dict[str, Any]]:
    """Return every pad on the open board with its footprint ref and net.

    The board-wide pin->net map — the PCB side of `kcd sync`'s drift check.
    A pad with no net comes back with `net` == "" (the caller normalizes
    that and `unconnected-*` names to "no net").
    """
    board = get_board()
    out: list[dict[str, Any]] = []
    for fp in board.get_footprints():
        try:
            ref = fp.reference_field.text.value
        except Exception:
            ref = "?"
        try:
            fp_pads = list(fp.definition.pads)
        except Exception:
            fp_pads = []
        for pad in fp_pads:
            try:
                num = pad.number
            except Exception:
                num = ""
            out.append({
                "footprint": ref,
                "pad": num,
                "net": _net_name(pad),
            })
    return out


def board_net_names() -> list[str]:
    """Return the names of every net on the open board.

    A lean read — no pad/track counting. Used by `edit net`'s post-rename
    drift check to confirm whether the old net name still lives on the PCB
    (kcd cannot forward-annotate headlessly, so a schematic rename leaves the
    board stale until the user runs F8).
    """
    board = get_board()
    try:
        return [n.name for n in board.get_nets()]
    except AttributeError:
        return []


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
    # `track.layer` is a BoardLayer enum int — the raw layer string KiCad
    # hands back from a read command would fail kipy serialization. Convert
    # like `modify_tracks` does, and echo the canonical name back.
    track.layer = _layer_enum(layer)
    track.net = nets[net_name]

    board.create_items([track])
    board.save()
    return {
        "net": net_name,
        "layer": _layer_name(track.layer),
        "width_mm": width_mm,
        "start": {"x_mm": start_mm[0], "y_mm": start_mm[1]},
        "end": {"x_mm": end_mm[0], "y_mm": end_mm[1]},
    }


def delete_tracks(
    expected_pcb: _Path,
    net: str | None = None,
    from_mm: tuple[float, float] | None = None,
    to_mm: tuple[float, float] | None = None,
    layer: str | None = None,
) -> dict[str, Any]:
    """Delete copper tracks from the open board.

    Selection (see `_match_tracks`): `from_mm` + `to_mm` picks the matching
    segment(s); `net` alone selects every track on the net; `layer` narrows
    either. Persists via `board.save()` — see the move-fp caveat.
    """
    assert_board_is(expected_pcb)
    board = get_board()
    tracks = _match_tracks(board, net, from_mm, to_mm, layer)
    deleted = [_track_summary(t) for t in tracks]
    board.remove_items(tracks)
    board.save()
    return {"deleted": deleted, "count": len(deleted)}


def modify_tracks(
    expected_pcb: _Path,
    net: str | None = None,
    from_mm: tuple[float, float] | None = None,
    to_mm: tuple[float, float] | None = None,
    layer: str | None = None,
    *,
    width_mm: float | None = None,
    set_layer: str | None = None,
    set_net: str | None = None,
) -> dict[str, Any]:
    """Modify copper tracks — width, layer, and/or net assignment.

    Selection is the same as `delete_tracks`; the `set_*` / `width_mm`
    arguments are the changes to apply. Persists via `board.save()`.
    """
    if width_mm is None and set_layer is None and set_net is None:
        raise CommandError(
            "nothing_to_do",
            "Specify at least one change: --width, --set-layer, or --set-net.",
        )
    assert_board_is(expected_pcb)
    board = get_board()
    tracks = _match_tracks(board, net, from_mm, to_mm, layer)

    new_net = None
    if set_net is not None:
        nets = {n.name: n for n in board.get_nets()}
        if set_net not in nets:
            raise LookupError(f"Net {set_net!r} not found on board")
        new_net = nets[set_net]
    new_layer = _layer_enum(set_layer) if set_layer is not None else None

    for t in tracks:
        if width_mm is not None:
            t.width = _mm_to_nm(width_mm)
        if new_layer is not None:
            t.layer = new_layer
        if new_net is not None:
            t.net = new_net
    board.update_items(tracks)
    board.save()
    return {"modified": [_track_summary(t) for t in tracks], "count": len(tracks)}


def add_via(
    expected_pcb: _Path,
    net_name: str,
    at_mm: tuple[float, float],
    diameter_mm: float = 0.6,
    drill_mm: float = 0.3,
) -> dict[str, Any]:
    """Add a through-via to the open board.

    Blind/buried vias are out of scope — they need an explicit layer pair.
    Persists via `board.save()` — see the move-fp caveat.

    Raises:
        LookupError: no net by that name exists on the board.
    """
    from kipy.board_types import Via  # type: ignore[import-untyped]
    from kipy.common_types import Vector2  # type: ignore[import-untyped]

    assert_board_is(expected_pcb)
    board = get_board()
    nets = {n.name: n for n in board.get_nets()}
    if net_name not in nets:
        raise LookupError(f"Net {net_name!r} not found on board")

    via = Via()
    via.position = Vector2.from_xy(_mm_to_nm(at_mm[0]), _mm_to_nm(at_mm[1]))
    via.net = nets[net_name]
    via.diameter = _mm_to_nm(diameter_mm)
    via.drill_diameter = _mm_to_nm(drill_mm)
    board.create_items([via])
    board.save()
    return {
        "net": net_name,
        "at_mm": [at_mm[0], at_mm[1]],
        "diameter_mm": diameter_mm,
        "drill_mm": drill_mm,
    }


def add_zone(
    expected_pcb: _Path,
    net_name: str,
    layer: str,
    rect_mm: tuple[float, float, float, float],
    priority: int = 0,
    clearance_mm: float | None = None,
) -> dict[str, Any]:
    """Add a rectangular copper-pour zone to the open board.

    `rect_mm` is (x1, y1, x2, y2) — two opposite corners in mm. The zone is
    created, then KiCad refills all zones. Arbitrary (non-rectangular)
    outlines are out of scope. Persists via `board.save()`.

    Raises:
        LookupError: no net by that name exists on the board.
    """
    from kipy.board_types import Zone  # type: ignore[import-untyped]
    from kipy.geometry import (  # type: ignore[import-untyped]
        PolygonWithHoles,
        PolyLine,
        PolyLineNode,
    )

    assert_board_is(expected_pcb)
    board = get_board()
    nets = {n.name: n for n in board.get_nets()}
    if net_name not in nets:
        raise LookupError(f"Net {net_name!r} not found on board")

    x1, y1, x2, y2 = (_mm_to_nm(v) for v in rect_mm)
    outline = PolyLine()
    for x, y in ((x1, y1), (x2, y1), (x2, y2), (x1, y2)):
        outline.append(PolyLineNode.from_xy(x, y))
    outline.closed = True
    poly = PolygonWithHoles()
    poly.outline = outline

    zone = Zone()
    zone.outline = poly
    zone.layers = [_layer_enum(layer)]
    zone.net = nets[net_name]
    zone.priority = priority
    if clearance_mm is not None:
        zone.clearance = _mm_to_nm(clearance_mm)

    board.create_items([zone])
    board.refill_zones()
    board.save()
    return {
        "net": net_name,
        "layer": layer,
        "rect_mm": list(rect_mm),
        "priority": priority,
    }


def delete_zones(
    expected_pcb: _Path,
    net: str | None = None,
    layer: str | None = None,
) -> dict[str, Any]:
    """Delete copper zones from the open board.

    Zones have no endpoints — select by `net` and/or `layer` (at least
    one). Remaining zones are refilled. Persists via `board.save()`.

    Raises:
        CommandError(code="bad_selector"): neither selector was given.
        CommandError(code="not_found"): nothing matched.
    """
    if net is None and layer is None:
        raise CommandError(
            "bad_selector", "Specify --net and/or --layer to pick zones."
        )
    assert_board_is(expected_pcb)
    board = get_board()
    want_layer = _layer_enum(layer) if layer is not None else None

    matched = []
    for zone in board.get_zones():
        if net is not None and _zone_net_name(zone) != net:
            continue
        if want_layer is not None and want_layer not in list(zone.layers):
            continue
        matched.append(zone)

    if not matched:
        raise CommandError("not_found", "No zone matched the given selectors.")
    deleted = [_zone_summary(z) for z in matched]
    board.remove_items(matched)
    board.refill_zones()
    board.save()
    return {"deleted": deleted, "count": len(deleted)}


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
            lambda: f"{fp.definition.id.library}:{fp.definition.id.name}", ""
        ),
        "layer": _safe(lambda: _layer_name(fp.layer), ""),
        "x_mm": _safe(lambda: _nm_to_mm(fp.position.x), 0.0),
        "y_mm": _safe(lambda: _nm_to_mm(fp.position.y), 0.0),
        "rotation_deg": _safe(lambda: float(fp.orientation.degrees), 0.0),
        "do_not_populate": _safe(lambda: bool(fp.attributes.do_not_populate), False),
    }


def _pad_to_dict(pad: Any, footprint_ref: str) -> dict[str, Any]:
    """Serialize a kipy Pad into a plain dict, tagged with its footprint ref."""
    return {
        "footprint": footprint_ref,
        "pad": _safe(lambda: pad.number, ""),
        "type": _safe(lambda: _pad_type_name(pad.pad_type), ""),
        "x_mm": _safe(lambda: _nm_to_mm(pad.position.x), 0.0),
        "y_mm": _safe(lambda: _nm_to_mm(pad.position.y), 0.0),
    }


def _pad_type_name(pad_type: Any) -> str:
    """Human name for a kipy PadType enum value (e.g. `"PT_SMD"`).

    Defensive like `_layer_name`: kipy surfaces the type as a proto enum
    whose `str()` is just the int. Resolve via the enum's `Name()`; fall
    back to the raw value rather than crashing mid-serialization.
    """
    try:
        from kipy.board_types import PadType  # type: ignore[import-untyped]
        return str(PadType.Name(int(pad_type)))
    except Exception:
        return str(pad_type)


def _net_name(item: Any) -> str:
    try:
        return item.net.name
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


# Endpoint-match tolerance for track selection (nm) — forgiving of
# human-entered coordinates, far below any real track geometry.
_TRACK_MATCH_TOL_NM = 50_000


def _layer_enum(name: str) -> int:
    """Resolve a KiCad layer name (`"F.Cu"`) to its kipy BoardLayer enum value.

    The inverse of `_layer_name`. Accepts every layer string kcd commands
    emit or kipy errors mention: the canonical KiCad form (`F.Cu`), the
    underscore form (`F_Cu`), and kipy's own proto form (`BL_F_Cu`). So a
    layer read off one command (`net of` / `track delete` emit `F.Cu`) can
    be fed straight into another without a translation step.

    Raises:
        CommandError(code="bad_layer"): the name resolves to no known layer.
    """
    try:
        from kipy.proto.board.board_types_pb2 import BoardLayer  # type: ignore[import-untyped]
        raw = name.strip()
        proto = raw if raw.startswith("BL_") else "BL_" + raw.replace(".", "_")
        return int(BoardLayer.Value(proto))
    except (ImportError, ValueError) as e:
        raise CommandError(
            "bad_layer",
            f"Unknown board layer {name!r}. Use the dotted KiCad form — "
            "copper layers are 'F.Cu', 'B.Cu', and 'In1.Cu'…'In30.Cu'.",
        ) from e


def _pt_near(point: Any, xy_nm: tuple[int, int]) -> bool:
    """True if a kipy point is within tolerance of an (x, y) nm pair."""
    return (
        abs(int(point.x) - xy_nm[0]) <= _TRACK_MATCH_TOL_NM
        and abs(int(point.y) - xy_nm[1]) <= _TRACK_MATCH_TOL_NM
    )


def _track_endpoints_match(
    track: Any, from_nm: tuple[int, int], to_nm: tuple[int, int]
) -> bool:
    """True if a track's two endpoints match `from`/`to` in either direction."""
    s, e = track.start, track.end
    return (_pt_near(s, from_nm) and _pt_near(e, to_nm)) or (
        _pt_near(s, to_nm) and _pt_near(e, from_nm)
    )


def _match_tracks(
    board: Any,
    net: str | None,
    from_mm: tuple[float, float] | None,
    to_mm: tuple[float, float] | None,
    layer: str | None,
) -> list[Any]:
    """Select tracks on the open board for delete/modify.

    `from_mm` + `to_mm` → the segment(s) whose endpoints match (either
    direction); `net` alone → every track on that net; `layer` further
    filters either case.

    Raises:
        CommandError(code="bad_selector"): selectors are missing or partial.
        CommandError(code="not_found"): nothing matched.
    """
    if (from_mm is None) != (to_mm is None):
        raise CommandError(
            "bad_selector", "--from and --to must be given together."
        )
    if from_mm is None and net is None:
        raise CommandError(
            "bad_selector",
            "Specify --net (whole net) or --from/--to (one segment).",
        )

    tracks = list(board.get_tracks())
    if net is not None:
        tracks = [t for t in tracks if _net_name(t) == net]
    if layer is not None:
        want = _layer_enum(layer)
        tracks = [t for t in tracks if int(t.layer) == want]
    if from_mm is not None and to_mm is not None:
        from_nm = (_mm_to_nm(from_mm[0]), _mm_to_nm(from_mm[1]))
        to_nm = (_mm_to_nm(to_mm[0]), _mm_to_nm(to_mm[1]))
        tracks = [t for t in tracks if _track_endpoints_match(t, from_nm, to_nm)]

    if not tracks:
        raise CommandError("not_found", "No track matched the given selectors.")
    return tracks


def _track_summary(track: Any) -> dict[str, Any]:
    """Serialize a kipy Track/ArcTrack into a plain dict (cf. `list_tracks`)."""
    return {
        "net": _net_name(track),
        "layer": _layer_name(track.layer),
        "width_mm": _nm_to_mm(track.width),
        "start": {"x_mm": _nm_to_mm(track.start.x), "y_mm": _nm_to_mm(track.start.y)},
        "end": {"x_mm": _nm_to_mm(track.end.x), "y_mm": _nm_to_mm(track.end.y)},
    }


def _zone_net_name(zone: Any) -> str:
    """Net name of a copper zone, or "" for rule areas / on any error."""
    try:
        return zone.net.name if zone.net is not None else ""
    except Exception:
        return ""


def _zone_summary(zone: Any) -> dict[str, Any]:
    """Serialize a kipy Zone into a plain dict."""
    return {
        "net": _zone_net_name(zone),
        "name": _safe(lambda: zone.name, ""),
        "layers": _safe(lambda: [_layer_name(la) for la in zone.layers], []),
        "priority": _safe(lambda: zone.priority, 0),
    }
