"""Tests for `kcd edit designrules` — board design-rule editing (Wave 7 A).

The command layer is exercised through the Typer `edit_app`; `set_design_rule`,
the pure JSON-mutation logic, is also unit-tested directly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kcd.adapters import kicad_pro
from kcd.commands.edit import edit_app
from kcd.core.output import CommandError

_NET_FIXTURE = Path(__file__).parent / "fixtures" / "net"


@pytest.fixture
def proj_dir(tmp_path: Path) -> Path:
    """A dir with just a (minimal) .kicad_pro — enough for `resolve()`."""
    (tmp_path / "net_fixture.kicad_pro").write_text(
        (_NET_FIXTURE / "net_fixture.kicad_pro").read_text()
    )
    return tmp_path


def _pro(proj_dir: Path) -> dict:
    return json.loads((proj_dir / "net_fixture.kicad_pro").read_text())


# ---------------------------------------------------------------------------
# edit designrules — command layer
# ---------------------------------------------------------------------------

def test_designrules_envelope_and_nested_path(proj_dir: Path) -> None:
    """The minimal fixture has no `board` block — it must be created."""
    r = CliRunner().invoke(
        edit_app,
        ["designrules", str(proj_dir), "--rule", "min_track_width",
         "--value", "0.2", "--no-snapshot", "--json"],
    )
    assert r.exit_code == 0, r.stdout
    out = json.loads(r.stdout)
    assert out["ok"] is True
    assert out["command"] == "edit.designrules"
    assert out["data"]["updated"]["rule"] == "min_track_width"
    assert out["data"]["updated"]["before"] is None
    assert out["data"]["updated"]["after"] == 0.2
    assert any("KiCad" in w for w in out["warnings"])

    rules = _pro(proj_dir)["board"]["design_settings"]["rules"]
    assert rules["min_track_width"] == 0.2


def test_designrules_bool_coercion(proj_dir: Path) -> None:
    r = CliRunner().invoke(
        edit_app,
        ["designrules", str(proj_dir), "--rule", "use_height_for_length_calcs",
         "--value", "false", "--no-snapshot", "--json"],
    )
    assert r.exit_code == 0, r.stdout
    out = json.loads(r.stdout)
    assert out["data"]["updated"]["after"] is False
    assert _pro(proj_dir)["board"]["design_settings"]["rules"][
        "use_height_for_length_calcs"
    ] is False


def test_designrules_unknown_rule(proj_dir: Path) -> None:
    r = CliRunner().invoke(
        edit_app,
        ["designrules", str(proj_dir), "--rule", "bogus_rule",
         "--value", "1", "--no-snapshot", "--json"],
    )
    assert r.exit_code == 1
    assert json.loads(r.stdout)["error"]["code"] == "unknown_rule"


def test_designrules_bad_value(proj_dir: Path) -> None:
    r = CliRunner().invoke(
        edit_app,
        ["designrules", str(proj_dir), "--rule", "min_track_width",
         "--value", "abc", "--no-snapshot", "--json"],
    )
    assert r.exit_code == 1
    assert json.loads(r.stdout)["error"]["code"] == "bad_value"


def test_designrules_bad_project_file(proj_dir: Path) -> None:
    (proj_dir / "net_fixture.kicad_pro").write_text("{not valid json")
    r = CliRunner().invoke(
        edit_app,
        ["designrules", str(proj_dir), "--rule", "min_clearance",
         "--value", "0.15", "--no-snapshot", "--json"],
    )
    assert r.exit_code == 1
    assert json.loads(r.stdout)["error"]["code"] == "bad_project_file"


# ---------------------------------------------------------------------------
# set_design_rule — adapter
# ---------------------------------------------------------------------------

def test_set_design_rule_preserves_existing_keys(tmp_path: Path) -> None:
    pro = tmp_path / "p.kicad_pro"
    pro.write_text(json.dumps({
        "board": {"design_settings": {"rules": {
            "min_clearance": 0.1,
            "min_via_diameter": 0.5,
        }}},
        "meta": {"version": 1},
    }))
    result = kicad_pro.set_design_rule(pro, "min_via_diameter", "0.6")
    assert result["before"] == 0.5
    assert result["after"] == 0.6

    data = json.loads(pro.read_text())
    rules = data["board"]["design_settings"]["rules"]
    assert rules["min_via_diameter"] == 0.6
    assert rules["min_clearance"] == 0.1  # untouched
    assert data["meta"] == {"version": 1}  # untouched


def test_set_design_rule_unknown_raises(tmp_path: Path) -> None:
    pro = tmp_path / "p.kicad_pro"
    pro.write_text("{}")
    with pytest.raises(CommandError) as exc:
        kicad_pro.set_design_rule(pro, "not_a_rule", "1")
    assert exc.value.code == "unknown_rule"


def test_set_design_rule_int_rejects_float(tmp_path: Path) -> None:
    pro = tmp_path / "p.kicad_pro"
    pro.write_text("{}")
    with pytest.raises(CommandError) as exc:
        kicad_pro.set_design_rule(pro, "min_resolved_spokes", "2.5")
    assert exc.value.code == "bad_value"
