"""Runtime configuration: paths, defaults, environment lookups."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    """Resolved runtime configuration for kcd."""

    kicad_cli: str
    """Path to the `kicad-cli` binary."""

    freerouting_jar: str | None
    """Path to FreeRouting JAR (optional, needed only for autorouting)."""

    snapshot_dir_name: str
    """Directory name for the per-project snapshot git repo. Default: `.kcd`."""

    auto_snapshot: bool
    """If True, every mutating command snapshots before executing."""

    auto_render: bool
    """If True, every mutating command renders the affected sheet/board after."""

    render_cache_dir: Path
    """Where auto-renders go (`/tmp/kcd/` by default). Last edit lands at
    `<render_cache_dir>/last-edit.{png,svg}`."""


def load() -> Config:
    """Load configuration from environment variables with sensible defaults.

    Environment variables (all optional):
        KCD_KICAD_CLI       — path to `kicad-cli`, default: search PATH
        KCD_FREEROUTING_JAR — path to FreeRouting JAR
        KCD_SNAPSHOT_DIR    — snapshot subdir name, default: `.kcd`
        KCD_AUTO_SNAPSHOT   — `0` to disable, default enabled
        KCD_AUTO_RENDER     — `0` to disable, default enabled
        KCD_RENDER_CACHE    — render output dir, default `/tmp/kcd`
    """
    kicad_cli = os.environ.get("KCD_KICAD_CLI") or shutil.which("kicad-cli") or "kicad-cli"
    freerouting = os.environ.get("KCD_FREEROUTING_JAR")
    snapshot_dir = os.environ.get("KCD_SNAPSHOT_DIR", ".kcd")
    auto_snap = os.environ.get("KCD_AUTO_SNAPSHOT", "1") != "0"
    auto_render = os.environ.get("KCD_AUTO_RENDER", "1") != "0"
    cache = Path(os.environ.get("KCD_RENDER_CACHE", "/tmp/kcd"))

    return Config(
        kicad_cli=kicad_cli,
        freerouting_jar=freerouting,
        snapshot_dir_name=snapshot_dir,
        auto_snapshot=auto_snap,
        auto_render=auto_render,
        render_cache_dir=cache,
    )
