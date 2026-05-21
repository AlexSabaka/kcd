"""Tests for the symbol-library adapter and `kcd lib` command.

Hermetic: the fixture dir under `tests/fixtures/lib/` doubles as both the
project (it has a `sym-lib-table`) and — via `KCD_SYMBOL_DIR` — the standard
symbol directory, so nothing here depends on a real KiCad install.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from kcd.adapters import symbol_lib
from kcd.commands.lib import list_libs, show
from kcd.core.output import CommandError
from kcd.core.project import resolve

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "lib"

_show_app = typer.Typer()
_show_app.command()(show)
_list_app = typer.Typer()
_list_app.command()(list_libs)


@pytest.fixture
def proj():
    """The fixture project (its dir holds a sym-lib-table + mylib.kicad_sym)."""
    return resolve(FIXTURE_DIR)


# ---------------------------------------------------------------------------
# find_symbol
# ---------------------------------------------------------------------------

def test_find_symbol_via_project_table(proj) -> None:
    """`MyLib` resolves through the project sym-lib-table + ${KIPRJMOD}."""
    info = symbol_lib.find_symbol("MyLib:R", proj)
    assert info["library"] == "MyLib"
    assert info["name"] == "R"
    assert [p["number"] for p in info["pins"]] == ["1", "2"]
    assert info["properties"]["Description"] == "Resistor"


def test_find_symbol_three_pin_part(proj) -> None:
    """Pin names and electrical type come through for a multi-pin symbol."""
    info = symbol_lib.find_symbol("MyLib:Q_NPN", proj)
    assert [(p["number"], p["name"]) for p in info["pins"]] == [
        ("1", "B"), ("2", "C"), ("3", "E"),
    ]
    assert info["pins"][0]["type"] == "input"


def test_find_symbol_via_symbol_dir(monkeypatch) -> None:
    """With KCD_SYMBOL_DIR at the fixture dir, a bare nickname resolves
    <dir>/<nickname>.kicad_sym — no project table needed."""
    monkeypatch.setenv("KCD_SYMBOL_DIR", str(FIXTURE_DIR))
    info = symbol_lib.find_symbol("mylib:R")
    assert info["name"] == "R"
    assert info["source_file"].endswith("mylib.kicad_sym")


def test_find_symbol_resolves_extends_pins(proj) -> None:
    """A derived symbol inherits its pins from the base it extends — the
    field-report case that returned `pins: []` for every regulator variant
    (Round-6)."""
    info = symbol_lib.find_symbol("MyLib:AP2112K-3.3", proj)
    assert [p["number"] for p in info["pins"]] == ["1", "2", "3", "5"]
    assert [p["name"] for p in info["pins"]] == ["VIN", "GND", "EN", "VOUT"]


def test_find_symbol_extends_merges_properties(proj) -> None:
    """Derived-symbol properties override the base; un-overridden base
    properties are inherited."""
    info = symbol_lib.find_symbol("MyLib:AP2112K-3.3", proj)
    assert info["properties"]["Value"] == "AP2112K-3.3"   # overridden
    assert info["properties"]["Reference"] == "U"         # inherited from base
    assert "3v3" in info["properties"]["Datasheet"]       # overridden


def test_find_symbol_base_of_extends_chain_still_works(proj) -> None:
    """The base symbol of an extends chain resolves its own pins directly."""
    info = symbol_lib.find_symbol("MyLib:AP2112K-1.8", proj)
    assert [p["number"] for p in info["pins"]] == ["1", "2", "3", "5"]


def test_find_symbol_invalid_lib_id(proj) -> None:
    with pytest.raises(CommandError) as exc:
        symbol_lib.find_symbol("NoColonHere", proj)
    assert exc.value.code == "invalid_lib_id"


def test_find_symbol_missing_symbol(proj) -> None:
    with pytest.raises(LookupError):
        symbol_lib.find_symbol("MyLib:Ghost", proj)


def test_find_symbol_missing_library(proj) -> None:
    with pytest.raises(FileNotFoundError):
        symbol_lib.find_symbol("NoSuchLib:R", proj)


def test_definition_is_embeddable(proj) -> None:
    """The returned `definition` is a parsed S-expr subtree Wave 4 can dump
    straight into a project's `lib_symbols`."""
    from kcd.core.sexp import dumps
    info = symbol_lib.find_symbol("MyLib:R", proj)
    text = dumps(info["definition"])
    assert text.startswith("(symbol")
    assert '"R"' in text


def test_list_libraries_merges_project_and_dir(proj, monkeypatch) -> None:
    monkeypatch.setenv("KCD_SYMBOL_DIR", str(FIXTURE_DIR))
    nicks = {lib["nickname"] for lib in symbol_lib.list_libraries(proj)}
    assert "MyLib" in nicks   # from the project sym-lib-table
    assert "mylib" in nicks   # from the symbol directory


# ---------------------------------------------------------------------------
# kcd lib commands
# ---------------------------------------------------------------------------

def test_lib_show_command(proj) -> None:
    runner = CliRunner()
    result = runner.invoke(
        _show_app, ["MyLib:R", "--project", str(FIXTURE_DIR), "--json"]
    )
    assert result.exit_code == 0, result.stdout
    out = json.loads(result.stdout)
    assert out["ok"] is True
    assert out["command"] == "lib.show"
    assert len(out["data"]["pins"]) == 2
    # the raw `definition` tree stays out of the user-facing envelope
    assert "definition" not in out["data"]


def test_lib_show_invalid_id() -> None:
    runner = CliRunner()
    result = runner.invoke(_show_app, ["NoColon", "--json"])
    assert result.exit_code == 1
    out = json.loads(result.stdout)
    assert out["ok"] is False
    assert out["error"]["code"] == "invalid_lib_id"


def test_lib_list_command(proj, monkeypatch) -> None:
    monkeypatch.setenv("KCD_SYMBOL_DIR", str(FIXTURE_DIR))
    runner = CliRunner()
    result = runner.invoke(
        _list_app, ["--project", str(FIXTURE_DIR), "--json"]
    )
    assert result.exit_code == 0, result.stdout
    out = json.loads(result.stdout)
    assert out["data"]["count"] >= 1
    assert any(lib["nickname"] == "MyLib" for lib in out["data"]["libraries"])


# ---------------------------------------------------------------------------
# embedded-library detection (Round-3 field report B10)
# ---------------------------------------------------------------------------

def test_embedded_lib_nicknames_parses_lib_symbols(tmp_path: Path) -> None:
    (tmp_path / "d.kicad_pro").write_text("{}")
    (tmp_path / "d.kicad_sch").write_text(
        '(kicad_sch (lib_symbols '
        '(symbol "mx1508:MX1508") (symbol "Device:R")))'
    )
    proj = resolve(str(tmp_path))
    assert symbol_lib._embedded_lib_nicknames(proj) == {"mx1508", "Device"}


def test_list_libraries_includes_embedded_schematic_libs(tmp_path: Path) -> None:
    """A project-local library used only via the schematic's in-file
    `lib_symbols` block surfaces with `location: embedded`."""
    (tmp_path / "demo.kicad_pro").write_text("{}")
    (tmp_path / "demo.kicad_sch").write_text(
        '(kicad_sch (lib_symbols '
        '(symbol "mx1508:MX1508" (property "Reference" "U")) '
        '(symbol "Device:R" (property "Reference" "R"))))'
    )
    proj = resolve(str(tmp_path))
    by_nick = {lib["nickname"]: lib for lib in symbol_lib.list_libraries(proj)}
    assert by_nick["mx1508"]["location"] == "embedded"
    assert by_nick["mx1508"]["path"] == "<embedded in schematic>"
