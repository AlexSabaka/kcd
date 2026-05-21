"""Tests for the `kcd drc --since` delta mode (Round-7).

`drc --since <snapshot>` runs DRC on a past git-backed snapshot and reports
only the by-(type,severity) counts that changed — so an agent measuring an
edit reads a tiny delta instead of re-pulling the whole report. The DRC
adapter is monkeypatched so no real kicad-cli is needed; the snapshot store
runs real git on a throwaway project.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from kcd.adapters import kicad_cli
from kcd.commands.drc import _delta, drc_cmd
from kcd.core.project import resolve
from kcd.core.snapshot import SnapshotError, SnapshotStore

_drc_app = typer.Typer()
_drc_app.command()(drc_cmd)


def _violation(vtype: str, severity: str) -> dict:
    return {"type": vtype, "severity": severity, "description": "d", "items": []}


def _proj(tmp_path: Path) -> Path:
    (tmp_path / "demo.kicad_pro").write_text("{}")
    (tmp_path / "demo.kicad_pcb").write_text("(kicad_pcb (version 1))")
    return tmp_path


# ---------------------------------------------------------------------------
# _delta — unit
# ---------------------------------------------------------------------------

def test_delta_reports_only_changed_groups() -> None:
    before = [
        {"type": "clearance", "severity": "error", "count": 5},
        {"type": "courtyard", "severity": "warning", "count": 2},
        {"type": "track_width", "severity": "error", "count": 1},
    ]
    after = [
        {"type": "clearance", "severity": "error", "count": 2},     # -3
        {"type": "courtyard", "severity": "warning", "count": 2},    # unchanged
        {"type": "silk_overlap", "severity": "warning", "count": 4},  # new +4
        # track_width is gone -> -1
    ]
    d = _delta(before, after)
    assert d["summary"] == {"before": 8, "after": 8, "delta": 0}
    changed = {(g["type"], g["severity"]): g for g in d["changed"]}
    assert set(changed) == {
        ("clearance", "error"),
        ("track_width", "error"),
        ("silk_overlap", "warning"),
    }
    assert changed[("clearance", "error")]["delta"] == -3
    assert changed[("track_width", "error")] == {
        "type": "track_width", "severity": "error",
        "before": 1, "after": 0, "delta": -1,
    }
    assert changed[("silk_overlap", "warning")] == {
        "type": "silk_overlap", "severity": "warning",
        "before": 0, "after": 4, "delta": 4,
    }


def test_delta_empty_when_nothing_changed() -> None:
    folds = [{"type": "clearance", "severity": "error", "count": 3}]
    d = _delta(folds, folds)
    assert d["changed"] == []
    assert d["summary"] == {"before": 3, "after": 3, "delta": 0}


# ---------------------------------------------------------------------------
# SnapshotStore.materialize
# ---------------------------------------------------------------------------

def test_materialize_yields_past_content(tmp_path: Path) -> None:
    """`materialize` extracts a past snapshot's files without touching the
    working tree."""
    proj_dir = _proj(tmp_path)
    pcb = proj_dir / "demo.kicad_pcb"
    store = SnapshotStore(resolve(str(proj_dir)))
    snap = store.create("baseline")

    pcb.write_text("(kicad_pcb (version 2))")   # mutate the live tree

    with store.materialize(snap.ref) as old:
        assert (old / "demo.kicad_pcb").read_text() == "(kicad_pcb (version 1))"
        assert (old / "demo.kicad_pro").read_text() == "{}"
    assert pcb.read_text() == "(kicad_pcb (version 2))"   # live tree untouched


def test_materialize_rejects_unknown_ref(tmp_path: Path) -> None:
    store = SnapshotStore(resolve(str(_proj(tmp_path))))
    store.create("v1")
    with pytest.raises(SnapshotError), store.materialize("deadbeef"):
        pass


# ---------------------------------------------------------------------------
# drc --since — command level
# ---------------------------------------------------------------------------

def test_drc_since_reports_the_delta(tmp_path: Path, monkeypatch) -> None:
    proj_dir = _proj(tmp_path)
    snap = SnapshotStore(resolve(str(proj_dir))).create("baseline")

    def fake_run_drc(cli, pcb_path, report):
        # the snapshot copy is materialized under a temp 'kcd-snap-' dir
        if "kcd-snap-" in str(pcb_path):
            return {"violations": [_violation("clearance", "error")] * 3}
        return {"violations": [_violation("clearance", "error")]}

    monkeypatch.setattr(kicad_cli, "run_drc", fake_run_drc)
    r = CliRunner().invoke(
        _drc_app,
        [str(proj_dir), "--out", str(tmp_path / "rep.json"),
         "--since", snap.ref, "--json"],
    )
    assert r.exit_code == 0, r.stdout
    data = json.loads(r.stdout)["data"]
    assert data["since"] == snap.ref
    assert data["summary"] == {"before": 3, "after": 1, "delta": -2}
    assert len(data["changed"]) == 1
    assert data["changed"][0]["type"] == "clearance"
    assert data["changed"][0]["delta"] == -2
    assert "violations" not in data   # the folded list is dropped — the token win


def test_drc_since_unknown_ref_is_clean_error(
    tmp_path: Path, monkeypatch,
) -> None:
    proj_dir = _proj(tmp_path)
    SnapshotStore(resolve(str(proj_dir))).create("v1")
    monkeypatch.setattr(
        kicad_cli, "run_drc", lambda *a, **k: {"violations": []}
    )
    r = CliRunner().invoke(
        _drc_app,
        [str(proj_dir), "--out", str(tmp_path / "rep.json"),
         "--since", "nonexistent", "--json"],
    )
    assert r.exit_code == 1
    assert json.loads(r.stdout)["error"]["code"] == "not_found"


def test_drc_without_since_keeps_the_full_fold(
    tmp_path: Path, monkeypatch,
) -> None:
    """Plain `drc` (no --since) is unchanged — the folded violations ride."""
    proj_dir = _proj(tmp_path)
    monkeypatch.setattr(
        kicad_cli, "run_drc",
        lambda *a, **k: {"violations": [_violation("clearance", "error")]},
    )
    r = CliRunner().invoke(
        _drc_app,
        [str(proj_dir), "--out", str(tmp_path / "rep.json"), "--json"],
    )
    assert r.exit_code == 0, r.stdout
    data = json.loads(r.stdout)["data"]
    assert "violations" in data
    assert "changed" not in data
