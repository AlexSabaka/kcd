"""`kcd analyze` — knowledge-layer analysis of KiCad projects.

Three read-only subcommands wrap the vendored kicad-happy analyzers
(`src/kcd/analyzers/analyze_{schematic,pcb,gerbers}.py`) in the
standard kcd JSON envelope:

  kcd analyze sch     <project>   → analyze_schematic.py
  kcd analyze pcb     <project>   → analyze_pcb.py
  kcd analyze gerbers <directory> → analyze_gerbers.py

Each subcommand:
  - subprocess-invokes the analyzer with a hard timeout
  - lifts findings with severity >= warning into envelope ``warnings[]``
    (so agents that don't unpack ``data`` still see the headline issues)
  - dumps the raw analyzer JSON to ``$KCD_RENDER_CACHE`` as a
    structured artifact for cheap re-reads

No auto-snapshot — analysis is read-only.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from kcd.adapters import analyzers
from kcd.core import config as cfg_mod
from kcd.core.output import CommandError, Result, run_command
from kcd.core.project import resolve

analyze_app = typer.Typer(
    help="Knowledge-layer analysis of KiCad projects "
         "(structure, BOM, power, manufacturability) via vendored kicad-happy.",
    no_args_is_help=True,
)


# Findings with these severities surface as envelope warnings. Anything below
# (info, debug, advisory) stays inside `data.findings` for callers that want
# the full picture but doesn't spam the envelope.
_WARNING_SEVERITIES = frozenset({"warning", "error", "critical"})


def _lift_findings(data: dict, r: Result) -> None:
    """Mirror high-severity analyzer findings into envelope ``warnings[]``.

    Each finding in the analyzer's ``findings`` array carries a ``severity``,
    a ``rule_id`` (e.g. ``"RS-001"``), and the human-readable text in
    ``detail`` (falling back to ``summary`` / ``description`` for older
    detectors). We tag the lifted warning with ``[severity][rule_id]`` so
    agents can grep without unpacking ``data.findings``.
    """
    findings = data.get("findings")
    if not isinstance(findings, list):
        return
    for f in findings:
        if not isinstance(f, dict):
            continue
        sev = (f.get("severity") or "").lower()
        if sev not in _WARNING_SEVERITIES:
            continue
        msg = (
            f.get("detail")
            or f.get("summary")
            or f.get("description")
            or f.get("message")
            or "(no message)"
        )
        rule = f.get("rule_id") or f.get("detector") or ""
        prefix = f"[{sev}]" + (f"[{rule}]" if rule else "")
        r.warn(f"{prefix} {msg}")


def _save_artifact(
    data: dict,
    out: Path | None,
    default_name: str,
    kind: str,
    r: Result,
) -> None:
    """Persist the raw analyzer JSON and register it as an envelope artifact."""
    cfg = cfg_mod.load()
    out_path = Path(out) if out else cfg.render_cache_dir / default_name
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, indent=2))
    r.add_artifact(kind, str(out_path))


@analyze_app.command("sch")
def analyze_sch_cmd(
    project: str = typer.Argument(
        ..., help="Path to .kicad_pro, project directory, or project name."
    ),
    out: str | None = typer.Option(
        None, "--out",
        help="Write raw analyzer JSON here (default: $KCD_RENDER_CACHE/<name>-analyze-sch.json).",
    ),
    json_: bool = typer.Option(False, "--json", help="Emit JSON envelope on stdout."),
) -> None:
    """Analyze the schematic side of a KiCad project.

    Returns the analyzer JSON: components, BOM, nets, rail_voltages,
    voltage_dividers, RC filters, regulators, decoupling adequacy, signal
    analysis, validation findings, and more. Findings with severity >=
    warning surface in envelope ``warnings[]``. Raw JSON saved as artifact.
    """
    with run_command("analyze.sch", json_) as r:
        proj = resolve(project)
        data = analyzers.run_analyzer("analyze_schematic.py", proj.sch)
        _lift_findings(data, r)
        _save_artifact(
            data, Path(out) if out else None,
            f"{proj.name}-analyze-sch.json",
            "analyze_schematic_json", r,
        )
        r.data = data


@analyze_app.command("pcb")
def analyze_pcb_cmd(
    project: str = typer.Argument(...),
    out: str | None = typer.Option(None, "--out"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Analyze the PCB side of a KiCad project.

    Returns the analyzer JSON: footprints, layers, nets, tracks, vias,
    decoupling placement/proximity, ground domains, layer transitions,
    DFM summary, findings. Read-only — does NOT need KiCad open.
    """
    with run_command("analyze.pcb", json_) as r:
        proj = resolve(project)
        data = analyzers.run_analyzer("analyze_pcb.py", proj.pcb)
        _lift_findings(data, r)
        _save_artifact(
            data, Path(out) if out else None,
            f"{proj.name}-analyze-pcb.json",
            "analyze_pcb_json", r,
        )
        r.data = data


@analyze_app.command("gerbers")
def analyze_gerbers_cmd(
    directory: str = typer.Argument(
        ..., help="Directory containing gerber + drill files."
    ),
    out: str | None = typer.Option(None, "--out"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Analyze a directory of gerber + drill files for manufacturability.

    Use after `kcd export gerber` (or a manual export) produces a gerber
    directory. The analyzer pulls layer integrity, drill geometry, min
    trace/space, and fab-compliance signals from the raw files — the things
    a fab house would check before quoting.
    """
    with run_command("analyze.gerbers", json_) as r:
        gerber_dir = Path(directory).expanduser().resolve()
        if not gerber_dir.is_dir():
            raise CommandError("not_found", f"Not a directory: {gerber_dir}")
        data = analyzers.run_analyzer("analyze_gerbers.py", gerber_dir)
        _lift_findings(data, r)
        _save_artifact(
            data, Path(out) if out else None,
            f"{gerber_dir.name}-analyze-gerbers.json",
            "analyze_gerbers_json", r,
        )
        r.data = data
