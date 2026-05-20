"""Tests for the kipy_pcb adapter's pure helpers (no live KiCad needed).

Live-IPC paths (list_footprints, move_footprint, etc.) are exercised by
`tests/test_agentic_loop.py` (KCD_INTEGRATION=1 gated).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kcd.adapters import kipy_pcb
from kcd.adapters.kipy_pcb import _layer_enum, _layer_name, _ref_sort_key
from kcd.core.output import CommandError


def test_ref_sort_key_numeric_order() -> None:
    """R1, R2, R10 sort in numeric order, not lexicographic."""
    refs = ["R10", "R2", "R1", "R3"]
    refs.sort(key=_ref_sort_key)
    assert refs == ["R1", "R2", "R3", "R10"]


def test_ref_sort_key_groups_by_prefix() -> None:
    """All Cs land before all Rs, regardless of numeric value."""
    refs = ["R1", "C99", "C1", "R99", "U1"]
    refs.sort(key=_ref_sort_key)
    assert refs == ["C1", "C99", "R1", "R99", "U1"]


def test_ref_sort_key_handles_subreference_suffix() -> None:
    """`U4A` / `U4B` (multi-unit refs) sort after `U4` and stay grouped."""
    refs = ["U4B", "U4A", "U4", "U10"]
    refs.sort(key=_ref_sort_key)
    assert refs == ["U4", "U4A", "U4B", "U10"]


def test_ref_sort_key_handles_empty_and_malformed() -> None:
    """Refs without the standard shape sort to the bottom rather than crash."""
    refs = ["R1", "", "?", "R2"]
    refs.sort(key=_ref_sort_key)
    # Well-formed refs first, malformed at the end (stable among themselves).
    assert refs[:2] == ["R1", "R2"]
    assert set(refs[2:]) == {"", "?"}


def test_ref_sort_key_multi_letter_prefix() -> None:
    """`TP1` (test points) sort correctly relative to single-letter prefixes."""
    refs = ["TP10", "TP1", "TP2"]
    refs.sort(key=_ref_sort_key)
    assert refs == ["TP1", "TP2", "TP10"]


# ---------------------------------------------------------------------------
# _layer_enum — layer-string -> BoardLayer enum, tolerant of every form
# ---------------------------------------------------------------------------

def test_layer_enum_canonical_forms_round_trip() -> None:
    """The canonical KiCad form resolves and round-trips through `_layer_name`."""
    for name in ("F.Cu", "B.Cu", "In1.Cu"):
        assert _layer_name(_layer_enum(name)) == name


def test_layer_enum_accepts_proto_and_underscore_forms() -> None:
    """`route_track`'s old bug: only `BL_F_Cu` worked while reads emit `F.Cu`.

    All three forms must now resolve to the same enum so a layer read off one
    command can be fed straight into another.
    """
    canonical = _layer_enum("F.Cu")
    assert _layer_enum("BL_F_Cu") == canonical
    assert _layer_enum("F_Cu") == canonical


def test_layer_enum_rejects_unknown_layer() -> None:
    with pytest.raises(CommandError) as exc:
        _layer_enum("Nonsense.Cu")
    assert exc.value.code == "bad_layer"


# ---------------------------------------------------------------------------
# list_open_documents — schematic-doc path reconstruction (Dove session-5 close)
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_kicad_with_schematic_doc(monkeypatch):
    """Build a kipy `DocumentSpecifier` for an open schematic and inject it via
    `kipy_pcb.connect`. Returns ``(build, captured)``: ``build(name, path, hier)``
    constructs the proto message, ``captured["sch"] = ...`` arms the fake.

    The kipy proto's ``SheetPath.path_human_readable`` is the sheet-hierarchy
    path (``"/"``, ``"/SubA/"``), NOT the filesystem path. kcd reconstructs
    the actual ``.kicad_sch`` location from the ``ProjectSpecifier`` to match
    the board branch's shape.
    """
    from kipy.proto.common.types import (  # type: ignore[import-untyped]
        DocumentSpecifier,
        DocumentType,
        ProjectSpecifier,
        SheetPath,
    )

    def build(project_name: str | None, project_path: str | None, hier: str) -> object:
        kwargs: dict = {
            "type": DocumentType.DOCTYPE_SCHEMATIC,
            "sheet_path": SheetPath(path_human_readable=hier),
        }
        if project_name is not None or project_path is not None:
            kwargs["project"] = ProjectSpecifier(
                name=project_name or "",
                path=project_path or "",
            )
        return DocumentSpecifier(**kwargs)

    captured: dict = {"sch": None}

    class FakeKicad:
        def get_open_documents(self, doc_type):
            if doc_type == DocumentType.DOCTYPE_SCHEMATIC and captured["sch"]:
                return [captured["sch"]]
            return []

    monkeypatch.setattr(kipy_pcb, "connect", lambda: FakeKicad())
    return build, captured


def test_schematic_path_reconstructed_from_project(
    fake_kicad_with_schematic_doc, tmp_path: Path,
) -> None:
    """Schematic doc with project info → `path` is the actual .kicad_sch file
    location, NOT the sheet-hierarchy string."""
    build, captured = fake_kicad_with_schematic_doc
    captured["sch"] = build("demo", str(tmp_path), "/")

    docs = kipy_pcb.list_open_documents()
    sch_entries = [d for d in docs if d["kind"] == "schematic"]
    assert len(sch_entries) == 1
    entry = sch_entries[0]
    assert entry["path"] == str(tmp_path / "demo.kicad_sch")
    assert entry["filename"] == "demo.kicad_sch"
    assert entry["project_dir"] == str(tmp_path)
    # Hierarchy is preserved in a dedicated field so callers that want to know
    # *which sheet* the editor is focused on can still see it.
    assert entry["sheet_path"] == "/"


def test_schematic_path_handles_sub_sheet_hierarchy(
    fake_kicad_with_schematic_doc, tmp_path: Path,
) -> None:
    """Sub-sheet focused in the editor → `path` still points at the root
    `.kicad_sch` (kipy doesn't tell us which individual file is loaded);
    `sheet_path` carries the hierarchy so callers see the focus."""
    build, captured = fake_kicad_with_schematic_doc
    captured["sch"] = build("demo", str(tmp_path), "/SubA/")

    docs = kipy_pcb.list_open_documents()
    entry = next(d for d in docs if d["kind"] == "schematic")
    assert entry["path"] == str(tmp_path / "demo.kicad_sch")
    assert entry["sheet_path"] == "/SubA/"


def test_schematic_path_empty_when_project_unset(fake_kicad_with_schematic_doc) -> None:
    """Schematic doc without a project field → path falls back to empty
    rather than producing a junk string. Matches Dove session-5 observation
    when KiCad surfaces a schematic without project info."""
    build, captured = fake_kicad_with_schematic_doc
    captured["sch"] = build(None, None, "/")

    docs = kipy_pcb.list_open_documents()
    entry = next(d for d in docs if d["kind"] == "schematic")
    assert entry["path"] == ""
    assert entry["filename"] == ""
    assert entry["project_dir"] == ""
    assert entry["sheet_path"] == "/"


def test_schematic_path_empty_when_only_name_set(fake_kicad_with_schematic_doc) -> None:
    """Project name without a path → path falls back to empty (can't build
    a meaningful absolute path from name alone)."""
    build, captured = fake_kicad_with_schematic_doc
    captured["sch"] = build("demo", "", "/")

    docs = kipy_pcb.list_open_documents()
    entry = next(d for d in docs if d["kind"] == "schematic")
    assert entry["path"] == ""
    assert entry["project_dir"] == ""
