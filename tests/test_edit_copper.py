"""Tests for `kcd edit track` — PCB copper track editing (Wave 6 Phase A).

The command layer is tested with the `kipy_pcb` adapter monkeypatched (no
live KiCad) — the IPC path itself is integration-only. `_match_tracks`, the
pure selection logic, is unit-tested directly with fake track objects.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kcd.adapters import kipy_pcb
from kcd.commands.edit import pcb_text_app, track_app, via_app, zone_app
from kcd.core.ipc import IpcUnavailable
from kcd.core.output import CommandError

_NET_FIXTURE = Path(__file__).parent / "fixtures" / "net"
_MM = 1_000_000  # nm per mm


@pytest.fixture
def proj_dir(tmp_path: Path) -> Path:
    """A dir with just a .kicad_pro — enough for `resolve()`."""
    (tmp_path / "net_fixture.kicad_pro").write_text(
        (_NET_FIXTURE / "net_fixture.kicad_pro").read_text()
    )
    return tmp_path


# ---------------------------------------------------------------------------
# edit track delete / modify — command layer (adapter monkeypatched)
# ---------------------------------------------------------------------------

def test_track_delete_envelope(proj_dir: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        kipy_pcb, "delete_tracks",
        lambda *a, **k: {"deleted": [{"net": "VCC"}], "count": 2},
    )
    r = CliRunner().invoke(
        track_app,
        ["delete", str(proj_dir), "--net", "VCC", "--no-snapshot", "--json"],
    )
    assert r.exit_code == 0, r.stdout
    out = json.loads(r.stdout)
    assert out["ok"] is True
    assert out["command"] == "edit.track.delete"
    assert out["data"]["count"] == 2
    assert any("board.save()" in w for w in out["warnings"])


def test_track_delete_no_op_skips_board_save_warning(
    proj_dir: Path, monkeypatch,
) -> None:
    """A track-delete that matches nothing writes nothing — so it must not
    print the board.save() advisory (Round-3 B14)."""
    monkeypatch.setattr(
        kipy_pcb, "delete_tracks",
        lambda *a, **k: {"deleted": [], "count": 0},
    )
    r = CliRunner().invoke(
        track_app,
        ["delete", str(proj_dir), "--net", "VCC", "--no-snapshot", "--json"],
    )
    assert r.exit_code == 0, r.stdout
    out = json.loads(r.stdout)
    assert out["data"]["count"] == 0
    assert not any("board.save()" in w for w in out["warnings"])


def test_track_modify_no_op_skips_board_save_warning(
    proj_dir: Path, monkeypatch,
) -> None:
    """Same gating for `track modify` — no match, no write, no warning."""
    monkeypatch.setattr(
        kipy_pcb, "modify_tracks",
        lambda *a, **k: {"modified": [], "count": 0},
    )
    r = CliRunner().invoke(
        track_app,
        ["modify", str(proj_dir), "--net", "VCC", "--width", "0.5",
         "--no-snapshot", "--json"],
    )
    assert r.exit_code == 0, r.stdout
    out = json.loads(r.stdout)
    assert out["data"]["count"] == 0
    assert not any("board.save()" in w for w in out["warnings"])


def test_track_delete_ipc_unavailable(proj_dir: Path, monkeypatch) -> None:
    def boom(*a, **k):
        raise IpcUnavailable("KiCad not running")

    monkeypatch.setattr(kipy_pcb, "delete_tracks", boom)
    r = CliRunner().invoke(
        track_app,
        ["delete", str(proj_dir), "--net", "VCC", "--no-snapshot", "--json"],
    )
    assert r.exit_code == 1
    assert json.loads(r.stdout)["error"]["code"] == "ipc_unavailable"


def test_track_delete_bad_coordinate(proj_dir: Path) -> None:
    r = CliRunner().invoke(
        track_app,
        ["delete", str(proj_dir), "--from", "notxy", "--to", "5,5",
         "--no-snapshot", "--json"],
    )
    assert r.exit_code == 1
    assert json.loads(r.stdout)["error"]["code"] == "bad_coordinate"


def test_track_modify_envelope(proj_dir: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        kipy_pcb, "modify_tracks",
        lambda *a, **k: {"modified": [{"net": "VCC"}], "count": 1},
    )
    r = CliRunner().invoke(
        track_app,
        ["modify", str(proj_dir), "--net", "VCC", "--width", "0.5",
         "--no-snapshot", "--json"],
    )
    assert r.exit_code == 0, r.stdout
    out = json.loads(r.stdout)
    assert out["command"] == "edit.track.modify"
    assert out["data"]["count"] == 1


# ---------------------------------------------------------------------------
# _match_tracks — selection logic
# ---------------------------------------------------------------------------

class _Pt:
    def __init__(self, x: int, y: int) -> None:
        self.x, self.y = x, y


class _FakeTrack:
    def __init__(self, net, start, end, layer=0, width=250000):
        self.net = type("N", (), {"name": net})()
        self.start = _Pt(*start)
        self.end = _Pt(*end)
        self.layer = layer
        self.width = width


class _FakeBoard:
    def __init__(self, tracks):
        self._tracks = tracks

    def get_tracks(self):
        return self._tracks


def test_match_tracks_by_net() -> None:
    board = _FakeBoard([
        _FakeTrack("VCC", (0, 0), (10 * _MM, 0)),
        _FakeTrack("GND", (0, 0), (10 * _MM, 0)),
    ])
    got = kipy_pcb._match_tracks(board, "VCC", None, None, None)
    assert len(got) == 1
    assert got[0].net.name == "VCC"


def test_match_tracks_by_endpoints_either_direction() -> None:
    board = _FakeBoard([
        _FakeTrack("VCC", (10 * _MM, 20 * _MM), (30 * _MM, 20 * _MM)),
        _FakeTrack("VCC", (50 * _MM, 0), (60 * _MM, 0)),
    ])
    got = kipy_pcb._match_tracks(board, None, (30.0, 20.0), (10.0, 20.0), None)
    assert len(got) == 1


def test_match_tracks_no_selector_errors() -> None:
    with pytest.raises(CommandError) as exc:
        kipy_pcb._match_tracks(_FakeBoard([]), None, None, None, None)
    assert exc.value.code == "bad_selector"


def test_match_tracks_partial_endpoints_errors() -> None:
    with pytest.raises(CommandError) as exc:
        kipy_pcb._match_tracks(_FakeBoard([]), "VCC", (1.0, 1.0), None, None)
    assert exc.value.code == "bad_selector"


def test_match_tracks_no_match_errors() -> None:
    board = _FakeBoard([_FakeTrack("GND", (0, 0), (1, 1))])
    with pytest.raises(CommandError) as exc:
        kipy_pcb._match_tracks(board, "VCC", None, None, None)
    assert exc.value.code == "not_found"


# ---------------------------------------------------------------------------
# _layer_enum
# ---------------------------------------------------------------------------

def test_layer_enum_known() -> None:
    assert isinstance(kipy_pcb._layer_enum("F.Cu"), int)
    assert kipy_pcb._layer_enum("B.Cu") != kipy_pcb._layer_enum("F.Cu")


def test_layer_enum_bad() -> None:
    with pytest.raises(CommandError) as exc:
        kipy_pcb._layer_enum("Bogus.Layer")
    assert exc.value.code == "bad_layer"


# ---------------------------------------------------------------------------
# edit via add — command layer (adapter monkeypatched)
# ---------------------------------------------------------------------------

def test_via_add_envelope(proj_dir: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        kipy_pcb, "add_via",
        lambda *a, **k: {"net": "VCC", "at_mm": [100.0, 50.0]},
    )
    r = CliRunner().invoke(
        via_app,
        ["add", str(proj_dir), "--net", "VCC", "--at", "100,50",
         "--no-snapshot", "--json"],
    )
    assert r.exit_code == 0, r.stdout
    out = json.loads(r.stdout)
    assert out["ok"] is True
    assert out["command"] == "edit.via.add"
    assert out["data"]["added"]["net"] == "VCC"
    assert any("board.save()" in w for w in out["warnings"])


def test_via_add_defaults_passed(proj_dir: Path, monkeypatch) -> None:
    """--diameter / --drill default to 0.6 / 0.3 mm when omitted."""
    captured: dict = {}

    def fake_add_via(expected_pcb, net, at_mm, diameter_mm, drill_mm):
        captured.update(diameter=diameter_mm, drill=drill_mm, at=at_mm)
        return {"net": net}

    monkeypatch.setattr(kipy_pcb, "add_via", fake_add_via)
    r = CliRunner().invoke(
        via_app,
        ["add", str(proj_dir), "--net", "VCC", "--at", "100,50",
         "--no-snapshot", "--json"],
    )
    assert r.exit_code == 0, r.stdout
    assert captured == {"diameter": 0.6, "drill": 0.3, "at": (100.0, 50.0)}


def test_via_add_bad_coordinate(proj_dir: Path) -> None:
    r = CliRunner().invoke(
        via_app,
        ["add", str(proj_dir), "--net", "VCC", "--at", "notxy",
         "--no-snapshot", "--json"],
    )
    assert r.exit_code == 1
    assert json.loads(r.stdout)["error"]["code"] == "bad_coordinate"


def test_via_add_ipc_unavailable(proj_dir: Path, monkeypatch) -> None:
    def boom(*a, **k):
        raise IpcUnavailable("KiCad not running")

    monkeypatch.setattr(kipy_pcb, "add_via", boom)
    r = CliRunner().invoke(
        via_app,
        ["add", str(proj_dir), "--net", "VCC", "--at", "100,50",
         "--no-snapshot", "--json"],
    )
    assert r.exit_code == 1
    assert json.loads(r.stdout)["error"]["code"] == "ipc_unavailable"


# ---------------------------------------------------------------------------
# edit zone add / delete — command layer (adapter monkeypatched)
# ---------------------------------------------------------------------------

def test_zone_add_envelope(proj_dir: Path, monkeypatch) -> None:
    captured: dict = {}

    def fake_add_zone(expected_pcb, net, layer, rect_mm, priority, clearance_mm):
        captured.update(rect=rect_mm, priority=priority, clearance=clearance_mm)
        return {"net": net, "layer": layer}

    monkeypatch.setattr(kipy_pcb, "add_zone", fake_add_zone)
    r = CliRunner().invoke(
        zone_app,
        ["add", str(proj_dir), "--net", "GND", "--layer", "F.Cu",
         "--rect", "0,0,10,8", "--no-snapshot", "--json"],
    )
    assert r.exit_code == 0, r.stdout
    out = json.loads(r.stdout)
    assert out["ok"] is True
    assert out["command"] == "edit.zone.add"
    assert out["data"]["added"]["net"] == "GND"
    assert captured["rect"] == (0.0, 0.0, 10.0, 8.0)
    assert captured["priority"] == 0 and captured["clearance"] is None
    assert any("board.save()" in w for w in out["warnings"])


def test_zone_add_bad_rect(proj_dir: Path) -> None:
    r = CliRunner().invoke(
        zone_app,
        ["add", str(proj_dir), "--net", "GND", "--layer", "F.Cu",
         "--rect", "0,0,10", "--no-snapshot", "--json"],
    )
    assert r.exit_code == 1
    assert json.loads(r.stdout)["error"]["code"] == "bad_coordinate"


def test_zone_add_ipc_unavailable(proj_dir: Path, monkeypatch) -> None:
    def boom(*a, **k):
        raise IpcUnavailable("KiCad not running")

    monkeypatch.setattr(kipy_pcb, "add_zone", boom)
    r = CliRunner().invoke(
        zone_app,
        ["add", str(proj_dir), "--net", "GND", "--layer", "F.Cu",
         "--rect", "0,0,10,8", "--no-snapshot", "--json"],
    )
    assert r.exit_code == 1
    assert json.loads(r.stdout)["error"]["code"] == "ipc_unavailable"


def test_zone_delete_envelope(proj_dir: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        kipy_pcb, "delete_zones",
        lambda *a, **k: {"deleted": [{"net": "GND"}], "count": 1},
    )
    r = CliRunner().invoke(
        zone_app,
        ["delete", str(proj_dir), "--net", "GND", "--no-snapshot", "--json"],
    )
    assert r.exit_code == 0, r.stdout
    out = json.loads(r.stdout)
    assert out["command"] == "edit.zone.delete"
    assert out["data"]["count"] == 1


def test_zone_delete_no_selector(proj_dir: Path) -> None:
    """No --net / --layer → the real delete_zones rejects before any IPC."""
    r = CliRunner().invoke(
        zone_app, ["delete", str(proj_dir), "--no-snapshot", "--json"]
    )
    assert r.exit_code == 1
    assert json.loads(r.stdout)["error"]["code"] == "bad_selector"


# ---------------------------------------------------------------------------
# edit pcb-text add / set — command layer (adapter monkeypatched) — R5-7
# ---------------------------------------------------------------------------

def test_pcb_text_add_envelope(proj_dir: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        kipy_pcb, "add_pcb_text",
        lambda *a, **k: {"text": "REV-A", "layer": "F.SilkS"},
    )
    r = CliRunner().invoke(
        pcb_text_app,
        ["add", str(proj_dir), "--text", "REV-A", "--at", "10,20",
         "--no-snapshot", "--json"],
    )
    assert r.exit_code == 0, r.stdout
    out = json.loads(r.stdout)
    assert out["ok"] is True
    assert out["command"] == "edit.pcb-text.add"
    assert out["data"]["added"]["text"] == "REV-A"
    assert any("board.save()" in w for w in out["warnings"])


def test_pcb_text_add_defaults_passed(proj_dir: Path, monkeypatch) -> None:
    """Layer / size / thickness / rotation default when omitted."""
    captured: dict = {}

    def fake_add(expected_pcb, text, at_mm, layer, size, thickness, rotation):
        captured.update(
            at=at_mm, layer=layer, size=size,
            thickness=thickness, rotation=rotation,
        )
        return {"text": text}

    monkeypatch.setattr(kipy_pcb, "add_pcb_text", fake_add)
    r = CliRunner().invoke(
        pcb_text_app,
        ["add", str(proj_dir), "--text", "REV-A", "--at", "10,20",
         "--no-snapshot", "--json"],
    )
    assert r.exit_code == 0, r.stdout
    assert captured == {
        "at": (10.0, 20.0), "layer": "F.SilkS",
        "size": 1.0, "thickness": 0.15, "rotation": 0.0,
    }


def test_pcb_text_add_bad_coordinate(proj_dir: Path) -> None:
    r = CliRunner().invoke(
        pcb_text_app,
        ["add", str(proj_dir), "--text", "REV-A", "--at", "notxy",
         "--no-snapshot", "--json"],
    )
    assert r.exit_code == 1
    assert json.loads(r.stdout)["error"]["code"] == "bad_coordinate"


def test_pcb_text_add_ipc_unavailable(proj_dir: Path, monkeypatch) -> None:
    def boom(*a, **k):
        raise IpcUnavailable("KiCad not running")

    monkeypatch.setattr(kipy_pcb, "add_pcb_text", boom)
    r = CliRunner().invoke(
        pcb_text_app,
        ["add", str(proj_dir), "--text", "REV-A", "--at", "10,20",
         "--no-snapshot", "--json"],
    )
    assert r.exit_code == 1
    assert json.loads(r.stdout)["error"]["code"] == "ipc_unavailable"


def test_pcb_text_set_envelope(proj_dir: Path, monkeypatch) -> None:
    captured: dict = {}

    def fake_set(expected_pcb, match, new_value):
        captured.update(match=match, new_value=new_value)
        return {"match": match, "new_value": new_value, "layer": "F.SilkS"}

    monkeypatch.setattr(kipy_pcb, "set_pcb_text", fake_set)
    r = CliRunner().invoke(
        pcb_text_app,
        ["set", str(proj_dir), "--match", "REV-A", "--to", "REV-B",
         "--no-snapshot", "--json"],
    )
    assert r.exit_code == 0, r.stdout
    out = json.loads(r.stdout)
    assert out["command"] == "edit.pcb-text.set"
    assert out["data"]["updated"]["new_value"] == "REV-B"
    assert captured == {"match": "REV-A", "new_value": "REV-B"}
    assert any("board.save()" in w for w in out["warnings"])


def test_pcb_text_set_ipc_unavailable(proj_dir: Path, monkeypatch) -> None:
    def boom(*a, **k):
        raise IpcUnavailable("KiCad not running")

    monkeypatch.setattr(kipy_pcb, "set_pcb_text", boom)
    r = CliRunner().invoke(
        pcb_text_app,
        ["set", str(proj_dir), "--match", "REV-A", "--to", "REV-B",
         "--no-snapshot", "--json"],
    )
    assert r.exit_code == 1
    assert json.loads(r.stdout)["error"]["code"] == "ipc_unavailable"
