"""Tests for the `inspect ref` consistency block (Dove session-2 #14)."""

from __future__ import annotations

from kcd.commands.inspect import _check_consistency


def test_consistency_when_pcb_unavailable() -> None:
    """PCB info missing: returns explicit pcb_available=False + a note."""
    result = _check_consistency(
        {"value": "10k", "footprint": "Resistor_SMD:R_0805"},
        None,
    )
    assert result["pcb_available"] is False
    assert any("PCB info unavailable" in n for n in result["notes"])
    # Don't claim matching/non-matching when we couldn't compare
    assert "value_matches" not in result
    assert "footprint_matches" not in result


def test_consistency_when_values_match() -> None:
    """Identical sch + pcb: no divergence notes."""
    result = _check_consistency(
        {"value": "10k", "footprint": "Resistor_SMD:R_0805"},
        {"value": "10k", "library_id": "Resistor_SMD:R_0805"},
    )
    assert result["pcb_available"] is True
    assert result["value_matches"] is True
    assert result["footprint_matches"] is True
    assert result["notes"] == []


def test_consistency_when_value_diverges() -> None:
    """Schematic value changed but PCB still on old value: divergence flagged."""
    result = _check_consistency(
        {"value": "LT1373CN8", "footprint": "Package_DIP:DIP-8"},
        {"value": "LT1373", "library_id": "Package_DIP:DIP-8"},
    )
    assert result["pcb_available"] is True
    assert result["value_matches"] is False
    assert result["footprint_matches"] is True
    assert any("value differs" in n for n in result["notes"])
    assert any("Update PCB from Schematic" in n for n in result["notes"])


def test_consistency_when_footprint_diverges() -> None:
    """Footprint mismatch surfaces too."""
    result = _check_consistency(
        {"value": "10k", "footprint": "Resistor_SMD:R_0805"},
        {"value": "10k", "library_id": "Resistor_THT:R_Axial"},
    )
    assert result["pcb_available"] is True
    assert result["value_matches"] is True
    assert result["footprint_matches"] is False
    assert any("footprint differs" in n for n in result["notes"])


def test_consistency_handles_missing_fields_gracefully() -> None:
    """Partial dicts shouldn't crash."""
    result = _check_consistency(
        {"value": "10k"},
        {"value": "10k"},
    )
    # sch.footprint missing → None; pcb.library_id missing → None; equal → True
    assert result["pcb_available"] is True
    assert result["value_matches"] is True
    assert result["footprint_matches"] is True
