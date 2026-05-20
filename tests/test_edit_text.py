"""Tests for `kcd edit text` — title block + free graphic text (Wave 7 B).

The command layer runs through the Typer `text_app`; `set_titleblock_field`
and `set_text`, the raw-S-expr mutators, are also unit-tested directly on
hand-built minimal `.kicad_sch` files.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kcd.adapters import skip_sch
from kcd.adapters.skip_sch import SchEditError
from kcd.commands.edit import text_app
from kcd.core import sexp

_NET_FIXTURE = Path(__file__).parent / "fixtures" / "net"


def _min_sch(path: Path, body: str = "") -> None:
    """Write a minimal but parseable `.kicad_sch` with `body` spliced in."""
    path.write_text(
        "(kicad_sch\n"
        "\t(version 20231120)\n"
        '\t(generator "test")\n'
        '\t(paper "A4")\n'
        f"{body}"
        "\t(lib_symbols)\n"
        ")\n"
    )


def _title_block(path: Path) -> list:
    return next(
        n for n in sexp.parse(path.read_text())
        if isinstance(n, list) and n and n[0] == "title_block"
    )


@pytest.fixture
def proj_dir(tmp_path: Path) -> Path:
    """A project with the real net_fixture sch (no title_block, no text)."""
    for ext in ("kicad_pro", "kicad_sch"):
        (tmp_path / f"net_fixture.{ext}").write_text(
            (_NET_FIXTURE / f"net_fixture.{ext}").read_text()
        )
    return tmp_path


# ---------------------------------------------------------------------------
# edit text titleblock — command layer
# ---------------------------------------------------------------------------

def test_titleblock_create_when_absent(proj_dir: Path) -> None:
    """net_fixture has no title_block — the command must create one."""
    r = CliRunner().invoke(
        text_app,
        ["titleblock", str(proj_dir), "--field", "title", "--value",
         "My Board", "--no-snapshot", "--no-render", "--json"],
    )
    assert r.exit_code == 0, r.stdout
    out = json.loads(r.stdout)
    assert out["ok"] is True
    assert out["command"] == "edit.text.titleblock"
    assert out["data"]["updated"]["field"] == "title"
    assert out["data"]["updated"]["before"] is None

    tb = _title_block(proj_dir / "net_fixture.kicad_sch")
    title = next(c for c in tb if isinstance(c, list) and c[0] == "title")
    assert title[1] == "My Board"


def test_titleblock_comment(proj_dir: Path) -> None:
    r = CliRunner().invoke(
        text_app,
        ["titleblock", str(proj_dir), "--field", "comment3", "--value",
         "Reviewed", "--no-snapshot", "--no-render", "--json"],
    )
    assert r.exit_code == 0, r.stdout
    out = json.loads(r.stdout)
    assert out["data"]["updated"]["field"] == "comment3"

    tb = _title_block(proj_dir / "net_fixture.kicad_sch")
    comment = next(
        c for c in tb
        if isinstance(c, list) and c[0] == "comment" and str(c[1]) == "3"
    )
    assert comment[2] == "Reviewed"


def test_titleblock_bad_field(proj_dir: Path) -> None:
    r = CliRunner().invoke(
        text_app,
        ["titleblock", str(proj_dir), "--field", "bogus", "--value", "x",
         "--no-snapshot", "--no-render", "--json"],
    )
    assert r.exit_code == 1
    assert json.loads(r.stdout)["error"]["code"] == "bad_field"


# ---------------------------------------------------------------------------
# edit text set — command layer
# ---------------------------------------------------------------------------

def test_text_set_envelope(tmp_path: Path) -> None:
    (tmp_path / "p.kicad_pro").write_text("{}")
    _min_sch(tmp_path / "p.kicad_sch", '\t(text "Draft"\n\t\t(at 50 50 0)\n\t)\n')
    r = CliRunner().invoke(
        text_app,
        ["set", str(tmp_path), "--match", "Draft", "--to", "Final",
         "--no-snapshot", "--no-render", "--json"],
    )
    assert r.exit_code == 0, r.stdout
    out = json.loads(r.stdout)
    assert out["command"] == "edit.text.set"
    assert out["data"]["updated"][0]["after"] == "Final"
    assert "Final" in (tmp_path / "p.kicad_sch").read_text()


# ---------------------------------------------------------------------------
# set_titleblock_field — adapter
# ---------------------------------------------------------------------------

def test_set_titleblock_update_existing(tmp_path: Path) -> None:
    sch = tmp_path / "s.kicad_sch"
    _min_sch(sch, '\t(title_block\n\t\t(title "Old Title")\n\t)\n')
    result = skip_sch.set_titleblock_field(sch, "title", "New Title")
    assert result["before"] == "Old Title"
    assert result["field"] == "title"

    title = next(c for c in _title_block(sch) if isinstance(c, list) and c[0] == "title")
    assert title[1] == "New Title"


# ---------------------------------------------------------------------------
# set_text — adapter
# ---------------------------------------------------------------------------

def test_set_text_match(tmp_path: Path) -> None:
    sch = tmp_path / "s.kicad_sch"
    _min_sch(sch, '\t(text "Hello"\n\t\t(at 10 10 0)\n\t)\n')
    result = skip_sch.set_text(sch, "Hello", "World")
    assert len(result["updated"]) == 1
    assert result["updated"][0]["after"] == "World"
    assert "World" in sch.read_text()


def test_set_text_ambiguous(tmp_path: Path) -> None:
    sch = tmp_path / "s.kicad_sch"
    _min_sch(
        sch,
        '\t(text "Dup"\n\t\t(at 10 10 0)\n\t)\n'
        '\t(text "Dup"\n\t\t(at 20 20 0)\n\t)\n',
    )
    with pytest.raises(SchEditError, match="pass --at"):
        skip_sch.set_text(sch, "Dup", "X")


def test_set_text_at_disambiguates(tmp_path: Path) -> None:
    sch = tmp_path / "s.kicad_sch"
    _min_sch(
        sch,
        '\t(text "Dup"\n\t\t(at 10 10 0)\n\t)\n'
        '\t(text "Dup"\n\t\t(at 20 20 0)\n\t)\n',
    )
    result = skip_sch.set_text(sch, "Dup", "Picked", at=(20.0, 20.0))
    assert len(result["updated"]) == 1
    assert result["updated"][0]["at"] == [20.0, 20.0]


def test_set_text_no_match(tmp_path: Path) -> None:
    sch = tmp_path / "s.kicad_sch"
    _min_sch(sch, '\t(text "Hello"\n\t\t(at 10 10 0)\n\t)\n')
    with pytest.raises(SchEditError, match="No text"):
        skip_sch.set_text(sch, "Nope", "X")
