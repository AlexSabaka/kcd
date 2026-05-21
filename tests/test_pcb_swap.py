"""Tests for offline `.kicad_pcb` footprint swap (Round-7 `edit swap-fp`).

`pcb_file.swap_footprint` rewrites a placed footprint's definition in the
board S-expression, keeping the instance identity (uuid/path/position/
properties) and each pad's net. Covers the `sexp` round-trip safety, the
swap itself, the identical-pad-layout guard, and the `edit swap-fp` command.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kcd.adapters import kicad_cli, pcb_file
from kcd.commands.edit import edit_app
from kcd.core import sexp
from kcd.core.output import CommandError

FIXTURE = Path(__file__).parent / "fixtures" / "pcb"


def _copy_project(tmp_path: Path) -> Path:
    """A writable copy of the whole pcb fixture project."""
    dest = tmp_path / "proj"
    shutil.copytree(FIXTURE, dest)
    return dest


def _mod(name: str) -> list:
    return sexp.parse((FIXTURE / "demo.pretty" / f"{name}.kicad_mod").read_text())


def _children(node: list, tag: str) -> list:
    return [c for c in node if isinstance(c, list) and c and c[0] == tag]


# ---------------------------------------------------------------------------
# sexp round-trip safety — the .kicad_pcb is rewritten through sexp.dumps
# ---------------------------------------------------------------------------

def test_sexp_roundtrip_preserves_the_board() -> None:
    """parse -> dumps -> parse on the board fixture is structurally lossless."""
    once = sexp.parse((FIXTURE / "demo.kicad_pcb").read_text())
    assert sexp.parse(sexp.dumps(once)) == once


def test_sexp_roundtrip_preserves_the_kicad_mods() -> None:
    for name in ("R_0805", "R_0603", "SOT-23"):
        once = _mod(name)
        assert sexp.parse(sexp.dumps(once)) == once


# ---------------------------------------------------------------------------
# swap_footprint
# ---------------------------------------------------------------------------

def test_swap_footprint_swaps_lib_id_keeps_identity_and_nets(
    tmp_path: Path,
) -> None:
    pcb = _copy_project(tmp_path) / "demo.kicad_pcb"
    result = pcb_file.swap_footprint(pcb, "R1", "Demo:R_0603", _mod("R_0603"))

    assert result["from_footprint"] == "Demo:R_0805"
    assert result["to_footprint"] == "Demo:R_0603"
    assert result["pads_remapped"] == 2
    assert result["position"] == [100, 80, 0]

    tree = sexp.parse(pcb.read_text())          # the written board re-parses
    fp = pcb_file.find_footprint_node(tree, "R1")
    assert fp is not None
    assert str(fp[1]) == "Demo:R_0603"          # lib-id swapped

    # instance identity preserved verbatim
    assert _children(fp, "uuid")[0][1] == "11111111-1111-1111-1111-111111111111"
    assert _children(fp, "path")[0][1] == "/00000000-0000-0000-0000-0000000000a1"
    assert [str(v) for v in _children(fp, "at")[0][1:]] == ["100", "80", "0"]

    props = {p[1]: p for p in _children(fp, "property")}
    assert props["Reference"][2] == "R1"        # kept
    assert props["Value"][2] == "10k"           # kept
    assert props["Footprint"][2] == "Demo:R_0603"   # follows the swap

    # pads keep their nets but take the new 0603 geometry
    pads = {p[1]: p for p in _children(fp, "pad")}
    assert set(pads) == {"1", "2"}
    assert _children(pads["1"], "net")[0][1:] == ["1", "GND"]
    assert _children(pads["2"], "net")[0][1:] == ["2", "VCC"]
    assert [str(v) for v in _children(pads["1"], "size")[0][1:]] == ["0.875", "0.95"]


def test_swap_footprint_rejects_pad_set_mismatch(tmp_path: Path) -> None:
    """A footprint with a different pad-number set is refused."""
    pcb = _copy_project(tmp_path) / "demo.kicad_pcb"
    with pytest.raises(CommandError) as exc:
        pcb_file.swap_footprint(pcb, "R1", "Demo:SOT-23", _mod("SOT-23"))
    assert exc.value.code == "pad_set_mismatch"


def test_swap_footprint_unknown_ref(tmp_path: Path) -> None:
    pcb = _copy_project(tmp_path) / "demo.kicad_pcb"
    with pytest.raises(CommandError) as exc:
        pcb_file.swap_footprint(pcb, "R99", "Demo:R_0603", _mod("R_0603"))
    assert exc.value.code == "not_found"


def test_swap_footprint_leaves_other_footprints_untouched(
    tmp_path: Path,
) -> None:
    pcb = _copy_project(tmp_path) / "demo.kicad_pcb"
    pcb_file.swap_footprint(pcb, "R1", "Demo:R_0603", _mod("R_0603"))
    tree = sexp.parse(pcb.read_text())
    r2 = pcb_file.find_footprint_node(tree, "R2")
    assert str(r2[1]) == "Demo:R_0805"          # R2 still the original


# ---------------------------------------------------------------------------
# edit swap-fp — command level
# ---------------------------------------------------------------------------

def test_edit_swap_fp_command(tmp_path: Path, monkeypatch) -> None:
    proj_dir = _copy_project(tmp_path)
    from kcd.adapters import kipy_pcb
    monkeypatch.setattr(kipy_pcb, "project_is_open", lambda *a, **k: False)
    monkeypatch.setattr(
        kicad_cli, "export_pcb_svg",
        lambda *a, **k: Path(a[2]).write_text("<svg/>"),
    )
    r = CliRunner().invoke(edit_app, [
        "swap-fp", str(proj_dir), "--ref", "R1",
        "--to-footprint", "Demo:R_0603", "--json",
    ])
    assert r.exit_code == 0, r.stdout
    out = json.loads(r.stdout)
    assert out["data"]["swapped"]["to_footprint"] == "Demo:R_0603"
    tree = sexp.parse((proj_dir / "demo.kicad_pcb").read_text())
    assert str(pcb_file.find_footprint_node(tree, "R1")[1]) == "Demo:R_0603"


def test_edit_swap_fp_guards_open_project(tmp_path: Path, monkeypatch) -> None:
    proj_dir = _copy_project(tmp_path)
    from kcd.adapters import kipy_pcb
    monkeypatch.setattr(kipy_pcb, "project_is_open", lambda *a, **k: True)
    r = CliRunner().invoke(edit_app, [
        "swap-fp", str(proj_dir), "--ref", "R1",
        "--to-footprint", "Demo:R_0603", "--json",
    ])
    assert r.exit_code == 1
    assert json.loads(r.stdout)["error"]["code"] == "project_open_in_kicad"


def test_edit_swap_fp_pad_mismatch_is_clean_error(
    tmp_path: Path, monkeypatch,
) -> None:
    proj_dir = _copy_project(tmp_path)
    from kcd.adapters import kipy_pcb
    monkeypatch.setattr(kipy_pcb, "project_is_open", lambda *a, **k: False)
    r = CliRunner().invoke(edit_app, [
        "swap-fp", str(proj_dir), "--ref", "R1",
        "--to-footprint", "Demo:SOT-23", "--json",
    ])
    assert r.exit_code == 1
    assert json.loads(r.stdout)["error"]["code"] == "pad_set_mismatch"
