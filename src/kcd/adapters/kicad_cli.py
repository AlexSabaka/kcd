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


def _run(cli: str, *args: str) -> CliResult:
    cmd = [cli, *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
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
    # Convert with rsvg-convert if available; else fall back to a warning.
    try:
        subprocess.run(
            ["rsvg-convert", "-d", str(dpi), "-p", str(dpi), "-o", str(out), str(svgs[0])],
            check=True, capture_output=True, text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        # Last-ditch: try inkscape
        try:
            subprocess.run(
                ["inkscape", "--export-type=png", f"--export-dpi={dpi}",
                 f"--export-filename={out}", str(svgs[0])],
                check=True, capture_output=True, text=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError) as e:
            raise CliError(
                ["png-rasterize"], 1, "",
                "Neither rsvg-convert nor inkscape found on PATH for PNG rasterization. "
                "Install one, or use --format svg/pdf."
            ) from e
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


# ---------------------------------------------------------------------------
# PCB rendering / export
# ---------------------------------------------------------------------------

def export_pcb_svg(cli: str, pcb: Path, out: Path, layers: list[str] | None = None) -> Path:
    """Export PCB layers to SVG."""
    out.parent.mkdir(parents=True, exist_ok=True)
    args = ["pcb", "export", "svg", "--output", str(out)]
    if layers:
        args.extend(["--layers", ",".join(layers)])
    args.append(str(pcb))
    _run(cli, *args)
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
