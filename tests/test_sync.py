"""Unit tests for `kcd sync`.

The pure helpers (`_parse_netlist_xml`, `_compute_drift`) are tested directly.
The command is tested with `kicad_cli.export_sch_netlist` monkeypatched to drop
canned netlist XML and — for `--check` — the `kipy_pcb` adapter monkeypatched
with canned board data, so nothing here touches a live KiCad or kicad-cli.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from kcd.adapters import kicad_cli
from kcd.commands.sync import _compute_drift, _parse_netlist_xml, sync_cmd
from kcd.core.ipc import IpcUnavailable

_sync_app = typer.Typer()
_sync_app.command()(sync_cmd)

# A kicad-cli `--format kicadxml` netlist: R1/R2/C1, a local-label net
# `/SIGNAL`, a global `GND`, and R1 pin 1 floating (unconnected-* bookkeeping).
CANNED_NETLIST = """<?xml version="1.0" encoding="UTF-8"?>
<export version="E">
  <components>
    <comp ref="R1"><value>10k</value></comp>
    <comp ref="R2"><value>4k7</value></comp>
    <comp ref="C1"><value>100n</value></comp>
  </components>
  <nets>
    <net code="1" name="/SIGNAL">
      <node ref="R1" pin="2"/>
      <node ref="R2" pin="1"/>
    </net>
    <net code="2" name="GND">
      <node ref="R2" pin="2"/>
      <node ref="C1" pin="2"/>
    </net>
    <net code="3" name="unconnected-(R1-Pad1)">
      <node ref="R1" pin="1"/>
    </net>
  </nets>
</export>
"""


@pytest.fixture
def proj_dir(tmp_path: Path) -> Path:
    """Minimal fixture project — files just need to exist for `resolve()`."""
    (tmp_path / "demo.kicad_pro").write_text("{}")
    (tmp_path / "demo.kicad_sch").write_text(
        '(kicad_sch (version 20231120) (generator "test"))'
    )
    (tmp_path / "demo.kicad_pcb").write_text(
        '(kicad_pcb (version 20231120) (generator "test"))'
    )
    return tmp_path


def _stub_export(monkeypatch, xml: str = CANNED_NETLIST) -> None:
    """Monkeypatch the netlist export to drop canned XML at the requested path."""
    def fake(cli: str, sch: Path, out: Path, fmt: str = "kicadxml") -> Path:
        Path(out).write_text(xml)
        return out
    monkeypatch.setattr(kicad_cli, "export_sch_netlist", fake)


# ---------------------------------------------------------------------------
# _parse_netlist_xml
# ---------------------------------------------------------------------------

def test_parse_netlist_components_and_pins(tmp_path: Path) -> None:
    """Components and (ref,pin)->net come out of the XML; `unconnected-*`
    bookkeeping nets normalize to None."""
    nl = tmp_path / "nl.xml"
    nl.write_text(CANNED_NETLIST)
    comps, pins = _parse_netlist_xml(nl)
    assert comps == {"R1", "R2", "C1"}
    assert pins[("R1", "2")] == "/SIGNAL"
    assert pins[("R2", "1")] == "/SIGNAL"
    assert pins[("R2", "2")] == "GND"
    # The floating pin is recorded but its net is normalized away.
    assert pins[("R1", "1")] is None


# ---------------------------------------------------------------------------
# _compute_drift
# ---------------------------------------------------------------------------

def test_compute_drift_in_sync() -> None:
    """Identical schematic and PCB → in_sync, all buckets empty."""
    comps = {"R1", "R2"}
    pins = {("R1", "2"): "GND", ("R2", "1"): "GND"}
    drift = _compute_drift(comps, pins, comps, dict(pins))
    assert drift["in_sync"] is True
    assert drift["components_added"] == []
    assert drift["components_removed"] == []
    assert drift["net_changes"] == []


def test_compute_drift_component_added_and_removed() -> None:
    """Refs on one side only land in components_added / components_removed."""
    drift = _compute_drift(
        {"R1", "C1"}, {("R1", "1"): "GND"},
        {"R1", "U9"}, {("R1", "1"): "GND"},
    )
    assert drift["components_added"] == ["C1"]   # in schematic, not on PCB
    assert drift["components_removed"] == ["U9"]  # on PCB, not in schematic
    assert drift["in_sync"] is False


def test_compute_drift_net_change() -> None:
    """A pin whose net differs between sides → a net_changes entry."""
    drift = _compute_drift(
        {"R1"}, {("R1", "2"): "+BATT"},
        {"R1"}, {("R1", "2"): "+12V"},
    )
    assert drift["net_changes"] == [
        {"reference": "R1", "pin": "2", "schematic": "+BATT", "pcb": "+12V"}
    ]
    assert drift["in_sync"] is False


def test_compute_drift_skips_pins_of_drifted_components() -> None:
    """A pin on a component that exists on only one side is component-level
    drift already — it must not also appear as a net change."""
    drift = _compute_drift(
        {"R1", "C1"}, {("R1", "1"): "GND", ("C1", "2"): "GND"},
        {"R1"}, {("R1", "1"): "GND", ("C1", "2"): "VCC"},
    )
    assert drift["components_added"] == ["C1"]
    assert drift["net_changes"] == []  # (C1,2) skipped — C1 isn't on the PCB


# ---------------------------------------------------------------------------
# sync command — bare (export) mode
# ---------------------------------------------------------------------------

def test_sync_bare_exports_and_instructs(monkeypatch, proj_dir: Path, tmp_path: Path) -> None:
    """Bare `sync` exports the netlist, registers the artifact, and emits the
    F8 push instruction — no PCB needed."""
    _stub_export(monkeypatch)
    nl = tmp_path / "out.xml"
    runner = CliRunner()
    result = runner.invoke(_sync_app, [str(proj_dir), "--out", str(nl), "--json"])
    assert result.exit_code == 0, result.stdout
    out = json.loads(result.stdout)
    assert out["ok"] is True
    assert out["command"] == "sync"
    assert out["data"]["mode"] == "export"
    assert out["data"]["schematic_components"] == 3
    assert out["data"]["schematic_nets"] == 2  # /SIGNAL + GND; unconnected excluded
    assert out["artifacts"][0]["kind"] == "schematic_netlist"
    assert any("F8" in w for w in out["warnings"])


# ---------------------------------------------------------------------------
# sync command — --check mode
# ---------------------------------------------------------------------------

def test_sync_check_reports_drift(monkeypatch, proj_dir: Path, tmp_path: Path) -> None:
    """`sync --check` diffs the netlist against the live PCB and reports the
    component + net drift."""
    _stub_export(monkeypatch)
    from kcd.adapters import kipy_pcb
    monkeypatch.setattr(kipy_pcb, "assert_board_is", lambda expected: None)
    # PCB has R1/R2 but not C1; R2 pin 2 still on the old net.
    monkeypatch.setattr(kipy_pcb, "list_footprints", lambda: [
        {"reference": "R1"}, {"reference": "R2"},
    ])
    monkeypatch.setattr(kipy_pcb, "list_pad_nets", lambda: [
        {"footprint": "R1", "pad": "1", "net": ""},        # floating ↔ None: ok
        {"footprint": "R1", "pad": "2", "net": "/SIGNAL"},
        {"footprint": "R2", "pad": "1", "net": "/SIGNAL"},
        {"footprint": "R2", "pad": "2", "net": "VCC"},      # schematic says GND
    ])
    runner = CliRunner()
    result = runner.invoke(
        _sync_app, [str(proj_dir), "--check", "--out", str(tmp_path / "o.xml"), "--json"]
    )
    assert result.exit_code == 0, result.stdout
    out = json.loads(result.stdout)
    data = out["data"]
    assert data["mode"] == "check"
    assert data["pcb_available"] is True
    assert data["in_sync"] is False
    assert data["components_added"] == ["C1"]
    assert data["components_removed"] == []
    assert data["net_changes"] == [
        {"reference": "R2", "pin": "2", "schematic": "GND", "pcb": "VCC"}
    ]
    assert any("out of sync" in w for w in out["warnings"])


def test_sync_check_in_sync(monkeypatch, proj_dir: Path, tmp_path: Path) -> None:
    """A PCB that matches the netlist → in_sync, no drift warning."""
    _stub_export(monkeypatch)
    from kcd.adapters import kipy_pcb
    monkeypatch.setattr(kipy_pcb, "assert_board_is", lambda expected: None)
    monkeypatch.setattr(kipy_pcb, "list_footprints", lambda: [
        {"reference": "R1"}, {"reference": "R2"}, {"reference": "C1"},
    ])
    monkeypatch.setattr(kipy_pcb, "list_pad_nets", lambda: [
        {"footprint": "R1", "pad": "1", "net": "unconnected-(R1-Pad1)"},
        {"footprint": "R1", "pad": "2", "net": "/SIGNAL"},
        {"footprint": "R2", "pad": "1", "net": "/SIGNAL"},
        {"footprint": "R2", "pad": "2", "net": "GND"},
        {"footprint": "C1", "pad": "2", "net": "GND"},
    ])
    runner = CliRunner()
    result = runner.invoke(
        _sync_app, [str(proj_dir), "--check", "--out", str(tmp_path / "o.xml"), "--json"]
    )
    assert result.exit_code == 0, result.stdout
    data = json.loads(result.stdout)["data"]
    assert data["in_sync"] is True
    assert data["net_changes"] == []


def test_sync_check_degrades_when_ipc_unavailable(
    monkeypatch, proj_dir: Path, tmp_path: Path,
) -> None:
    """`sync --check` with KiCad unreachable degrades to export-only +
    warning — the netlist is still exported, the command still succeeds."""
    _stub_export(monkeypatch)
    from kcd.adapters import kipy_pcb

    def boom(expected: Path) -> None:
        raise IpcUnavailable("KiCad not running")
    monkeypatch.setattr(kipy_pcb, "assert_board_is", boom)

    runner = CliRunner()
    result = runner.invoke(
        _sync_app, [str(proj_dir), "--check", "--out", str(tmp_path / "o.xml"), "--json"]
    )
    assert result.exit_code == 0, result.stdout
    out = json.loads(result.stdout)
    assert out["ok"] is True
    assert out["data"]["pcb_available"] is False
    assert "in_sync" not in out["data"]
    assert any("KiCad not running" in w for w in out["warnings"])
