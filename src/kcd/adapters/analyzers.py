"""Subprocess wrappers around the vendored kicad-happy analyzer scripts.

The analyzers live at `skills/kicad/scripts/` — at the repo root in source
layout, and under `kcd/skills/kicad/scripts/` in the installed wheel thanks
to the `force-include` rule in `pyproject.toml`. Each prints structured JSON
on stdout; this module subprocess-invokes them with a hard timeout and
returns the parsed dict.

Pattern mirrors `kcd.adapters.kicad_cli._run`: no stdin, captured stdout/stderr,
timeout. Non-zero exit (or empty/non-JSON stdout) raises `CliError` so the
envelope ladder maps it to `error.code: "cli_failed"`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from kcd.adapters.kicad_cli import CliError


def _locate_scripts_dir() -> Path:
    """Find the vendored analyzer scripts directory.

    Checks source-tree layout first, then the installed-wheel layout. Either
    path produces the same answer for script *names* — only the parent
    location differs depending on how kcd was installed.
    """
    here = Path(__file__).resolve()
    candidates = [
        # Source: src/kcd/adapters/analyzers.py → repo-root/skills/kicad/scripts/
        here.parents[3] / "skills" / "kicad" / "scripts",
        # Wheel:  kcd/adapters/analyzers.py     → kcd/skills/kicad/scripts/
        here.parents[1] / "skills" / "kicad" / "scripts",
    ]
    for c in candidates:
        if c.is_dir():
            return c
    raise FileNotFoundError(
        "Could not locate skills/kicad/scripts/. Tried: "
        + ", ".join(str(c) for c in candidates)
    )


def run_analyzer(
    script_name: str,
    target: Path | str,
    extra_args: list[str] | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    """Subprocess-invoke a vendored analyzer; return parsed JSON.

    Args:
        script_name: filename in `skills/kicad/scripts/` (e.g.
            `"analyze_pcb.py"`).
        target: path to the file or directory the analyzer should consume
            (`.kicad_sch`, `.kicad_pcb`, or a gerber directory).
        extra_args: optional additional CLI flags forwarded to the analyzer.
        timeout: subprocess timeout in seconds. 120s default — the schematic
            analyzer is the slowest (~1–3s on a typical board), but
            cross_analysis on a large board can run several times longer.

    Returns: parsed JSON dict from the analyzer's stdout.

    Raises:
        FileNotFoundError: `script_name` not present in
            `skills/kicad/scripts/` (packaging / vendor mismatch).
        CliError: subprocess returned non-zero exit, timed out, or wrote
            non-JSON to stdout. The envelope ladder maps this to
            `error.code: "cli_failed"`.
    """
    scripts_dir = _locate_scripts_dir()
    script = scripts_dir / script_name
    if not script.is_file():
        raise FileNotFoundError(
            f"Analyzer script not found: {script} (in {scripts_dir})"
        )
    cmd: list[str] = [sys.executable, str(script), str(target)]
    if extra_args:
        cmd.extend(extra_args)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise CliError(
            cmd,
            -1,
            (e.stdout.decode() if isinstance(e.stdout, bytes) else e.stdout) or "",
            (e.stderr.decode() if isinstance(e.stderr, bytes) else e.stderr)
            or f"analyzer {script_name} timed out after {timeout}s",
        ) from e
    if proc.returncode != 0:
        raise CliError(cmd, proc.returncode, proc.stdout, proc.stderr)
    if not proc.stdout.strip():
        raise CliError(
            cmd, 0, proc.stdout,
            f"analyzer {script_name} returned empty stdout",
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise CliError(
            cmd, 0, proc.stdout[:1000],
            f"analyzer {script_name} stdout was not valid JSON: {e}",
        ) from e
