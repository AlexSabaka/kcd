"""Tests for `kcd snapshot diff` folding (Round-3 field report B4).

A zone-fill in a `.kicad_pcb` makes the raw unified diff thousands of lines —
it overran the 1MB MCP cap when inlined whole. `diff` now inlines a per-file
summary (and a small diff body), spilling a large body to the artifact. The
artifact always holds the complete unified diff.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kcd.commands.snapshot import snapshot_app
from kcd.core.project import resolve
from kcd.core.snapshot import SnapshotStore

# ---------------------------------------------------------------------------
# SnapshotStore.diff_summary — git --numstat rollup
# ---------------------------------------------------------------------------

def test_diff_summary_per_file_counts(tmp_path: Path) -> None:
    (tmp_path / "p.kicad_pro").write_text("{}\n")
    (tmp_path / "p.kicad_sch").write_text("line1\nline2\n")
    store = SnapshotStore(resolve(str(tmp_path)))
    base = store.create("base")

    (tmp_path / "p.kicad_sch").write_text("line1\nline2 changed\nline3\n")
    summary = store.diff_summary(base.ref)

    assert summary["files_changed"] == 1
    assert summary["files"][0]["path"] == "p.kicad_sch"
    assert summary["added"] > 0
    assert summary["removed"] > 0


def test_diff_summary_empty_when_no_change(tmp_path: Path) -> None:
    (tmp_path / "p.kicad_pro").write_text("{}\n")
    store = SnapshotStore(resolve(str(tmp_path)))
    base = store.create("base")
    summary = store.diff_summary(base.ref)
    assert summary == {"files_changed": 0, "added": 0, "removed": 0, "files": []}


# ---------------------------------------------------------------------------
# `kcd snapshot diff` command — inline small, spill large
# ---------------------------------------------------------------------------

@pytest.fixture
def proj_dir(tmp_path: Path, monkeypatch) -> Path:
    """A project dir with the render cache pinned inside tmp (hermetic)."""
    monkeypatch.setenv("KCD_RENDER_CACHE", str(tmp_path / "cache"))
    (tmp_path / "p.kicad_pro").write_text("{}\n")
    (tmp_path / "p.kicad_pcb").write_text("(kicad_pcb)\n")
    return tmp_path


def _diff(proj_dir: Path, ref: str) -> dict:
    r = CliRunner().invoke(snapshot_app, ["diff", str(proj_dir), ref, "--json"])
    assert r.exit_code == 0, r.stdout
    return json.loads(r.stdout)


def test_diff_small_body_rides_inline(proj_dir: Path) -> None:
    store = SnapshotStore(resolve(str(proj_dir)))
    base = store.create("base")
    (proj_dir / "p.kicad_pcb").write_text("(kicad_pcb)\n(segment 1)\n")

    out = _diff(proj_dir, base.ref)
    data = out["data"]
    assert data["files_changed"] == 1
    assert data["added"] > 0
    assert "(segment 1)" in data["diff"]            # small body inlined
    assert out["artifacts"][0]["kind"] == "snapshot_diff"


def test_diff_large_body_spills_to_artifact(proj_dir: Path) -> None:
    store = SnapshotStore(resolve(str(proj_dir)))
    base = store.create("base")
    big = "(kicad_pcb)\n" + "\n".join(f"(segment {i})" for i in range(3000))
    (proj_dir / "p.kicad_pcb").write_text(big)

    out = _diff(proj_dir, base.ref)
    data = out["data"]
    # body too large to inline — only the summary rides in `data`
    assert data["diff_inlined"] is False
    assert "diff" not in data
    assert data["files_changed"] == 1
    assert any("too large to inline" in w for w in out["warnings"])

    # the artifact holds the complete unified diff
    artifact = Path(out["artifacts"][0]["path"])
    full = artifact.read_text()
    assert "(segment 2999)" in full
