"""Tests for the `snapshot restore` IPC-sync flow (Dove session-3 #18).

Validates that `restore` attempts `kipy_pcb.revert_board()` after the file
revert, exposing the result in `data.kicad_reverted` and warning loudly only
when the editor is reachable but the revert itself fails.

Implementation under test:
    `kcd snapshot restore` calls `SnapshotStore.restore` (file-side), then
    `kipy_pcb.revert_board` (memory-side). The latter is mocked here — real
    IPC interaction is covered by `tests/test_agentic_loop.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kcd.commands.snapshot import snapshot_app


@pytest.fixture
def stub_proj(monkeypatch, tmp_path: Path) -> Path:
    """A tmp project directory with stubbed SnapshotStore.restore.

    We're testing the *post-restore* logic (the new revert_board hook), not
    git mechanics — so SnapshotStore.restore is monkeypatched to return a
    fixed SnapshotInfo without touching the filesystem.
    """
    proj_dir = tmp_path / "demo"
    proj_dir.mkdir()
    (proj_dir / "demo.kicad_pro").write_text("{}")
    (proj_dir / "demo.kicad_sch").write_text("(kicad_sch (version 20231120))")

    from kcd.core.snapshot import SnapshotInfo, SnapshotStore
    fake_info = SnapshotInfo(
        ref="abc123def4567890",
        short="abc123d",
        message="test snapshot",
        timestamp="2026-05-19T12:00:00Z",
    )
    monkeypatch.setattr(SnapshotStore, "restore", lambda self, ref: fake_info)
    return proj_dir


def _invoke_restore(proj_dir: Path) -> dict:
    runner = CliRunner()
    result = runner.invoke(
        snapshot_app,
        ["restore", str(proj_dir), "abc123d", "--yes", "--json"],
    )
    assert result.exit_code == 0, f"exit {result.exit_code}: {result.stdout}"
    return json.loads(result.stdout)


def test_restore_when_kicad_unavailable_warns(monkeypatch, stub_proj: Path) -> None:
    """IpcUnavailable from revert_board → kicad_reverted=False *with* a warning.

    Dove session-4 #21: an agent that doesn't unpack `data.kicad_reverted` and
    runs a mutating IPC command next will overwrite the restored file with
    stale KiCad memory. The warning surfaces that hazard at envelope level so
    no consumer is silently exposed.
    """
    from kcd.adapters import kipy_pcb
    from kcd.core.ipc import IpcUnavailable

    def raise_ipc() -> None:
        raise IpcUnavailable("no editor open")

    monkeypatch.setattr(kipy_pcb, "revert_board", raise_ipc)

    out = _invoke_restore(stub_proj)
    assert out["ok"] is True
    assert out["data"]["kicad_reverted"] is False
    assert any("not synced" in w for w in out["warnings"])
    assert any("Reload the .kicad_pcb" in w for w in out["warnings"])


def test_restore_when_revert_succeeds_marks_reverted(monkeypatch, stub_proj: Path) -> None:
    """Happy path: KiCad open, revert succeeds → kicad_reverted=True."""
    from kcd.adapters import kipy_pcb

    calls: list[str] = []
    monkeypatch.setattr(kipy_pcb, "revert_board", lambda: calls.append("revert"))

    out = _invoke_restore(stub_proj)
    assert out["ok"] is True
    assert out["data"]["kicad_reverted"] is True
    assert calls == ["revert"]
    assert out["warnings"] == []


def test_restore_when_revert_raises_warns_but_succeeds(monkeypatch, stub_proj: Path) -> None:
    """Non-IpcUnavailable error from revert_board: file restore stands,
    but in-memory state may be stale → warn loudly and mark not-reverted.

    The restore itself succeeded (disk is correct), so the envelope is still
    ok=True; the warning is the agent's signal that one piece didn't land.
    """
    from kcd.adapters import kipy_pcb

    def raise_api() -> None:
        raise RuntimeError("simulated KiCad ApiError: document busy")

    monkeypatch.setattr(kipy_pcb, "revert_board", raise_api)

    out = _invoke_restore(stub_proj)
    assert out["ok"] is True
    assert out["data"]["kicad_reverted"] is False
    assert any("in-memory board may be stale" in w for w in out["warnings"])
    assert any("File → Revert" in w for w in out["warnings"])
