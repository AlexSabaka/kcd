"""Tests for `kcd edit net` — lib_id-aware net rename (Wave 5).

Each test copies the `net_fixture` schematic into a tmp dir and drives the
real command with `--no-snapshot --no-render` (no git repo, no kicad-cli
subprocess), then reloads the `.kicad_sch` with kicad-skip to confirm the
rename landed on disk. KiCad is not running, so the PCB drift check always
degrades to `pcb.checked: false`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kcd.commands.edit import edit_app, netlabel_app

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


def _net(proj: Path, old: str, new: str, *extra: str):
    return CliRunner().invoke(
        edit_app, ["net", str(proj), "--from", old, "--to", new, *_OFFLINE, *extra]
    )


# ---------------------------------------------------------------------------
# label / global-label rename
# ---------------------------------------------------------------------------

def test_rename_local_label(proj: Path) -> None:
    r = _net(proj, "SIGNAL", "VOUT")
    assert r.exit_code == 0, r.stdout
    out = json.loads(r.stdout)
    assert out["ok"] is True
    assert out["command"] == "edit.net"
    assert out["data"]["renamed"]["labels"] == 1
    labels = {lbl.value for lbl in _sch(proj).label}
    assert "VOUT" in labels and "SIGNAL" not in labels


def test_rename_global_label(proj: Path) -> None:
    CliRunner().invoke(
        netlabel_app,
        ["add", str(proj), "--text", "BUS0", "--at", "60,60", "--global", *_OFFLINE],
    )
    r = _net(proj, "BUS0", "BUS1")
    assert r.exit_code == 0, r.stdout
    assert json.loads(r.stdout)["data"]["renamed"]["global_labels"] == 1
    globs = {lbl.value for lbl in _sch(proj).global_label}
    assert "BUS1" in globs and "BUS0" not in globs


# ---------------------------------------------------------------------------
# power-net rename — lib_id repoint
# ---------------------------------------------------------------------------

def test_rename_power_net_repoints_lib_id(proj: Path) -> None:
    """Renaming a power net rewrites the power symbol's Value *and* lib_id,
    and embeds a matching lib_symbols entry — the friction-#4 landmine fix."""
    r = _net(proj, "GND", "VRENAMED")
    assert r.exit_code == 0, r.stdout
    out = json.loads(r.stdout)
    renamed = out["data"]["renamed"]
    assert renamed["power_symbols"] == ["#PWR01"]
    assert renamed["power_lib_id"] == {"from": "power:GND", "to": "power:VRENAMED"}
    assert renamed["power_definition_source"] == "derived"

    sym = next(
        s for s in _sch(proj).symbol if s.property.Reference.value == "#PWR01"
    )
    assert sym.property.Value.value == "VRENAMED"
    assert str(sym.lib_id.value) == "power:VRENAMED"
    assert hasattr(_sch(proj).lib_symbols, "power_VRENAMED")
    assert any("not a stock library symbol" in w for w in out["warnings"])


# ---------------------------------------------------------------------------
# guards
# ---------------------------------------------------------------------------

def test_rename_unknown_net_not_found(proj: Path) -> None:
    r = _net(proj, "NOPE", "X")
    assert r.exit_code == 1
    out = json.loads(r.stdout)
    assert out["ok"] is False
    assert out["error"]["code"] == "not_found"


def test_rename_into_existing_net_warns_merge(proj: Path) -> None:
    """Renaming onto a name that already exists is allowed but warns it
    merges the two nets."""
    r = _net(proj, "SIGNAL", "GND")
    assert r.exit_code == 0, r.stdout
    out = json.loads(r.stdout)
    assert any("merges" in w for w in out["warnings"])


def test_pcb_check_degrades_without_kicad(proj: Path) -> None:
    """With KiCad closed the PCB drift check degrades — it never fails the
    command, since the schematic rename already succeeded."""
    out = json.loads(_net(proj, "SIGNAL", "VOUT").stdout)
    pcb = out["data"]["pcb"]
    assert pcb["checked"] is False
    assert any("KiCad" in w for w in out["warnings"])


def test_pcb_drift_check_normalizes_hierarchical_prefix(
    proj: Path, monkeypatch,
) -> None:
    """PCB nets carry a leading `/` (`/SIGNAL`); the drift check strips it
    before comparing to the bare schematic label, so a genuinely stale net
    is reported stale instead of a false green (Round-6 field report)."""
    from kcd.adapters import kipy_pcb
    monkeypatch.setattr(kipy_pcb, "assert_board_is", lambda *a, **k: None)
    monkeypatch.setattr(
        kipy_pcb, "board_net_names", lambda *a, **k: ["/SIGNAL", "GND"]
    )
    out = json.loads(_net(proj, "SIGNAL", "VOUT").stdout)
    pcb = out["data"]["pcb"]
    assert pcb["checked"] is True
    assert pcb["stale"] is True
    assert pcb["old_net_present"] is True
    assert pcb["new_net_present"] is False
    assert any("still carries net" in w for w in out["warnings"])
