"""`kcd drc` and `kcd erc` — design rule and electrical rule checking.

kicad-cli emits one JSON object per violation, repeating `type` / `severity`
/ structure — a real board (~200 violations) blows past 45K tokens. These
commands *fold* the report: violations are grouped by `(type, severity)`,
each group carries a true `count` and a small sample of `occurrences`. The
complete report is always written to the artifact path; `--full` inlines
every occurrence.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import typer

from kcd.adapters import kicad_cli
from kcd.core import config as cfg_mod
from kcd.core.output import Result, run_command
from kcd.core.project import resolve

# Occurrences shown per (type, severity) group in the inline envelope. Three
# examples are enough to recognise a uniform violation kind; the artifact
# carries every occurrence for a drill-in.
_SAMPLE = 3

# Sort order for violation groups — errors first, so a truncated skim still
# leads with what matters.
_SEVERITY_RANK = {"error": 0, "warning": 1, "exclusion": 2, "ignore": 3}


def _xy(pos: Any) -> Any:
    """kicad-cli's `pos` object `{x, y}` -> a compact `[x, y]` pair."""
    if isinstance(pos, dict):
        return [pos.get("x"), pos.get("y")]
    return pos


def _compact_item(item: dict, *, with_uuid: bool) -> dict:
    """One violation item -> `{desc, at}` (+ `uuid` only for the artifact)."""
    out: dict[str, Any] = {
        "desc": item.get("description", ""),
        "at": _xy(item.get("pos")),
    }
    if with_uuid and item.get("uuid"):
        out["uuid"] = item["uuid"]
    return out


def _compact_occurrence(v: dict, *, with_uuid: bool) -> dict:
    """One violation -> `{desc, items}`, items compacted."""
    return {
        "desc": v.get("description", ""),
        "items": [
            _compact_item(it, with_uuid=with_uuid) for it in v.get("items", [])
        ],
    }


def _severity_counts(violations: list[dict]) -> dict[str, int]:
    sev = Counter((v.get("severity") or "error") for v in violations)
    return {
        "errors": sev.get("error", 0),
        "warnings": sev.get("warning", 0),
        "exclusions": sev.get("exclusion", 0),
    }


def _fold(
    violations: list[dict], *, sample: int | None, with_uuid: bool
) -> list[dict]:
    """Group violations by `(type, severity)` into capped, sorted groups.

    `sample=None` keeps every occurrence (the `--full` / artifact form).
    """
    groups: dict[tuple[str, str], list[dict]] = {}
    for v in violations:
        key = (v.get("type", "unknown"), v.get("severity") or "error")
        groups.setdefault(key, []).append(v)

    out: list[dict] = []
    for (vtype, severity), members in groups.items():
        occ = [_compact_occurrence(v, with_uuid=with_uuid) for v in members]
        shown = occ if sample is None else occ[:sample]
        out.append({
            "type": vtype,
            "severity": severity,
            "count": len(members),
            "shown": len(shown),
            "occurrences": shown,
        })
    out.sort(key=lambda g: (_SEVERITY_RANK.get(g["severity"], 9), -g["count"]))
    return out


def _build_report(
    raw: dict, *, full: bool, kind: str
) -> tuple[dict, dict]:
    """Transform kicad-cli's raw report into `(inline_data, full_report)`.

    `kind` is `"drc"` or `"erc"`. Both returned dicts share the folded
    shape; `inline_data` caps each group at `_SAMPLE` (unless `full`),
    `full_report` keeps every occurrence and retains item uuids.
    """
    violations = raw.get("violations", []) or []
    if kind == "drc":
        unconnected = raw.get("unconnected_items", []) or []
        parity = raw.get("schematic_parity", []) or []
        combined = [*violations, *unconnected]
        summary = {
            **_severity_counts(combined),
            "unconnected": len(unconnected),
            "parity_issues": len(parity),
        }
    else:  # erc
        combined = violations
        parity = []
        summary = {
            **_severity_counts(combined),
            "sheet_count": len(raw.get("sheets", []) or []),
        }

    sample = None if full else _SAMPLE
    inline = {
        "summary": summary,
        "total": len(combined),
        "violations": _fold(combined, sample=sample, with_uuid=False),
    }
    full_report = {
        "summary": summary,
        "total": len(combined),
        "violations": _fold(combined, sample=None, with_uuid=True),
    }
    if parity:
        full_report["schematic_parity"] = parity
    return inline, full_report


def _warn(r: Result) -> None:
    """Emit a one-line headline; flag when the inline sample is folded."""
    total = r.data["total"]
    if not total:
        return
    parts = [f"{total} violations"]
    unconnected = r.data["summary"].get("unconnected")
    if unconnected:
        parts.append(f"{unconnected} unconnected")
    msg = ", ".join(parts)
    if any(g["shown"] < g["count"] for g in r.data["violations"]):
        msg += " — inline sample folded by type; full report in the artifact"
    r.warn(msg)


def drc_cmd(
    project: str = typer.Argument(...),
    report: Path = typer.Option(
        None, "-o", "--out", help="Path for the DRC report JSON (default: render cache)"
    ),
    full: bool = typer.Option(
        False, "--full", help="Inline every occurrence, not just a per-type sample"
    ),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Run DRC on the PCB and return a folded, token-efficient report.

    Violations are grouped by (type, severity); each group shows a sample of
    occurrences inline (all of them with --full). The artifact at the report
    path always holds the complete report, including item uuids.
    """
    with run_command("drc", json_) as r:
        cfg = cfg_mod.load()
        proj = resolve(project)
        report_path = report or cfg.render_cache_dir / f"{proj.name}-drc.json"
        raw = kicad_cli.run_drc(cfg.kicad_cli, proj.pcb, report_path)
        core, full_report = _build_report(raw, full=full, kind="drc")
        report_path.write_text(json.dumps(full_report, indent=2))
        r.data = {"project": proj.name, **core}
        r.add_artifact("drc_report", str(report_path))
        _warn(r)


def erc_cmd(
    project: str = typer.Argument(...),
    report: Path = typer.Option(None, "-o", "--out"),
    full: bool = typer.Option(
        False, "--full", help="Inline every occurrence, not just a per-type sample"
    ),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Run ERC on the schematic and return a folded, token-efficient report.

    Same folding as `drc` — violations grouped by (type, severity) with a
    per-group sample inline and the complete report in the artifact.
    """
    with run_command("erc", json_) as r:
        cfg = cfg_mod.load()
        proj = resolve(project)
        report_path = report or cfg.render_cache_dir / f"{proj.name}-erc.json"
        raw = kicad_cli.run_erc(cfg.kicad_cli, proj.sch, report_path)
        core, full_report = _build_report(raw, full=full, kind="erc")
        report_path.write_text(json.dumps(full_report, indent=2))
        r.data = {"project": proj.name, **core}
        r.add_artifact("erc_report", str(report_path))
        _warn(r)
