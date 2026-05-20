"""Tests for `kcd edit` structural edits — wires and net labels (Wave 4 A).

Each test copies the `net_fixture` schematic into a tmp dir and drives the
real commands with `--no-snapshot --no-render` (no git repo, no kicad-cli
subprocess), then reloads the `.kicad_sch` with kicad-skip to confirm the
edit landed on disk.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kcd.commands.edit import netlabel_app, wire_app

_NET_FIXTURE = Path(__file__).parent / "fixtures" / "net"
_OFFLINE = ["--no-snapshot", "--no-render", "--json"]


@pytest.fixture
def proj(tmp_path: Path) -> Path:
    """A writable copy of the net_fixture project."""
    for ext in ("kicad_pro", "kicad_sch"):
        (tmp_path / f"net_fixture.{ext}").write_text(
            (_NET_FIXTURE / f"net_fixture.{ext}").read_text()
        )
    return tmp_path


def _sch(proj: Path):
    from skip import Schematic
    return Schematic(str(proj / "net_fixture.kicad_sch"))


# ---------------------------------------------------------------------------
# wire
# ---------------------------------------------------------------------------

def test_wire_add_then_delete(proj: Path) -> None:
    runner = CliRunner()
    add = runner.invoke(wire_app, ["add", str(proj), "--from", "40,40", "--to", "50,40", *_OFFLINE])
    assert add.exit_code == 0, add.stdout
    out = json.loads(add.stdout)
    assert out["ok"] is True
    assert out["command"] == "edit.wire.add"
    assert out["data"]["added"]["start"] == [40.0, 40.0]
    assert len(list(_sch(proj).wire)) == 3  # 2 original + 1 new

    # delete with endpoints reversed — direction-agnostic match
    rm = runner.invoke(
        wire_app, ["delete", str(proj), "--from", "50,40", "--to", "40,40", *_OFFLINE]
    )
    assert rm.exit_code == 0, rm.stdout
    assert json.loads(rm.stdout)["ok"] is True
    assert len(list(_sch(proj).wire)) == 2  # back to the originals


def test_wire_delete_not_found(proj: Path) -> None:
    runner = CliRunner()
    r = runner.invoke(wire_app, ["delete", str(proj), "--from", "1,1", "--to", "2,2", *_OFFLINE])
    assert r.exit_code == 1
    out = json.loads(r.stdout)
    assert out["ok"] is False
    assert out["error"]["code"] == "edit_failed"


def test_wire_bad_coordinate(proj: Path) -> None:
    runner = CliRunner()
    r = runner.invoke(wire_app, ["add", str(proj), "--from", "notxy", "--to", "5,5", *_OFFLINE])
    assert r.exit_code == 1
    assert json.loads(r.stdout)["error"]["code"] == "bad_coordinate"


# ---------------------------------------------------------------------------
# netlabel
# ---------------------------------------------------------------------------

def test_netlabel_add_local_and_global(proj: Path) -> None:
    runner = CliRunner()
    loc = runner.invoke(
        netlabel_app, ["add", str(proj), "--text", "VOUT", "--at", "55,55", *_OFFLINE]
    )
    assert loc.exit_code == 0, loc.stdout
    assert json.loads(loc.stdout)["data"]["added"]["kind"] == "local"

    glob = runner.invoke(
        netlabel_app,
        ["add", str(proj), "--text", "VBUS", "--at", "60,60", "--global", *_OFFLINE],
    )
    assert glob.exit_code == 0, glob.stdout
    assert json.loads(glob.stdout)["data"]["added"]["kind"] == "global"

    sch = _sch(proj)
    assert "VOUT" in {lbl.value for lbl in sch.label}
    assert "VBUS" in {lbl.value for lbl in sch.global_label}


def test_netlabel_delete(proj: Path) -> None:
    runner = CliRunner()
    runner.invoke(netlabel_app, ["add", str(proj), "--text", "TMP", "--at", "33,33", *_OFFLINE])
    rm = runner.invoke(netlabel_app, ["delete", str(proj), "--text", "TMP", *_OFFLINE])
    assert rm.exit_code == 0, rm.stdout
    out = json.loads(rm.stdout)
    assert out["data"]["deleted"][0]["text"] == "TMP"
    assert "TMP" not in {lbl.value for lbl in _sch(proj).label}


def test_netlabel_delete_ambiguous_needs_at(proj: Path) -> None:
    """Two labels with the same text → delete without --at refuses to guess."""
    runner = CliRunner()
    runner.invoke(netlabel_app, ["add", str(proj), "--text", "DUP", "--at", "10,10", *_OFFLINE])
    runner.invoke(netlabel_app, ["add", str(proj), "--text", "DUP", "--at", "20,20", *_OFFLINE])
    r = runner.invoke(netlabel_app, ["delete", str(proj), "--text", "DUP", *_OFFLINE])
    assert r.exit_code == 1
    out = json.loads(r.stdout)
    assert out["error"]["code"] == "edit_failed"
    assert "--at" in out["error"]["message"]
    # disambiguated delete succeeds
    ok = runner.invoke(
        netlabel_app, ["delete", str(proj), "--text", "DUP", "--at", "10,10", *_OFFLINE]
    )
    assert ok.exit_code == 0, ok.stdout
