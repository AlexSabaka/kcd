"""Unit tests for `kcd net pcb|of`.

These exercise the envelope wrapping (shape, error classification) by
monkeypatching the `kipy_pcb` adapter with canned data — they do NOT touch a
live KiCad. The adapter's own board iteration (Counter pad/track tallies,
net-member filtering) is exercised by the gated agentic-loop integration test.

`net trace` (schematic-side) is covered separately once Phase B lands.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from kcd.adapters import kipy_pcb
from kcd.adapters.skip_sch import trace_net
from kcd.commands.net import net_of, pcb_nets, trace
from kcd.core.ipc import IpcUnavailable

# Wrap each command in its own Typer so CliRunner can invoke it directly. The
# real CLI mounts them under `kcd net pcb|of|trace`; tests hit the functions
# and pass `--json` for parseable output.
_pcb_app = typer.Typer()
_pcb_app.command()(pcb_nets)
_of_app = typer.Typer()
_of_app.command()(net_of)
_trace_app = typer.Typer()
_trace_app.command()(trace)

# A hand-authored single-sheet schematic: R1 pin2 — wire — R2 pin1 carry the
# local label SIGNAL; R2 pin2 — wire — power:GND symbol #PWR01.
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "net"
FIXTURE_SCH = FIXTURE_DIR / "net_fixture.kicad_sch"


@pytest.fixture
def proj_dir(tmp_path: Path) -> Path:
    """Minimal fixture project — the files just need to *exist* for
    `resolve()` to succeed; the kipy adapter is mocked anyway."""
    (tmp_path / "demo.kicad_pro").write_text("{}")
    (tmp_path / "demo.kicad_sch").write_text(
        '(kicad_sch (version 20231120) (generator "test"))'
    )
    (tmp_path / "demo.kicad_pcb").write_text(
        '(kicad_pcb (version 20231120) (generator "test"))'
    )
    return tmp_path


# ---------------------------------------------------------------------------
# net pcb
# ---------------------------------------------------------------------------

def test_net_pcb_envelope_shape(monkeypatch, proj_dir: Path) -> None:
    """Happy path: enriched nets (name + pad/track counts) wrap with ok=true."""
    monkeypatch.setattr(kipy_pcb, "list_nets", lambda: [
        {"name": "GND", "pad_count": 12, "track_count": 8},
        {"name": "VCC", "pad_count": 5, "track_count": 3},
    ])
    runner = CliRunner()
    result = runner.invoke(_pcb_app, [str(proj_dir), "--json"])
    assert result.exit_code == 0, result.stdout
    out = json.loads(result.stdout)
    assert out["ok"] is True
    assert out["command"] == "net.pcb"
    assert len(out["data"]["nets"]) == 2
    assert out["data"]["nets"][0]["pad_count"] == 12
    assert out["data"]["nets"][0]["track_count"] == 8


def test_net_pcb_ipc_unavailable(monkeypatch, proj_dir: Path) -> None:
    """KiCad not reachable → error.code='ipc_unavailable'."""
    def boom() -> list:
        raise IpcUnavailable("KiCad not running")
    monkeypatch.setattr(kipy_pcb, "list_nets", boom)
    runner = CliRunner()
    result = runner.invoke(_pcb_app, [str(proj_dir), "--json"])
    assert result.exit_code == 1
    out = json.loads(result.stdout)
    assert out["ok"] is False
    assert out["error"]["code"] == "ipc_unavailable"


# ---------------------------------------------------------------------------
# net of
# ---------------------------------------------------------------------------

def test_net_of_envelope_shape(monkeypatch, proj_dir: Path) -> None:
    """Happy path: net members (pads/tracks/vias/zones) wrap with ok=true."""
    monkeypatch.setattr(kipy_pcb, "net_members", lambda net: {
        "net": net,
        "pads": [
            {"footprint": "R1", "pad": "2", "type": "PT_SMD",
             "x_mm": 1.0, "y_mm": 2.0},
        ],
        "tracks": [
            {"net": net, "layer": "F.Cu", "width_mm": 0.25,
             "start": {"x_mm": 0.0, "y_mm": 0.0},
             "end": {"x_mm": 1.0, "y_mm": 0.0}},
        ],
        "vias": [],
        "zones": [],
    })
    runner = CliRunner()
    result = runner.invoke(_of_app, [str(proj_dir), "--net", "GND", "--json"])
    assert result.exit_code == 0, result.stdout
    out = json.loads(result.stdout)
    assert out["ok"] is True
    assert out["command"] == "net.of"
    assert out["data"]["net"] == "GND"
    assert out["data"]["pads"][0]["footprint"] == "R1"
    assert len(out["data"]["tracks"]) == 1


def test_net_of_unknown_net_is_not_found(monkeypatch, proj_dir: Path) -> None:
    """A net absent from the board → LookupError → error.code='not_found'."""
    def boom(net: str) -> dict:
        raise LookupError(f"Net {net!r} not found on board")
    monkeypatch.setattr(kipy_pcb, "net_members", boom)
    runner = CliRunner()
    result = runner.invoke(_of_app, [str(proj_dir), "--net", "NOPE", "--json"])
    assert result.exit_code == 1
    out = json.loads(result.stdout)
    assert out["ok"] is False
    assert out["error"]["code"] == "not_found"
    assert "NOPE" in out["error"]["message"]


def test_net_of_ipc_unavailable(monkeypatch, proj_dir: Path) -> None:
    """KiCad not reachable → error.code='ipc_unavailable'."""
    def boom(net: str) -> dict:
        raise IpcUnavailable("KiCad not running")
    monkeypatch.setattr(kipy_pcb, "net_members", boom)
    runner = CliRunner()
    result = runner.invoke(_of_app, [str(proj_dir), "--net", "GND", "--json"])
    assert result.exit_code == 1
    out = json.loads(result.stdout)
    assert out["ok"] is False
    assert out["error"]["code"] == "ipc_unavailable"


# ---------------------------------------------------------------------------
# trace_net adapter — run against the real fixture schematic (kicad-skip)
# ---------------------------------------------------------------------------

def test_trace_net_label_resolves_component_pins() -> None:
    """A local-label net resolves to the exact symbol pins on it."""
    result = trace_net(FIXTURE_SCH, "SIGNAL")
    assert result["found"] is True
    assert result["kind"] == ["label"]
    assert result["symbols"] == ["R1", "R2"]
    pins = {(p["reference"], p["pin"]) for p in result["pins"]}
    assert pins == {("R1", "2"), ("R2", "1")}


def test_trace_net_power_lists_anchor_without_pins() -> None:
    """A power net lists the declaring power symbol but not component pins
    (kicad-skip can't crawl through single-pin symbols)."""
    result = trace_net(FIXTURE_SCH, "GND")
    assert result["found"] is True
    assert result["kind"] == ["power"]
    assert result["symbols"] == ["#PWR01"]
    assert result["pins"] == []


def test_trace_net_unknown_net_not_found() -> None:
    """A name that is neither label nor power net → found=false, empty."""
    result = trace_net(FIXTURE_SCH, "NOPE")
    assert result["found"] is False
    assert result["pins"] == []
    assert result["symbols"] == []


# ---------------------------------------------------------------------------
# net trace command
# ---------------------------------------------------------------------------

def test_net_trace_command_label() -> None:
    """`net trace` on a label net → envelope with the pin list + scope warn."""
    runner = CliRunner()
    result = runner.invoke(_trace_app, [str(FIXTURE_DIR), "--net", "SIGNAL", "--json"])
    assert result.exit_code == 0, result.stdout
    out = json.loads(result.stdout)
    assert out["ok"] is True
    assert out["command"] == "net.trace"
    assert out["data"]["found"] is True
    pins = {(p["reference"], p["pin"]) for p in out["data"]["pins"]}
    assert pins == {("R1", "2"), ("R2", "1")}
    # The scope caveat is always surfaced so an agent knows the edges.
    assert any("hierarchical" in w for w in out["warnings"])


def test_net_trace_command_power_warns() -> None:
    """`net trace` on a power net → power-specific warning pointing at `net of`."""
    runner = CliRunner()
    result = runner.invoke(_trace_app, [str(FIXTURE_DIR), "--net", "GND", "--json"])
    assert result.exit_code == 0, result.stdout
    out = json.loads(result.stdout)
    assert out["data"]["kind"] == ["power"]
    assert any("power net" in w and "net of" in w for w in out["warnings"])


def test_net_trace_command_not_found_warns() -> None:
    """`net trace` on an unknown net → found=false + a `net of` hint."""
    runner = CliRunner()
    result = runner.invoke(_trace_app, [str(FIXTURE_DIR), "--net", "NOPE", "--json"])
    assert result.exit_code == 0, result.stdout
    out = json.loads(result.stdout)
    assert out["data"]["found"] is False
    assert any("net of" in w for w in out["warnings"])
