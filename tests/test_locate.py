"""Tests for `skip_sch.locate` — hierarchical sheet lookup (Dove #20).

Builds minimal hierarchical project fixtures and validates that a symbol on
a sub-sheet is reachable via `locate(proj, reference)`, the inspect/edit
plumbing's core primitive for multi-sheet designs.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from kcd.adapters import skip_sch
from kcd.core.project import resolve


_ROOT_WITH_ONE_SYMBOL = textwrap.dedent("""
(kicad_sch
\t(version 20231120)
\t(generator "eeschema")
\t(uuid "root-uuid")
\t(paper "A4")
\t(lib_symbols)
\t(symbol
\t\t(lib_id "Device:R")
\t\t(at 100 100 0)
\t\t(unit 1)
\t\t(uuid "r1-uuid")
\t\t(property "Reference" "R1" (at 100 95 0))
\t\t(property "Value" "10k" (at 100 105 0))
\t\t(property "Footprint" "" (at 100 100 0))
\t\t(property "Datasheet" "" (at 100 100 0))
\t)
\t(sheet
\t\t(uuid "sub-inst")
\t\t(property "Sheetname" "subpage")
\t\t(property "Sheetfile" "sub.kicad_sch")
\t)
)
""").strip()


_SUB_WITH_C7 = textwrap.dedent("""
(kicad_sch
\t(version 20231120)
\t(generator "eeschema")
\t(uuid "sub-file-uuid")
\t(paper "A4")
\t(lib_symbols)
\t(symbol
\t\t(lib_id "Device:C")
\t\t(at 50 50 0)
\t\t(unit 1)
\t\t(uuid "c7-uuid")
\t\t(property "Reference" "C7" (at 50 45 0))
\t\t(property "Value" "100n" (at 50 55 0))
\t\t(property "Footprint" "" (at 50 50 0))
\t\t(property "Datasheet" "" (at 50 50 0))
\t)
)
""").strip()


@pytest.fixture
def hierarchical_proj(tmp_path: Path):
    """A two-sheet project: root holds R1, sub-sheet holds C7."""
    (tmp_path / "demo.kicad_pro").write_text(json.dumps({
        "sheets": [
            ["root-uuid", "Root"],
            ["sub-inst", "subpage"],
        ]
    }))
    (tmp_path / "demo.kicad_sch").write_text(_ROOT_WITH_ONE_SYMBOL)
    (tmp_path / "sub.kicad_sch").write_text(_SUB_WITH_C7)
    return resolve(tmp_path)


def test_locate_finds_symbol_on_root(hierarchical_proj) -> None:
    """R1 lives on the root sheet → locate returns root's .kicad_sch + the
    .kicad_pro display name for page 1 ("Root" in this fixture)."""
    sheet_path, sheet_name = skip_sch.locate(hierarchical_proj, "R1")
    assert sheet_path == hierarchical_proj.root / "demo.kicad_sch"
    assert sheet_name == "Root"


def test_locate_uses_root_default_when_pro_name_empty(tmp_path: Path) -> None:
    """When the .kicad_pro root entry has no display name, locate falls back to "root"."""
    (tmp_path / "demo.kicad_pro").write_text(json.dumps({
        "sheets": [["root-uuid", ""]]
    }))
    (tmp_path / "demo.kicad_sch").write_text(_ROOT_WITH_ONE_SYMBOL)
    proj = resolve(tmp_path)
    _, sheet_name = skip_sch.locate(proj, "R1")
    assert sheet_name == "root"


def test_locate_finds_symbol_on_subsheet(hierarchical_proj) -> None:
    """C7 lives on the sub-sheet → locate returns sub's .kicad_sch + display name.

    This is the regression for Dove #20: previously inspect/edit only looked
    at proj.sch and reported C7 as missing.
    """
    sheet_path, sheet_name = skip_sch.locate(hierarchical_proj, "C7")
    assert sheet_path == hierarchical_proj.root / "sub.kicad_sch"
    assert sheet_name == "subpage"


def test_locate_raises_for_missing_symbol(hierarchical_proj) -> None:
    """A reference not on any sheet raises `SymbolNotFound` with a project-wide
    message. The exception subclasses `LookupError` so the run_command envelope
    classifies it as `error.code: "not_found"` (Dove session-4 #23)."""
    with pytest.raises(skip_sch.SymbolNotFound, match="any sheet") as exc_info:
        skip_sch.locate(hierarchical_proj, "Q99")
    assert isinstance(exc_info.value, LookupError)
    assert not isinstance(exc_info.value, skip_sch.SchEditError)


def test_list_symbols_all_aggregates_across_sheets(hierarchical_proj) -> None:
    """list_symbols_all returns both root + sub-sheet symbols, each tagged."""
    syms = skip_sch.list_symbols_all(hierarchical_proj)
    by_ref = {s["reference"]: s for s in syms}
    assert "R1" in by_ref
    assert "C7" in by_ref
    assert by_ref["R1"]["sheet"] == "Root"
    assert by_ref["C7"]["sheet"] == "subpage"


def test_list_symbols_all_falls_through_orphan_sheets(tmp_path: Path) -> None:
    """Sheets with file=None (orphan UUIDs) are skipped silently, not errored."""
    (tmp_path / "demo.kicad_pro").write_text(json.dumps({
        "sheets": [
            ["root-uuid", "Root"],
            ["orphan-uuid", "missing"],
        ]
    }))
    (tmp_path / "demo.kicad_sch").write_text(_ROOT_WITH_ONE_SYMBOL)
    proj = resolve(tmp_path)
    # Should aggregate the root sheet's R1 without crashing on the orphan entry.
    syms = skip_sch.list_symbols_all(proj)
    refs = {s["reference"] for s in syms}
    assert "R1" in refs
