"""Subprocess wrappers around `kicad-cli`.

kicad-cli is the workhorse for headless rendering, DRC, ERC, and most exports.
We wrap it with consistent error handling and typed outputs.

References: https://docs.kicad.org/master/en/cli/cli.html
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


class CliError(RuntimeError):
    """Raised when kicad-cli returns a non-zero exit code."""

    def __init__(self, cmd: list[str], returncode: int, stdout: str, stderr: str):
        self.cmd = cmd
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(
            f"kicad-cli failed (exit {returncode}): {' '.join(cmd)}\n"
            f"stderr: {stderr.strip()}"
        )


@dataclass(frozen=True)
class CliResult:
    stdout: str
    stderr: str


def _run(cli: str, *args: str, timeout: int | None = None) -> CliResult:
    """Invoke kicad-cli with a hard timeout and no stdin.

    `stdin=subprocess.DEVNULL` prevents interactive prompts (e.g. "convert
    old-format file?") from deadlocking the subprocess; the child either
    proceeds with defaults or errors out, but never blocks waiting on tty.

    `timeout` defaults to the configured `kicad_cli_timeout` when unset.
    """
    from kcd.core import config as cfg_mod
    cmd = [cli, *args]
    effective_timeout = timeout if timeout is not None else cfg_mod.load().kicad_cli_timeout
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=effective_timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise CliError(
            cmd,
            -1,
            (e.stdout.decode() if isinstance(e.stdout, bytes) else e.stdout) or "",
            (e.stderr.decode() if isinstance(e.stderr, bytes) else e.stderr)
            or f"kicad-cli timed out after {effective_timeout}s",
        ) from e
    if proc.returncode != 0:
        raise CliError(cmd, proc.returncode, proc.stdout, proc.stderr)
    return CliResult(stdout=proc.stdout, stderr=proc.stderr)


def version(cli: str) -> str:
    """Return KiCad CLI version string."""
    return _run(cli, "--version").stdout.strip()


# ---------------------------------------------------------------------------
# Schematic rendering / export
# ---------------------------------------------------------------------------

def export_sch_svg(cli: str, sch: Path, out_dir: Path) -> Path:
    """Export schematic to SVG; returns the directory where files were written."""
    out_dir.mkdir(parents=True, exist_ok=True)
    _run(cli, "sch", "export", "svg", "--output", str(out_dir), str(sch))
    return out_dir


def export_sch_pdf(cli: str, sch: Path, out: Path) -> Path:
    """Export schematic to a single PDF."""
    out.parent.mkdir(parents=True, exist_ok=True)
    _run(cli, "sch", "export", "pdf", "--output", str(out), str(sch))
    return out


def _rasterize_svg(svg: Path, out: Path, dpi: int) -> None:
    """Rasterize an SVG to PNG via the bundled `resvg_py` (Rust resvg).

    kicad-cli has no direct PNG export for schematics or flat 2D boards, so
    PNG output goes via SVG. `resvg_py` ships a self-contained wheel — no
    external rasterizer app (rsvg-convert / inkscape) is required. Raises
    `CliError` if resvg cannot rasterize the SVG.
    """
    import resvg_py

    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        png = resvg_py.svg_to_bytes(svg_path=str(svg), dpi=dpi)
    except Exception as e:
        raise CliError(
            ["png-rasterize"], 1, "",
            f"resvg could not rasterize {svg.name} to PNG: {e}",
        ) from e
    out.write_bytes(bytes(png))


def export_sch_png(cli: str, sch: Path, out: Path, dpi: int = 300) -> Path:
    """Export schematic to PNG.

    kicad-cli doesn't have a direct PNG export for schematics, so we go via SVG
    then rasterize. For agentic use cases, SVG is preferred (it's a real vector
    representation Claude can inspect), but PNG is needed when Claude is reading
    via its vision capability.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    svg_dir = out.parent / f".{out.stem}-svg"
    export_sch_svg(cli, sch, svg_dir)
    # Find the SVG that matches our sheet (root sheet uses project name)
    svgs = sorted(svg_dir.glob("*.svg"))
    if not svgs:
        raise CliError(["sch", "export", "svg"], 1, "", "no SVG produced")
    _rasterize_svg(svgs[0], out, dpi)
    return out


def export_sch_bom(cli: str, sch: Path, out: Path, grouped: bool = True) -> Path:
    """Export BOM (CSV)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    args = ["sch", "export", "bom", "--output", str(out)]
    if grouped:
        # kicad-cli 10 groups by --group-by; refdes is a sensible default
        args.extend(["--group-by", "Value,Footprint"])
    args.append(str(sch))
    _run(cli, *args)
    return out


def export_sch_netlist(cli: str, sch: Path, out: Path, fmt: str = "kicadxml") -> Path:
    """Export the schematic netlist; returns the written file path.

    `fmt` is a `kicad-cli sch export netlist --format` value. We default to
    `kicadxml` because it's the structured form kcd parses for drift
    detection; `kicadsexpr` is KiCad's native form for the legacy pcbnew
    netlist-import path.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    _run(cli, "sch", "export", "netlist", "--format", fmt, "--output", str(out), str(sch))
    return out


# ---------------------------------------------------------------------------
# PCB rendering / export
# ---------------------------------------------------------------------------

def export_pcb_svg(
    cli: str, pcb: Path, out: Path,
    layers: list[str] | None = None, mirror: bool = False,
) -> Path:
    """Export PCB layers to SVG, cropped to the board.

    `--page-size-mode 2` (board area only) + `--exclude-drawing-sheet` drop
    the A4 worksheet frame, so the board fills the SVG instead of occupying a
    small fraction of an empty sheet — a render an agent can actually read.
    `mirror` flips the plot (so a bottom-side view reads correctly).
    Render-only; `export pdf --target pcb` keeps the framed sheet.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    args = [
        "pcb", "export", "svg", "--output", str(out),
        "--page-size-mode", "2", "--exclude-drawing-sheet",
    ]
    if mirror:
        args.append("--mirror")
    if layers:
        args.extend(["--layers", ",".join(layers)])
    args.append(str(pcb))
    _run(cli, *args)
    return out


def export_pcb_png(
    cli: str, pcb: Path, out: Path,
    layers: list[str] | None = None, dpi: int = 300,
) -> Path:
    """Export PCB layers to a flat 2D PNG — exports SVG, then rasterizes.

    kicad-cli has no direct flat-2D PNG export for boards (`pcb render` is the
    photorealistic 3D view, which hides copper under soldermask). For an agent
    that needs to *see* the copper/silk layers, this rasterizes the layered SVG.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    svg = out.parent / f".{out.stem}.svg"
    export_pcb_svg(cli, pcb, svg, layers=layers)
    _rasterize_svg(svg, out, dpi)
    return out


def render_pcb_png(
    cli: str,
    pcb: Path,
    out: Path,
    side: str = "top",
    background: str = "default",
    quality: str = "high",
) -> Path:
    """Render a photorealistic PCB image using `kicad-cli pcb render`.

    side: "top" | "bottom" | "left" | "right" | "front" | "back"
    quality: "basic" | "high" | "user"
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    args = [
        "pcb", "render",
        "--output", str(out),
        "--side", side,
        "--background", background,
        "--quality", quality,
        str(pcb),
    ]
    _run(cli, *args)
    return out


def export_pcb_pdf(cli: str, pcb: Path, out: Path, layers: list[str] | None = None) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    args = ["pcb", "export", "pdf", "--output", str(out)]
    if layers:
        args.extend(["--layers", ",".join(layers)])
    args.append(str(pcb))
    _run(cli, *args)
    return out


# ---------------------------------------------------------------------------
# Manufacturing exports
# ---------------------------------------------------------------------------

def export_gerber(cli: str, pcb: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    _run(cli, "pcb", "export", "gerbers", "--output", str(out_dir), str(pcb))
    return out_dir


def export_drill(cli: str, pcb: Path, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    _run(cli, "pcb", "export", "drill", "--output", str(out_dir) + "/", str(pcb))
    return out_dir


def export_step(cli: str, pcb: Path, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    _run(cli, "pcb", "export", "step", "--output", str(out), str(pcb))
    return out


def export_pos(cli: str, pcb: Path, out: Path) -> Path:
    """Export pick-and-place position file."""
    out.parent.mkdir(parents=True, exist_ok=True)
    _run(cli, "pcb", "export", "pos", "--output", str(out), str(pcb))
    return out


# ---------------------------------------------------------------------------
# DRC / ERC
# ---------------------------------------------------------------------------

def run_drc(cli: str, pcb: Path, report: Path) -> dict:
    """Run DRC and return parsed JSON report."""
    report.parent.mkdir(parents=True, exist_ok=True)
    _run(
        cli, "pcb", "drc",
        "--output", str(report),
        "--format", "json",
        "--severity-all",
        str(pcb),
    )
    return json.loads(report.read_text())


def run_erc(cli: str, sch: Path, report: Path) -> dict:
    """Run ERC and return parsed JSON report."""
    report.parent.mkdir(parents=True, exist_ok=True)
    _run(
        cli, "sch", "erc",
        "--output", str(report),
        "--format", "json",
        "--severity-all",
        str(sch),
    )
    return json.loads(report.read_text())
