"""Subprocess wrappers around the vendored kicad-happy analyzer engine.

The analyzer scripts live at `src/kcd/analyzers/` in the source tree and
`kcd/analyzers/` in the installed wheel — shipped natively as part of the
`kcd` package, no force-include needed. Each prints structured JSON on
stdout; this module subprocess-invokes them with a hard timeout and returns
the parsed dict.

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
    """Find the vendored analyzer engine directory.

    `analyzers.py` sits at `kcd/adapters/`, so the engine is always its
    grandparent's `analyzers/` — `src/kcd/analyzers/` in the source tree and
    `kcd/analyzers/` in the installed wheel. One path resolves both layouts.
    """
    scripts_dir = Path(__file__).resolve().parents[1] / "analyzers"
    if scripts_dir.is_dir():
        return scripts_dir
    raise FileNotFoundError(
        f"Could not locate the analyzer engine directory: {scripts_dir}"
    )


def run_analyzer_argv(
    script_name: str,
    argv: list[str],
    timeout: int = 120,
) -> dict[str, Any]:
    """Subprocess-invoke a vendored analyzer with an explicit arg list.

    The general form behind `run_analyzer`: some analyzers take more than a
    single positional target (e.g. `cross_analysis.py -s sch.json -p
    pcb.json`, `diff_analysis.py base head`), so callers pass the full
    argument vector themselves.

    Args:
        script_name: filename in `kcd/analyzers/` (e.g. `"cross_analysis.py"`).
        argv: arguments passed to the analyzer, after the script path.
        timeout: subprocess timeout in seconds. 120s default - the schematic
            analyzer is the slowest (~1-3s on a typical board), but
            cross_analysis on a large board can run several times longer.

    Returns: parsed JSON dict from the analyzer's stdout.

    Raises:
        FileNotFoundError: `script_name` not present in `kcd/analyzers/`
            (packaging / vendor mismatch).
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
    cmd: list[str] = [sys.executable, str(script), *argv]
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


def run_analyzer(
    script_name: str,
    target: Path | str,
    extra_args: list[str] | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    """Subprocess-invoke a single-positional-target analyzer; return parsed JSON.

    Convenience wrapper over `run_analyzer_argv` for the common case — an
    analyzer that consumes one file or directory (`analyze_schematic.py`,
    `analyze_pcb.py`, `analyze_gerbers.py`).
    """
    return run_analyzer_argv(
        script_name, [str(target), *(extra_args or [])], timeout
    )
