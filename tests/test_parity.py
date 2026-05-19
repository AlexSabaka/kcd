"""Tests for `kcd parity` — schematic↔PCB drift detection (Dove session-4 #22).

These exercise the set algebra and IPC-degradation path with a real
kicad-skip parse of a tiny fixture schematic. `kipy_pcb.list_footprints` is
monkeypatched to inject controlled PCB data so we can test all four drift
flavors without a live KiCad.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from kcd.commands.parity import parity_cmd

# Wrap the flat command in a single-command Typer for CliRunner invocation.
# (CliRunner.invoke needs a typer.Typer/click.Command instance, not a bare
# function.) The CLI registers `parity_cmd` directly on the top-level app
# via `app.command("parity")(parity_cmd)` — same shape, different mount.
_parity_app = typer.Typer()
_parity_app.command()(parity_cmd)


# Two-symbol schematic: R1 (10k, R_0805) and C1 (100n, C_0603).
_SCH_TWO_SYMBOLS = textwrap.dedent("""
(kicad_sch
\t(version 20231120)
\t(generator "eeschema")
\t(uuid "55555555-5555-5555-5555-555555555555")
\t(paper "A4")
\t(lib_symbols)
\t(symbol
\t\t(lib_id "Device:R")
\t\t(at 100 100 0)
\t\t(unit 1)
\t\t(uuid "aaaa1111-1111-1111-1111-111111111111")
\t\t(property "Reference" "R1" (at 100 95 0))
\t\t(property "Value" "10k" (at 100 105 0))
\t\t(property "Footprint" "Resistor_SMD:R_0805_2012Metric" (at 100 100 0))
\t\t(property "Datasheet" "" (at 100 100 0))
\t)
\t(symbol
\t\t(lib_id "Device:C")
\t\t(at 200 100 0)
\t\t(unit 1)
\t\t(uuid "bbbb2222-2222-2222-2222-222222222222")
\t\t(property "Reference" "C1" (at 200 95 0))
\t\t(property "Value" "100n" (at 200 105 0))
\t\t(property "Footprint" "Capacitor_SMD:C_0603_1608Metric" (at 200 100 0))
\t\t(property "Datasheet" "" (at 200 100 0))
\t)
)
""").strip()


@pytest.fixture
def two_symbol_proj(tmp_path: Path) -> Path:
    """A minimal one-sheet project with R1 (10k) and C1 (100n)."""
    (tmp_path / "demo.kicad_pro").write_text("{}")
    (tmp_path / "demo.kicad_sch").write_text(_SCH_TWO_SYMBOLS)
    return tmp_path


def _invoke_parity(proj_dir: Path) -> dict:
    runner = CliRunner()
    result = runner.invoke(_parity_app, [str(proj_dir), "--json"])
    assert result.exit_code == 0, f"exit {result.exit_code}: {result.stdout}"
    return json.loads(result.stdout)


def test_parity_clean_alignment(monkeypatch, two_symbol_proj: Path) -> None:
    """Sch ≡ PCB: all four drift lists empty, no warnings, pcb_available=True."""
    from kcd.adapters import kipy_pcb
    monkeypatch.setattr(kipy_pcb, "list_footprints", lambda: [
        {"reference": "R1", "value": "10k",
         "library_id": "Resistor_SMD:R_0805_2012Metric"},
        {"reference": "C1", "value": "100n",
         "library_id": "Capacitor_SMD:C_0603_1608Metric"},
    ])
    out = _invoke_parity(two_symbol_proj)
    assert out["ok"] is True
    assert out["data"]["pcb_available"] is True
    assert out["data"]["schematic_only"] == []
    assert out["data"]["pcb_only"] == []
    assert out["data"]["value_mismatches"] == []
    assert out["data"]["footprint_mismatches"] == []
    assert out["warnings"] == []


def test_parity_finds_pcb_only_and_schematic_only(monkeypatch, two_symbol_proj: Path) -> None:
    """Sch has R1, C1; PCB has C1, C99: → schematic_only=[R1], pcb_only=[C99]."""
    from kcd.adapters import kipy_pcb
    monkeypatch.setattr(kipy_pcb, "list_footprints", lambda: [
        {"reference": "C1", "value": "100n",
         "library_id": "Capacitor_SMD:C_0603_1608Metric"},
        {"reference": "C99", "value": "1u",
         "library_id": "Capacitor_SMD:C_0805_2012Metric"},
    ])
    out = _invoke_parity(two_symbol_proj)
    assert out["data"]["pcb_available"] is True
    assert out["data"]["schematic_only"] == ["R1"]
    assert out["data"]["pcb_only"] == ["C99"]
    # PCB-only is a BOM hazard → warning emitted.
    assert any("BOM hazard" in w for w in out["warnings"])
    # Schematic-only also warns (mid-design state).
    assert any("not placed on the PCB" in w for w in out["warnings"])


def test_parity_value_mismatch(monkeypatch, two_symbol_proj: Path) -> None:
    """R1 schematic=10k but PCB=4.7k → value_mismatches entry."""
    from kcd.adapters import kipy_pcb
    monkeypatch.setattr(kipy_pcb, "list_footprints", lambda: [
        {"reference": "R1", "value": "4.7k",
         "library_id": "Resistor_SMD:R_0805_2012Metric"},
        {"reference": "C1", "value": "100n",
         "library_id": "Capacitor_SMD:C_0603_1608Metric"},
    ])
    out = _invoke_parity(two_symbol_proj)
    assert out["data"]["value_mismatches"] == [{
        "reference": "R1",
        "schematic": "10k",
        "pcb": "4.7k",
    }]
    assert out["data"]["footprint_mismatches"] == []


def test_parity_footprint_mismatch(monkeypatch, two_symbol_proj: Path) -> None:
    """R1 schematic=R_0805 but PCB=R_0603 → footprint_mismatches entry."""
    from kcd.adapters import kipy_pcb
    monkeypatch.setattr(kipy_pcb, "list_footprints", lambda: [
        {"reference": "R1", "value": "10k",
         "library_id": "Resistor_SMD:R_0603_1608Metric"},
        {"reference": "C1", "value": "100n",
         "library_id": "Capacitor_SMD:C_0603_1608Metric"},
    ])
    out = _invoke_parity(two_symbol_proj)
    assert out["data"]["footprint_mismatches"] == [{
        "reference": "R1",
        "schematic": "Resistor_SMD:R_0805_2012Metric",
        "pcb": "Resistor_SMD:R_0603_1608Metric",
    }]
    assert out["data"]["value_mismatches"] == []


def test_parity_degrades_when_ipc_unavailable(monkeypatch, two_symbol_proj: Path) -> None:
    """No KiCad open: returns schematic-only listing with a warning, ok=True.

    The command intentionally doesn't fail here — agents still get the
    schematic side, they just can't see drift. Failing would force them
    to special-case "is KiCad open" before every parity check.
    """
    from kcd.adapters import kipy_pcb
    from kcd.core.ipc import IpcUnavailable

    def raise_ipc() -> list:
        raise IpcUnavailable("KiCad not reachable")

    monkeypatch.setattr(kipy_pcb, "list_footprints", raise_ipc)

    out = _invoke_parity(two_symbol_proj)
    assert out["ok"] is True
    assert out["data"]["pcb_available"] is False
    assert sorted(out["data"]["schematic_only"]) == ["C1", "R1"]
    assert out["data"]["pcb_only"] == []
    assert any("KiCad not running" in w for w in out["warnings"])
