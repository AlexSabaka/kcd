"""Tests for `skip_sch.sheet_index` and `snapshot_sheet_mtimes` (Dove #13).

These verify the file→page→SVG mapping that drives per-sheet artifact
attribution in `_post_edit_sch`. Fixtures use minimal in-memory project
trees — no KiCad install needed.
"""

from __future__ import annotations

import json
import textwrap
import time
from pathlib import Path

from kcd.adapters import skip_sch
from kcd.core.project import resolve


def _make_proj(tmp_path: Path, pro_json: dict, sch_files: dict[str, str]):
    """Build a project tree with the given .kicad_pro contents + named .kicad_sch files."""
    pro_path = tmp_path / "demo.kicad_pro"
    pro_path.write_text(json.dumps(pro_json))
    for name, content in sch_files.items():
        (tmp_path / name).write_text(content)
    return resolve(tmp_path)


def test_sheet_index_single_sheet_project(tmp_path: Path) -> None:
    """Single-sheet project: page 1 = root, no sub-sheets."""
    proj = _make_proj(
        tmp_path,
        {"sheets": [["root-uuid", "Root"]]},
        {"demo.kicad_sch": '(kicad_sch (uuid "root-uuid"))'},
    )
    index = skip_sch.sheet_index(proj)
    assert len(index) == 1
    assert index[0]["page"] == 1
    assert index[0]["uuid"] == "root-uuid"
    assert index[0]["file"] == tmp_path / "demo.kicad_sch"
    assert index[0]["svg_filename"] == "demo.svg"


def test_sheet_index_hierarchical_project(tmp_path: Path) -> None:
    """Multi-sheet project: page 1 = root, pages 2+ = sub-sheets keyed by .kicad_pro UUIDs."""
    root_content = textwrap.dedent("""
    (kicad_sch
      (uuid "root-file-uuid")
      (sheet
        (uuid "sub-inst-1")
        (property "Sheetname" "sub_a")
        (property "Sheetfile" "sub_a.kicad_sch")
      )
      (sheet
        (uuid "sub-inst-2")
        (property "Sheetname" "sub_b")
        (property "Sheetfile" "sub_b.kicad_sch")
      )
    )
    """).strip()
    proj = _make_proj(
        tmp_path,
        {"sheets": [
            ["root-file-uuid", "Root"],
            ["sub-inst-1", "sub_a"],
            ["sub-inst-2", "sub_b"],
        ]},
        {
            "demo.kicad_sch": root_content,
            "sub_a.kicad_sch": '(kicad_sch (uuid "sub-a-file-uuid"))',
            "sub_b.kicad_sch": '(kicad_sch (uuid "sub-b-file-uuid"))',
        },
    )
    index = skip_sch.sheet_index(proj)
    assert len(index) == 3
    assert index[0]["page"] == 1
    assert index[0]["file"] == tmp_path / "demo.kicad_sch"
    assert index[0]["svg_filename"] == "demo.svg"
    assert index[1]["page"] == 2
    assert index[1]["file"] == tmp_path / "sub_a.kicad_sch"
    assert index[1]["svg_filename"] == "demo-sub_a.svg"
    assert index[2]["page"] == 3
    assert index[2]["file"] == tmp_path / "sub_b.kicad_sch"
    assert index[2]["svg_filename"] == "demo-sub_b.svg"


def test_sheet_index_reused_subsheet_file(tmp_path: Path) -> None:
    """The same .kicad_sch can be used by two sheet instances — both map to that file.

    This is the complex_hierarchy demo case: ampli_ht.kicad_sch is referenced
    by both ampli_ht_vertical and ampli_ht_horizontal instances. A write to
    that one file should attribute SVGs for both pages.
    """
    root_content = textwrap.dedent("""
    (kicad_sch
      (uuid "root-uuid")
      (sheet
        (uuid "vert-inst")
        (property "Sheetname" "ampli_vert")
        (property "Sheetfile" "ampli_ht.kicad_sch")
      )
      (sheet
        (uuid "horiz-inst")
        (property "Sheetname" "ampli_horiz")
        (property "Sheetfile" "ampli_ht.kicad_sch")
      )
    )
    """).strip()
    proj = _make_proj(
        tmp_path,
        {"sheets": [
            ["root-uuid", "Root"],
            ["vert-inst", "ampli_vert"],
            ["horiz-inst", "ampli_horiz"],
        ]},
        {
            "demo.kicad_sch": root_content,
            "ampli_ht.kicad_sch": '(kicad_sch (uuid "ampli-file-uuid"))',
        },
    )
    index = skip_sch.sheet_index(proj)
    assert len(index) == 3
    ampli_path = tmp_path / "ampli_ht.kicad_sch"
    # Both sub-pages point at the same .kicad_sch file
    assert index[1]["file"] == ampli_path
    assert index[2]["file"] == ampli_path
    assert index[1]["svg_filename"] == "demo-ampli_vert.svg"
    assert index[2]["svg_filename"] == "demo-ampli_horiz.svg"


def test_sheet_index_missing_pro_falls_back(tmp_path: Path) -> None:
    """No .kicad_pro: return a synthetic single-root index instead of crashing."""
    # Create .kicad_pro then delete; resolve needs it to build the Project.
    pro_path = tmp_path / "demo.kicad_pro"
    pro_path.write_text("{}")
    (tmp_path / "demo.kicad_sch").write_text("(kicad_sch)")
    proj = resolve(tmp_path)
    pro_path.unlink()

    index = skip_sch.sheet_index(proj)
    assert len(index) == 1
    assert index[0]["page"] == 1
    assert index[0]["file"] == tmp_path / "demo.kicad_sch"


def test_sheet_index_empty_sheets_array_falls_back(tmp_path: Path) -> None:
    """`.kicad_pro` with no `sheets` key (or empty) returns synthetic single-root."""
    proj = _make_proj(
        tmp_path,
        {"meta": {}},
        {"demo.kicad_sch": "(kicad_sch)"},
    )
    index = skip_sch.sheet_index(proj)
    assert len(index) == 1
    assert index[0]["svg_filename"] == "demo.svg"


def test_sheet_index_orphan_uuid_marks_file_none(tmp_path: Path) -> None:
    """A .kicad_pro entry whose UUID matches no (sheet ...) block leaves file=None."""
    proj = _make_proj(
        tmp_path,
        {"sheets": [
            ["root-uuid", "Root"],
            ["orphan-uuid", "missing"],
        ]},
        {"demo.kicad_sch": '(kicad_sch (uuid "root-uuid"))'},
    )
    index = skip_sch.sheet_index(proj)
    assert len(index) == 2
    assert index[1]["file"] is None
    # svg_filename is still composed — kicad-cli would produce this name —
    # but with file=None the post-edit attribution treats it as orphan
    # (falls back to "all changed SVGs").
    assert index[1]["svg_filename"] == "demo-missing.svg"


def test_snapshot_sheet_mtimes_captures_all_sch_files(tmp_path: Path) -> None:
    """`snapshot_sheet_mtimes` returns ns mtimes for every .kicad_sch in root."""
    proj = _make_proj(
        tmp_path,
        {"sheets": [["r", "Root"]]},
        {
            "demo.kicad_sch": "(kicad_sch)",
            "sub.kicad_sch": "(kicad_sch)",
        },
    )
    mtimes = skip_sch.snapshot_sheet_mtimes(proj)
    assert set(mtimes.keys()) == {tmp_path / "demo.kicad_sch", tmp_path / "sub.kicad_sch"}
    assert all(isinstance(v, int) and v > 0 for v in mtimes.values())


def test_snapshot_sheet_mtimes_detects_changes(tmp_path: Path) -> None:
    """An mtime captured pre-edit must differ from post-edit after a rewrite."""
    proj = _make_proj(
        tmp_path,
        {"sheets": [["r", "Root"]]},
        {"demo.kicad_sch": "(kicad_sch original)"},
    )
    before = skip_sch.snapshot_sheet_mtimes(proj)
    time.sleep(0.01)  # ensure ns clock moves
    (tmp_path / "demo.kicad_sch").write_text("(kicad_sch modified)")
    after = skip_sch.snapshot_sheet_mtimes(proj)
    assert after[tmp_path / "demo.kicad_sch"] > before[tmp_path / "demo.kicad_sch"]
