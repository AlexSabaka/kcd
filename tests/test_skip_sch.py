"""Tests for the kicad-skip schematic adapter.

These exercise the actual kicad-skip parser against a minimal in-memory
.kicad_sch fixture — no KiCad install or external project needed.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from kcd.adapters import skip_sch


# Minimal-but-valid .kicad_sch with one symbol that has the four standard
# properties (Reference, Value, Footprint, Datasheet). The `(unit 1)` line
# is required — kicad-skip's symbol-collection namefetcher reads it.
_MINIMAL_SCH = textwrap.dedent("""
(kicad_sch
\t(version 20231120)
\t(generator "eeschema")
\t(generator_version "8.0")
\t(uuid "11111111-1111-1111-1111-111111111111")
\t(paper "A4")
\t(lib_symbols)
\t(symbol
\t\t(lib_id "Device:R")
\t\t(at 100 100 0)
\t\t(unit 1)
\t\t(uuid "22222222-2222-2222-2222-222222222222")
\t\t(property "Reference" "R1" (at 100 95 0))
\t\t(property "Value" "10k" (at 100 105 0))
\t\t(property "Footprint" "" (at 100 100 0))
\t\t(property "Datasheet" "" (at 100 100 0))
\t)
)
""").strip()


@pytest.fixture
def sch_path(tmp_path: Path) -> Path:
    p = tmp_path / "test.kicad_sch"
    p.write_text(_MINIMAL_SCH)
    return p


def test_set_property_adds_new_field(sch_path: Path) -> None:
    """Adding a property that doesn't exist must succeed without TypeError.

    This is the Dove-session-2 #11 regression: the old `hasattr(sym, 'setProperty')`
    branch triggered `TypeError: 'NoneType' object is not callable` because
    kicad-skip's __getattr__ returns None instead of raising.
    """
    result = skip_sch.set_property(sch_path, "R1", "MPN", "RC0805FR-0710KL")
    assert result["reference"] == "R1"

    # Verify the property landed on disk by re-reading.
    from skip import Schematic
    sch = Schematic(str(sch_path))
    sym = next(iter(sch.symbol))
    assert "MPN" in sym.property
    assert sym.property.MPN.value == "RC0805FR-0710KL"


def test_set_property_updates_existing_field(sch_path: Path) -> None:
    """Calling set_property on an existing field updates rather than re-adds."""
    skip_sch.set_property(sch_path, "R1", "MPN", "FIRST")
    skip_sch.set_property(sch_path, "R1", "MPN", "SECOND")

    from skip import Schematic
    sch = Schematic(str(sch_path))
    sym = next(iter(sch.symbol))
    # Single MPN property, with the updated value
    mpn_props = [p for p in sym.property if p.name == "MPN"]
    assert len(mpn_props) == 1
    assert sym.property.MPN.value == "SECOND"


def test_set_property_updates_builtin_value_field(sch_path: Path) -> None:
    """The `in` path handles standard fields (Value) without going through clone."""
    skip_sch.set_property(sch_path, "R1", "Value", "4k7")
    from skip import Schematic
    sch = Schematic(str(sch_path))
    sym = next(iter(sch.symbol))
    assert sym.property.Value.value == "4k7"


def test_set_property_raises_on_missing_symbol(sch_path: Path) -> None:
    """Unknown reference designator raises SchEditError, not a low-level error."""
    with pytest.raises(skip_sch.SchEditError, match="R99"):
        skip_sch.set_property(sch_path, "R99", "MPN", "x")


# ---------------------------------------------------------------------------
# Phase κ: properties echo (Dove session-3 #17)
# ---------------------------------------------------------------------------

def test_find_symbol_echoes_all_properties(sch_path: Path) -> None:
    """find_symbol's returned dict carries a `properties` mapping that includes
    canonical + user-added fields. Previously custom props were write-only."""
    skip_sch.set_property(sch_path, "R1", "MPN", "RC0805FR-0710KL")
    skip_sch.set_property(sch_path, "R1", "Manufacturer", "Yageo")

    info = skip_sch.find_symbol(sch_path, "R1")
    assert "properties" in info
    assert info["properties"]["Reference"] == "R1"
    assert info["properties"]["Value"] == "10k"
    assert info["properties"]["MPN"] == "RC0805FR-0710KL"
    assert info["properties"]["Manufacturer"] == "Yageo"


def test_set_property_returns_properties_dict(sch_path: Path) -> None:
    """The mutator itself echoes the new property in its return value."""
    info = skip_sch.set_property(sch_path, "R1", "Stock", "5000")
    assert info["properties"]["Stock"] == "5000"


def test_list_symbols_includes_properties(sch_path: Path) -> None:
    """list_symbols carries the same properties dict for bulk enumeration."""
    skip_sch.set_property(sch_path, "R1", "MPN", "FOO")
    syms = skip_sch.list_symbols(sch_path)
    assert len(syms) == 1
    assert syms[0]["properties"]["MPN"] == "FOO"
    assert syms[0]["properties"]["Reference"] == "R1"
