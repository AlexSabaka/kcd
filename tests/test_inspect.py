"""Tests for the `inspect ref` consistency block (Dove session-2 #14)
and part-identity coherence (Round-3 field report B8)."""

from __future__ import annotations

from kcd.commands.inspect import (
    _check_consistency,
    _check_part_identity_coherence,
    _part_family,
)


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


# ---------------------------------------------------------------------------
# part-identity coherence (B8)
# ---------------------------------------------------------------------------

def test_part_family_extracts_the_part_number_core() -> None:
    assert _part_family("AP2112K-3.3") == "ap2112"
    assert _part_family("NCP1117-3.3_SOT223") == "ncp1117"
    assert _part_family("LM358") == "lm358"
    assert _part_family("ATmega328P") == "atmega328"


def test_part_family_is_none_for_non_part_numbers() -> None:
    """Passive values and digit-leading names are not part-number-shaped."""
    for v in ("10k", "100nF", "1N4148", "", None):
        assert _part_family(v) is None


def test_coherence_flags_value_symbol_datasheet_mismatch() -> None:
    """The U1 case: value AP2112K on an NCP1117 symbol + NCP1117 datasheet."""
    result = _check_part_identity_coherence({
        "value": "AP2112K-3.3",
        "lib_id": "Regulator_Linear:NCP1117-3.3_SOT223",
        "datasheet": "https://example.com/NCP1117.pdf",
    })
    assert result["coherent"] is False
    assert len(result["issues"]) == 2  # value↔symbol + datasheet corroboration
    assert any("ap2112" in i and "ncp1117" in i for i in result["issues"])


def test_coherence_clean_for_a_matching_part() -> None:
    result = _check_part_identity_coherence({
        "value": "LM358", "lib_id": "Amplifier_Operational:LM358",
        "datasheet": "",
    })
    assert result["coherent"] is True
    assert result["issues"] == []


def test_coherence_clean_for_a_passive() -> None:
    """A resistor's value is its resistance, not a part number — never flags."""
    result = _check_part_identity_coherence({
        "value": "10k", "lib_id": "Device:R", "datasheet": "",
    })
    assert result["coherent"] is True


def test_coherence_clean_for_a_generic_symbol() -> None:
    """A real part number on a generic symbol name (no competing identity)
    does not flag — conservative by design."""
    result = _check_part_identity_coherence({
        "value": "ATmega328P", "lib_id": "MCU_Microchip_ATmega:MCU",
        "datasheet": "",
    })
    assert result["coherent"] is True
