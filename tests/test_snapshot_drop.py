"""Tests for snapshot-on-failure cleanup (Round-2 field report bug #5).

A mutating command auto-snapshots *before* it runs. When the mutation then
fails, that snapshot records an edit that never landed — pure history noise.
`run_command` now discards it via `SnapshotStore.drop`; a snapshot for a
mutation that *did* land is kept.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kcd.commands.edit import edit_app
from kcd.core.project import resolve
from kcd.core.snapshot import SnapshotStore

_NET_FIXTURE = Path(__file__).parent / "fixtures" / "net"


# ---------------------------------------------------------------------------
# SnapshotStore.drop — git mechanics
# ---------------------------------------------------------------------------

def test_drop_removes_the_head_snapshot(tmp_path: Path) -> None:
    (tmp_path / "p.kicad_pro").write_text("{}")
    store = SnapshotStore(resolve(str(tmp_path)))
    store.create("before: edit one")
    second = store.create("before: edit two")

    store.drop(second.ref)

    msgs = [s.message for s in store.list()]
    assert "before: edit two" not in msgs
    assert "before: edit one" in msgs


def test_drop_is_noop_when_ref_is_not_head(tmp_path: Path) -> None:
    """Dropping a stale ref must never clobber a newer snapshot."""
    (tmp_path / "p.kicad_pro").write_text("{}")
    store = SnapshotStore(resolve(str(tmp_path)))
    first = store.create("before: edit one")
    store.create("before: edit two")

    store.drop(first.ref)  # first is no longer HEAD

    msgs = [s.message for s in store.list()]
    assert "before: edit one" in msgs
    assert "before: edit two" in msgs


# ---------------------------------------------------------------------------
# run_command — drop on failure, keep on success
# ---------------------------------------------------------------------------

@pytest.fixture
def proj_dir(tmp_path: Path) -> Path:
    """A real one-sheet project copied from the net fixture."""
    for ext in ("kicad_pro", "kicad_sch"):
        (tmp_path / f"net_fixture.{ext}").write_text(
            (_NET_FIXTURE / f"net_fixture.{ext}").read_text()
        )
    return tmp_path


def _before_snapshots(proj_dir: Path) -> list[str]:
    """Messages of the auto-snapshots taken before edits in this project."""
    store = SnapshotStore(resolve(str(proj_dir)))
    return [s.message for s in store.list() if s.message.startswith("before:")]


def test_failed_edit_drops_its_snapshot(proj_dir: Path) -> None:
    """An edit that fails after the pre-edit snapshot leaves no snapshot."""
    r = CliRunner().invoke(
        edit_app,
        ["value", str(proj_dir), "--ref", "NONEXISTENT", "--value", "1k",
         "--no-render", "--json"],
    )
    assert r.exit_code == 1
    out = json.loads(r.stdout)
    assert out["ok"] is False
    # The snapshot for the edit that never landed is discarded.
    assert out["snapshot_before"] is None
    assert _before_snapshots(proj_dir) == []


def test_successful_edit_keeps_its_snapshot(proj_dir: Path) -> None:
    """A landed mutation keeps its pre-edit snapshot as a rollback point."""
    r = CliRunner().invoke(
        edit_app,
        ["text", "titleblock", str(proj_dir), "--field", "rev",
         "--value", "B", "--no-render", "--json"],
    )
    assert r.exit_code == 0, r.stdout
    out = json.loads(r.stdout)
    assert out["snapshot_before"]
    assert len(_before_snapshots(proj_dir)) == 1
