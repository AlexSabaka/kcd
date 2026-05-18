"""Smoke tests that don't require KiCad to be installed.

These verify the CLI structure, config loading, snapshot store, and project
resolution work in isolation. Tests that need a real .kicad_pro file live in
test_integration.py (skipped if no kicad-cli on PATH).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


def test_import_package() -> None:
    """The package imports cleanly."""
    import kcd
    assert kcd.__version__


def test_cli_help() -> None:
    """`kcd --help` returns successfully and lists subcommands."""
    result = subprocess.run(
        [sys.executable, "-m", "kcd", "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    for sub in ("snapshot", "render", "inspect", "edit", "net", "drc", "erc", "export", "route"):
        assert sub in result.stdout, f"subcommand {sub} missing from --help"


def test_config_defaults() -> None:
    """Config loads with environment defaults."""
    from kcd.core import config
    cfg = config.load()
    assert cfg.snapshot_dir_name == ".kcd"
    assert cfg.auto_snapshot is True
    assert cfg.auto_render is True


def test_project_resolve_missing(tmp_path: Path) -> None:
    """Resolving a non-existent project raises FileNotFoundError."""
    from kcd.core.project import resolve
    with pytest.raises(FileNotFoundError):
        resolve(tmp_path)


def test_project_resolve_directory(tmp_path: Path) -> None:
    """Resolving a directory with one .kicad_pro file works."""
    pro = tmp_path / "demo.kicad_pro"
    pro.write_text('{"meta": {"filename": "demo.kicad_pro"}}')
    from kcd.core.project import resolve
    proj = resolve(tmp_path)
    assert proj.name == "demo"
    assert proj.root == tmp_path
    assert proj.pro == pro
    assert proj.sch == tmp_path / "demo.kicad_sch"
    assert proj.pcb == tmp_path / "demo.kicad_pcb"


def test_snapshot_create_and_list(tmp_path: Path) -> None:
    """Snapshot store can init, commit, and list."""
    pro = tmp_path / "demo.kicad_pro"
    pro.write_text("{}")
    sch = tmp_path / "demo.kicad_sch"
    sch.write_text("(kicad_sch)")

    from kcd.core.project import resolve
    from kcd.core.snapshot import SnapshotStore

    proj = resolve(tmp_path)
    store = SnapshotStore(proj)
    info = store.create("first snapshot")
    assert info.ref
    assert info.message == "first snapshot"

    # Modify a file
    sch.write_text("(kicad_sch (modified))")
    info2 = store.create("second snapshot")
    assert info2.ref != info.ref

    items = store.list()
    assert len(items) >= 2
    assert items[0].ref == info2.ref


def test_snapshot_restore(tmp_path: Path) -> None:
    """Snapshot restore puts the working tree back."""
    pro = tmp_path / "demo.kicad_pro"
    pro.write_text("{}")
    sch = tmp_path / "demo.kicad_sch"
    sch.write_text("(kicad_sch original)")

    from kcd.core.project import resolve
    from kcd.core.snapshot import SnapshotStore

    proj = resolve(tmp_path)
    store = SnapshotStore(proj)
    info1 = store.create("original state")

    sch.write_text("(kicad_sch modified)")
    store.create("modified state")
    assert "modified" in sch.read_text()

    store.restore(info1.ref)
    assert "original" in sch.read_text()
    assert "modified" not in sch.read_text()


def test_result_envelope() -> None:
    """Result objects serialize to the documented JSON shape."""
    from kcd.core.output import Result
    r = Result(command="test.cmd")
    r.data = {"foo": "bar"}
    r.add_artifact("png", "/tmp/x.png", dpi=300)
    r.warn("hi")
    d = r.to_dict()
    assert d["ok"] is True
    assert d["command"] == "test.cmd"
    assert d["data"] == {"foo": "bar"}
    assert d["artifacts"][0]["kind"] == "png"
    assert d["artifacts"][0]["dpi"] == 300
    assert d["warnings"] == ["hi"]
    assert d["error"] is None


def test_result_failure() -> None:
    """Result.fail sets ok=False and populates error."""
    from kcd.core.output import Result
    r = Result(command="test.cmd")
    r.fail("bad_input", "something went wrong")
    d = r.to_dict()
    assert d["ok"] is False
    assert d["error"]["code"] == "bad_input"
    assert d["error"]["message"] == "something went wrong"
