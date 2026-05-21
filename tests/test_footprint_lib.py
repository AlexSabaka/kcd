"""Tests for the footprint-library adapter (Round-7).

`footprint_lib.resolve_footprint` resolves a `Library:Footprint` id to its
`.kicad_mod` definition — via the project `fp-lib-table` or KiCad's standard
footprint directory. The fixture dir under `tests/fixtures/pcb/` doubles as
both the project (it has an `fp-lib-table`) and — via `KCD_FOOTPRINT_DIR` —
the standard footprint directory, so nothing here needs a real KiCad install.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kcd.adapters import footprint_lib
from kcd.core.output import CommandError
from kcd.core.project import resolve

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "pcb"


@pytest.fixture
def proj():
    """The fixture project (its dir holds an fp-lib-table + demo.pretty/)."""
    return resolve(FIXTURE_DIR)


def test_resolve_footprint_via_project_table(proj) -> None:
    """`Demo` resolves through the project fp-lib-table + ${KIPRJMOD}."""
    info = footprint_lib.resolve_footprint("Demo:R_0805", proj)
    assert info["library"] == "Demo"
    assert info["name"] == "R_0805"
    assert info["pads"] == {"1", "2"}
    assert info["definition"][0] == "footprint"
    assert info["source_file"].endswith("R_0805.kicad_mod")


def test_resolve_footprint_three_pad_part(proj) -> None:
    info = footprint_lib.resolve_footprint("Demo:SOT-23", proj)
    assert info["pads"] == {"1", "2", "3"}


def test_resolve_footprint_via_footprint_dir(monkeypatch) -> None:
    """With KCD_FOOTPRINT_DIR at the fixture dir, a bare nickname resolves
    <dir>/<nickname>.pretty/<name>.kicad_mod — no project table needed."""
    monkeypatch.setenv("KCD_FOOTPRINT_DIR", str(FIXTURE_DIR))
    info = footprint_lib.resolve_footprint("demo:R_0603")
    assert info["name"] == "R_0603"
    assert info["pads"] == {"1", "2"}


def test_resolve_footprint_invalid_lib_id(proj) -> None:
    with pytest.raises(CommandError) as exc:
        footprint_lib.resolve_footprint("NoColonHere", proj)
    assert exc.value.code == "invalid_lib_id"


def test_resolve_footprint_missing_footprint(proj) -> None:
    with pytest.raises(FileNotFoundError):
        footprint_lib.resolve_footprint("Demo:Ghost", proj)


def test_resolve_footprint_missing_library(proj) -> None:
    with pytest.raises(FileNotFoundError):
        footprint_lib.resolve_footprint("NoSuchLib:R_0805", proj)


def test_pad_numbers_collapses_duplicates() -> None:
    """`pad_numbers` is a set — duplicate pad numbers (one electrical node
    split across pads) collapse, and unnumbered mechanical pads carry ``""``."""
    fp = ["footprint", "X",
          ["pad", "1", "smd"], ["pad", "1", "smd"],
          ["pad", "2", "smd"], ["pad", "", "np_thru_hole"]]
    assert footprint_lib.pad_numbers(fp) == {"1", "2", ""}
