"""Tests for envelope `error.code` classification (Dove session-4 #23).

When a schematic command targets a reference that doesn't exist anywhere in
the project, the envelope used to return `error.code: "edit_failed"` — the
generic catch for `SchEditError`. That's dishonest: nothing was actually
edited, the input simply named a missing symbol. The right code is
`not_found` (which `FileNotFoundError` and `LookupError` already produce
via `kcd.core.output.run_command`).

`SymbolNotFound` (a `LookupError` subclass) raised at the not-found sites
makes the classification fall out for free.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kcd.commands.edit import edit_app
from kcd.commands.inspect import inspect_app


_MINIMAL_PROJ_SCH = textwrap.dedent("""
(kicad_sch
\t(version 20231120)
\t(generator "eeschema")
\t(uuid "33333333-3333-3333-3333-333333333333")
\t(paper "A4")
\t(lib_symbols)
\t(symbol
\t\t(lib_id "Device:R")
\t\t(at 100 100 0)
\t\t(unit 1)
\t\t(uuid "44444444-4444-4444-4444-444444444444")
\t\t(property "Reference" "R1" (at 100 95 0))
\t\t(property "Value" "10k" (at 100 105 0))
\t\t(property "Footprint" "" (at 100 100 0))
\t\t(property "Datasheet" "" (at 100 100 0))
\t)
)
""").strip()


@pytest.fixture
def single_sheet_proj(tmp_path: Path) -> Path:
    """A minimal one-sheet project containing just R1."""
    (tmp_path / "demo.kicad_pro").write_text("{}")
    (tmp_path / "demo.kicad_sch").write_text(_MINIMAL_PROJ_SCH)
    return tmp_path


def _invoke_json(app, *args: str) -> dict:
    runner = CliRunner()
    result = runner.invoke(app, [*args, "--json"])
    # exit_code 1 is expected here; we're testing failure envelopes
    return json.loads(result.stdout)


def test_edit_prop_missing_ref_classified_as_not_found(single_sheet_proj: Path) -> None:
    """edit prop on a ref that doesn't exist → error.code == not_found.

    Was `edit_failed` before `SymbolNotFound` was introduced — the generic
    `SchEditError` catch was misclassifying lookup misses as edit failures.
    """
    out = _invoke_json(
        edit_app, "prop", str(single_sheet_proj),
        "--ref", "DOES_NOT_EXIST", "--field", "MPN", "--value", "X",
    )
    assert out["ok"] is False
    assert out["error"]["code"] == "not_found"
    assert "DOES_NOT_EXIST" in out["error"]["message"]


def test_edit_value_missing_ref_classified_as_not_found(single_sheet_proj: Path) -> None:
    """Same classification across all five schematic edit commands."""
    out = _invoke_json(
        edit_app, "value", str(single_sheet_proj),
        "--ref", "DOES_NOT_EXIST", "--value", "X",
    )
    assert out["ok"] is False
    assert out["error"]["code"] == "not_found"


def test_inspect_ref_missing_classified_as_not_found(single_sheet_proj: Path) -> None:
    """inspect ref on a missing ref also flows through SymbolNotFound."""
    out = _invoke_json(
        inspect_app, "ref", str(single_sheet_proj), "DOES_NOT_EXIST",
    )
    assert out["ok"] is False
    assert out["error"]["code"] == "not_found"
