"""Tests for `kcd edit delete-fp` — PCB footprint deletion (Round-2 gap).

The command layer is tested with the `kipy_pcb` adapter monkeypatched (no
live KiCad). `delete_footprint`, the find-and-remove logic, is unit-tested
directly against a fake board — the IPC connection itself is integration-only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kcd.adapters import kipy_pcb
from kcd.commands.edit import edit_app
from kcd.core.ipc import IpcUnavailable

_NET_FIXTURE = Path(__file__).parent / "fixtures" / "net"


@pytest.fixture
def proj_dir(tmp_path: Path) -> Path:
    """A dir with just a .kicad_pro — enough for `resolve()`."""
    (tmp_path / "net_fixture.kicad_pro").write_text(
        (_NET_FIXTURE / "net_fixture.kicad_pro").read_text()
    )
    return tmp_path


# ---------------------------------------------------------------------------
# delete_footprint — find-and-remove logic (fake board)
# ---------------------------------------------------------------------------

class _FakeFootprint:
    def __init__(self, ref: str, symbol_sheet: str = "") -> None:
        self.reference_field = type(
            "F", (), {"text": type("T", (), {"value": ref})()}
        )()
        self.proto = type("P", (), {"symbol_sheet_name": symbol_sheet})()


class _FakeBoard:
    def __init__(self, fps: list[_FakeFootprint]) -> None:
        self._fps = fps
        self.removed: list[_FakeFootprint] = []
        self.saved = False

    def get_footprints(self) -> list[_FakeFootprint]:
        return self._fps

    def remove_items(self, items: list[_FakeFootprint]) -> None:
        self.removed.extend(items)

    def save(self) -> None:
        self.saved = True


@pytest.fixture
def fake_board(monkeypatch: pytest.MonkeyPatch):
    """Inject a fake board into `delete_footprint` and skip the board-id check."""
    def _install(fps: list[_FakeFootprint]) -> _FakeBoard:
        board = _FakeBoard(fps)
        monkeypatch.setattr(kipy_pcb, "assert_board_is", lambda _p: None)
        monkeypatch.setattr(kipy_pcb, "get_board", lambda: board)
        return board
    return _install


def test_delete_footprint_removes_and_saves(fake_board) -> None:
    board = fake_board([_FakeFootprint("R1"), _FakeFootprint("U3")])
    result = kipy_pcb.delete_footprint(Path("/x/demo.kicad_pcb"), "U3")
    assert result["count"] == 1
    assert result["deleted"]["reference"] == "U3"
    assert result["had_symbol"] is False
    assert [fp.reference_field.text.value for fp in board.removed] == ["U3"]
    assert board.saved is True


def test_delete_footprint_not_found_raises(fake_board) -> None:
    fake_board([_FakeFootprint("R1")])
    with pytest.raises(LookupError):
        kipy_pcb.delete_footprint(Path("/x/demo.kicad_pcb"), "NOPE")


def test_delete_footprint_flags_associated_symbol(fake_board) -> None:
    """A footprint with an associated schematic symbol sets `had_symbol`."""
    fake_board([_FakeFootprint("U5", symbol_sheet="/")])
    result = kipy_pcb.delete_footprint(Path("/x/demo.kicad_pcb"), "U5")
    assert result["had_symbol"] is True


# ---------------------------------------------------------------------------
# edit delete-fp — command layer (adapter monkeypatched)
# ---------------------------------------------------------------------------

def test_delete_fp_envelope(proj_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        kipy_pcb, "delete_footprint",
        lambda *a, **k: {"deleted": {"reference": "U3"}, "count": 1,
                         "had_symbol": False},
    )
    r = CliRunner().invoke(
        edit_app,
        ["delete-fp", str(proj_dir), "--ref", "U3", "--no-snapshot", "--json"],
    )
    assert r.exit_code == 0, r.stdout
    out = json.loads(r.stdout)
    assert out["ok"] is True
    assert out["command"] == "edit.delete-fp"
    assert out["data"]["count"] == 1
    assert any("board.save()" in w for w in out["warnings"])


def test_delete_fp_warns_on_associated_symbol(
    proj_dir: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`had_symbol` from the adapter surfaces a sch↔PCB drift warning."""
    monkeypatch.setattr(
        kipy_pcb, "delete_footprint",
        lambda *a, **k: {"deleted": {"reference": "U5"}, "count": 1,
                         "had_symbol": True},
    )
    r = CliRunner().invoke(
        edit_app,
        ["delete-fp", str(proj_dir), "--ref", "U5", "--no-snapshot", "--json"],
    )
    assert r.exit_code == 0, r.stdout
    out = json.loads(r.stdout)
    assert any("schematic symbol" in w for w in out["warnings"])


def test_delete_fp_ipc_unavailable(
    proj_dir: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*a: object, **k: object) -> dict:
        raise IpcUnavailable("KiCad not running")

    monkeypatch.setattr(kipy_pcb, "delete_footprint", boom)
    r = CliRunner().invoke(
        edit_app,
        ["delete-fp", str(proj_dir), "--ref", "U3", "--no-snapshot", "--json"],
    )
    assert r.exit_code == 1
    assert json.loads(r.stdout)["error"]["code"] == "ipc_unavailable"


def test_delete_fp_not_found(
    proj_dir: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(*a: object, **k: object) -> dict:
        raise LookupError("Footprint 'NOPE' not found on board")

    monkeypatch.setattr(kipy_pcb, "delete_footprint", missing)
    r = CliRunner().invoke(
        edit_app,
        ["delete-fp", str(proj_dir), "--ref", "NOPE", "--no-snapshot", "--json"],
    )
    assert r.exit_code == 1
    assert json.loads(r.stdout)["error"]["code"] == "not_found"
