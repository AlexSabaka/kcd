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

    symbol_dir: Path | None
    """Directory holding KiCad's standard `.kicad_sym` symbol libraries, or
    None if it couldn't be located. Override with `KCD_SYMBOL_DIR`."""

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

    kicad_cli_timeout: int
    """Hard timeout (seconds) for any `kicad-cli` subprocess call. 60s by
    default — generous enough for normal renders, short enough that an
    interactive prompt (e.g. old-format conversion) surfaces as a structured
    error within ~a minute instead of hanging the agent forever."""


def load() -> Config:
    """Load configuration from environment variables with sensible defaults.

    Environment variables (all optional):
        KCD_KICAD_CLI       — path to `kicad-cli`, default: search PATH
        KCD_SYMBOL_DIR      — KiCad standard symbol-library dir, default:
                              auto-detect from platform install locations
        KCD_FREEROUTING_JAR — path to FreeRouting JAR
        KCD_SNAPSHOT_DIR    — snapshot subdir name, default: `.kcd`
        KCD_AUTO_SNAPSHOT   — `0` to disable, default enabled
        KCD_AUTO_RENDER     — `0` to disable, default enabled
        KCD_RENDER_CACHE    — render output dir, default `/tmp/kcd`
        KCD_KICAD_CLI_TIMEOUT — subprocess timeout in seconds, default `60`
    """
    kicad_cli = os.environ.get("KCD_KICAD_CLI") or shutil.which("kicad-cli") or "kicad-cli"
    symbol_dir = _find_symbol_dir()
    freerouting = os.environ.get("KCD_FREEROUTING_JAR")
    snapshot_dir = os.environ.get("KCD_SNAPSHOT_DIR", ".kcd")
    auto_snap = os.environ.get("KCD_AUTO_SNAPSHOT", "1") != "0"
    auto_render = os.environ.get("KCD_AUTO_RENDER", "1") != "0"
    cache = Path(os.environ.get("KCD_RENDER_CACHE", "/tmp/kcd"))
    cli_timeout = int(os.environ.get("KCD_KICAD_CLI_TIMEOUT", "60"))

    return Config(
        kicad_cli=kicad_cli,
        symbol_dir=symbol_dir,
        freerouting_jar=freerouting,
        snapshot_dir_name=snapshot_dir,
        auto_snapshot=auto_snap,
        auto_render=auto_render,
        render_cache_dir=cache,
        kicad_cli_timeout=cli_timeout,
    )


def _find_symbol_dir() -> Path | None:
    """Locate KiCad's standard symbol-library directory.

    `KCD_SYMBOL_DIR` wins if set (returned as-is — trust the override). Else
    probe the known per-platform install locations and return the first that
    exists. `kicad-cli` can't be used to derive this — it's often a separate
    install (e.g. Homebrew) from the GUI app that ships the symbols.
    """
    env = os.environ.get("KCD_SYMBOL_DIR")
    if env:
        return Path(env)
    candidates = [
        Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols"),
        Path("/usr/share/kicad/symbols"),
        Path("/usr/local/share/kicad/symbols"),
    ]
    for base in (Path("C:/Program Files/KiCad"), Path("C:/Program Files (x86)/KiCad")):
        if base.is_dir():
            candidates.extend(
                ver / "share" / "kicad" / "symbols"
                for ver in sorted(base.iterdir(), reverse=True)
            )
    for c in candidates:
        if c.is_dir():
            return c
    return None
