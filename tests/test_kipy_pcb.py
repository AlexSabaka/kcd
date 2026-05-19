"""Tests for the kipy_pcb adapter's pure helpers (no live KiCad needed).

Live-IPC paths (list_footprints, move_footprint, etc.) are exercised by
`tests/test_agentic_loop.py` (KCD_INTEGRATION=1 gated).
"""

from __future__ import annotations

from kcd.adapters.kipy_pcb import _ref_sort_key


def test_ref_sort_key_numeric_order() -> None:
    """R1, R2, R10 sort in numeric order, not lexicographic."""
    refs = ["R10", "R2", "R1", "R3"]
    refs.sort(key=_ref_sort_key)
    assert refs == ["R1", "R2", "R3", "R10"]


def test_ref_sort_key_groups_by_prefix() -> None:
    """All Cs land before all Rs, regardless of numeric value."""
    refs = ["R1", "C99", "C1", "R99", "U1"]
    refs.sort(key=_ref_sort_key)
    assert refs == ["C1", "C99", "R1", "R99", "U1"]


def test_ref_sort_key_handles_subreference_suffix() -> None:
    """`U4A` / `U4B` (multi-unit refs) sort after `U4` and stay grouped."""
    refs = ["U4B", "U4A", "U4", "U10"]
    refs.sort(key=_ref_sort_key)
    assert refs == ["U4", "U4A", "U4B", "U10"]


def test_ref_sort_key_handles_empty_and_malformed() -> None:
    """Refs without the standard shape sort to the bottom rather than crash."""
    refs = ["R1", "", "?", "R2"]
    refs.sort(key=_ref_sort_key)
    # Well-formed refs first, malformed at the end (stable among themselves).
    assert refs[:2] == ["R1", "R2"]
    assert set(refs[2:]) == {"", "?"}


def test_ref_sort_key_multi_letter_prefix() -> None:
    """`TP1` (test points) sort correctly relative to single-letter prefixes."""
    refs = ["TP10", "TP1", "TP2"]
    refs.sort(key=_ref_sort_key)
    assert refs == ["TP1", "TP2", "TP10"]
