"""Tests for `_post_edit_sch` artifact attribution (Dove session-2 #12).

The cache dir defaults to /tmp/kcd and is shared across projects. Before
the fix, the post-edit code globbed *.svg unconditionally and surfaced
stale files from prior sessions as artifacts. After: only files whose
mtime *changed* count.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from kcd.adapters import kicad_cli
from kcd.commands import edit as edit_cmd
from kcd.core.output import Result
from kcd.core.project import Project


@pytest.fixture
def tmp_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point KCD_RENDER_CACHE at a clean tmp dir for the duration of the test."""
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setenv("KCD_RENDER_CACHE", str(cache))
    return cache


@pytest.fixture
def fake_proj(tmp_path: Path) -> Project:
    """A Project that points at non-existent files — _post_edit_sch never reads them."""
    return Project(
        root=tmp_path,
        pro=tmp_path / "demo.kicad_pro",
        name="demo",
    )


def test_post_edit_sch_skips_stale_svgs(
    tmp_cache: Path, fake_proj: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pre-existing SVG with an unchanged mtime must NOT appear in artifacts."""
    stale = tmp_cache / "old_project.svg"
    stale.write_text("<svg/>")
    # Pin its mtime in the past so any post-render touch is detectable.
    past = stale.stat().st_mtime_ns - 5_000_000_000  # 5 seconds ago
    os.utime(stale, ns=(past, past))

    fresh_path = tmp_cache / "demo.svg"

    def fake_export(cli: str, sch: Path, out_dir: Path) -> Path:
        fresh_path.write_text("<svg/>")
        return out_dir

    monkeypatch.setattr(kicad_cli, "export_sch_svg", fake_export)

    r = Result(command="edit.value")
    edit_cmd._post_edit_sch(fake_proj, r)

    artifact_paths = [a["path"] for a in r.to_dict()["artifacts"]]
    assert str(fresh_path) in artifact_paths
    assert str(stale) not in artifact_paths


def test_post_edit_sch_includes_refreshed_svgs(
    tmp_cache: Path, fake_proj: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An existing SVG that kicad-cli *re-renders* (mtime bumped) MUST appear."""
    existing = tmp_cache / "demo.svg"
    existing.write_text("<svg/>")
    past = existing.stat().st_mtime_ns - 5_000_000_000
    os.utime(existing, ns=(past, past))

    def fake_export(cli: str, sch: Path, out_dir: Path) -> Path:
        existing.write_text("<svg modified/>")  # bumps mtime
        return out_dir

    monkeypatch.setattr(kicad_cli, "export_sch_svg", fake_export)

    r = Result(command="edit.value")
    edit_cmd._post_edit_sch(fake_proj, r)

    artifact_paths = [a["path"] for a in r.to_dict()["artifacts"]]
    assert str(existing) in artifact_paths


def test_post_edit_sch_warns_on_cli_failure(
    tmp_cache: Path, fake_proj: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A kicad-cli failure must degrade to a warning, not raise — and produce no artifacts."""

    def fake_export(cli: str, sch: Path, out_dir: Path) -> Path:
        raise kicad_cli.CliError(["kicad-cli"], 1, "", "boom")

    monkeypatch.setattr(kicad_cli, "export_sch_svg", fake_export)

    r = Result(command="edit.value")
    edit_cmd._post_edit_sch(fake_proj, r)

    d = r.to_dict()
    assert d["artifacts"] == []
    assert any("Auto-render failed" in w for w in d["warnings"])


def test_post_edit_sch_respects_no_render(
    tmp_cache: Path, fake_proj: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`no_render=True` short-circuits — no glob, no kicad-cli call."""
    called = {"export": False}

    def fake_export(cli: str, sch: Path, out_dir: Path) -> Path:
        called["export"] = True
        return out_dir

    monkeypatch.setattr(kicad_cli, "export_sch_svg", fake_export)

    r = Result(command="edit.value")
    edit_cmd._post_edit_sch(fake_proj, r, no_render=True)

    assert called["export"] is False
    assert r.to_dict()["artifacts"] == []
