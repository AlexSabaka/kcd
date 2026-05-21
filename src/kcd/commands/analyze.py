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
  - folds the report for the inline envelope (``_compact``): the full
    analyzer JSON overruns the 1MB MCP result cap on real boards, so
    ``data`` carries the headline + folded findings and the bulk sections
    spill to the artifact

No auto-snapshot — analysis is read-only.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import typer

from kcd.adapters import analyzers, kicad_cli
from kcd.core import config as cfg_mod
from kcd.core.output import CommandError, Result, run_command
from kcd.core.project import Project, resolve

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


# --- inline-envelope folding -------------------------------------------------
# The vendored analyzers emit large JSON (full BOM, every net, every track,
# dependency graphs) — a 58-component board overruns the 1MB MCP result cap.
# `_compact` keeps the headline (summary, trust_summary), folds `findings` by
# (rule_id, severity), and spills bulk sections. The artifact always holds the
# complete analyzer JSON, so nothing is lost — only re-shaped for the envelope.

_FOLD_SAMPLE = 3          # findings/list entries kept per group before spilling
_VALUE_BUDGET = 8_000     # max JSON chars for one inline section before it spills
_TOTAL_BUDGET = 40_000    # max JSON chars for the whole compacted `data`
_SAMPLE_BUDGET = 2_000    # a spilled list keeps a sample only if it fits this

# Sections that are bulky by nature — net maps, layer stackup, silkscreen,
# per-domain copper lists. Always spilled to the artifact regardless of size:
# even a "small" 80-entry net map is noise an agent rarely needs inline
# (Round-6 field report — `analyze pcb` was still the token hog).
_BULKY_SECTIONS = frozenset({
    "nets", "net_name_to_id", "layers", "silkscreen",
    "ground_domains", "copper_presence",
})

_SEVERITY_RANK = {
    "critical": 0, "error": 1, "warning": 2,
    "info": 3, "advisory": 4, "debug": 5,
}

_HEADLINE_KEYS = ("summary", "trust_summary", "verdict", "status", "metadata")


def _jsize(value: object) -> int:
    """JSON-serialized size of `value` in chars — a cheap budget proxy."""
    try:
        return len(json.dumps(value, default=str))
    except (TypeError, ValueError):
        return _VALUE_BUDGET + 1


def _fold_findings(findings: list) -> list[dict]:
    """Group findings by `(rule_id, severity)` — a true count plus a sample.

    Mirrors the `drc` fold: a uniform issue kind collapses to one row; the
    complete finding list stays in the artifact.
    """
    groups: dict[tuple[str, str], list] = {}
    for f in findings:
        if not isinstance(f, dict):
            continue
        rule = f.get("rule_id") or f.get("detector") or "?"
        sev = (f.get("severity") or "info").lower()
        groups.setdefault((rule, sev), []).append(f)
    out = [
        {
            "rule_id": rule, "severity": sev,
            "count": len(members), "sample": members[:_FOLD_SAMPLE],
        }
        for (rule, sev), members in groups.items()
    ]
    out.sort(key=lambda g: (_SEVERITY_RANK.get(g["severity"], 9), -g["count"]))
    return out


def _spill_stub(value: object) -> dict | None:
    """A `{count, sample}` placeholder for a section spilled to the artifact.

    Lists sample their first entries, dicts their first key/value pairs.
    Scalars have nothing useful to stub — return None so the key is named
    in `spilled.sections` but carries no inline value.
    """
    if isinstance(value, list):
        sample: object = value[:_FOLD_SAMPLE]
        stub: dict = {"count": len(value)}
    elif isinstance(value, dict):
        sample = dict(list(value.items())[:_FOLD_SAMPLE])
        stub = {"count": len(value)}
    else:
        return None
    if sample and _jsize(sample) <= _SAMPLE_BUDGET:
        stub["sample"] = sample
    return stub


def _compact(data: dict) -> dict:
    """Shrink an analyzer report for the inline envelope.

    `findings` is folded; `summary` / `trust_summary` ride verbatim; the
    remaining sections are kept smallest-first while under budget and the
    rest spill (named in `spilled.sections`), as do the always-bulky
    sections in `_BULKY_SECTIONS`. The complete report is always written to
    the artifact by `_save_artifact`.
    """
    if not isinstance(data, dict):
        return data
    out: dict = {}
    spilled: list[str] = []
    used = 0

    findings = data.get("findings")
    if isinstance(findings, list):
        out["findings"] = _fold_findings(findings)
        out["finding_total"] = len(findings)
        used += _jsize(out["findings"])

    for key in _HEADLINE_KEYS:
        if key in data and key not in out:
            out[key] = data[key]
            used += _jsize(data[key])

    rest = sorted(
        ((k, v) for k, v in data.items() if k != "findings" and k not in out),
        key=lambda kv: _jsize(kv[1]),
    )
    for key, value in rest:
        size = _jsize(value)
        bulky = key in _BULKY_SECTIONS
        if not bulky and size <= _VALUE_BUDGET and used + size <= _TOTAL_BUDGET:
            out[key] = value
            used += size
        else:
            spilled.append(key)
            stub = _spill_stub(value)
            if stub is not None:
                out[key] = stub

    if spilled:
        out["spilled"] = {
            "sections": sorted(spilled),
            "note": "large sections elided from the inline envelope; "
                    "the full analyzer JSON is in the artifact",
        }
    return out


def _dedup_net_maps(data: dict) -> None:
    """Drop `net_name_to_id` — the exact inverse of `nets` (id→name).

    `analyze_pcb` emits both directions of the same ~80-entry map; keeping
    only `nets` halves the net payload in the artifact and the envelope
    (Round-6 field report). The inverse is trivially reconstructable.
    """
    if "nets" in data and "net_name_to_id" in data:
        del data["net_name_to_id"]


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


# --- analyzer false-confidence guards ----------------------------------------
# The vendored analyzers report confident verdicts from partial or empty
# evaluation. These post-process the analyzer JSON in kcd's own layer (the
# engine itself is vendored and not modified here).

def _recount_gate(data: dict) -> None:
    """Recompute a fab-gate report's summary counts and overall status."""
    checks = data.get("checks", [])
    counts = {"pass": 0, "warn": 0, "fail": 0, "skip": 0}
    for c in checks:
        if isinstance(c, dict):
            st = c.get("status", "skip")
            counts[st] = counts.get(st, 0) + 1
    data["summary"] = {"total_checks": len(checks), **counts}
    if counts["fail"]:
        data["overall_status"] = "FAIL"
    elif counts["warn"]:
        data["overall_status"] = "WARN"
    elif counts["pass"]:
        data["overall_status"] = "PASS"
    else:
        data["overall_status"] = "INCOMPLETE"


def _drc_unconnected_count(proj: Project, r: Result, label: str) -> int | None:
    """Run DRC and return its unconnected-pad count, or None if DRC failed."""
    try:
        with tempfile.TemporaryDirectory(prefix="kcd-drc-") as td:
            raw = kicad_cli.run_drc(
                cfg_mod.load().kicad_cli, proj.pcb, Path(td) / "drc.json"
            )
    except Exception as e:
        r.warn(f"{label} could not cross-check routing against DRC: {e}")
        return None
    return len(raw.get("unconnected_items", []) or [])


def _reconcile_routing(data: dict, proj: Project, r: Result) -> None:
    """Cross-check fab-gate's routing verdict against DRC unconnected pads.

    The gate's routing check trusts net-level `routing_complete` and is blind
    to pad-level gaps — it can PASS while DRC finds unconnected pads. Run DRC
    and downgrade a falsely-passing routing check (Round-3 field report B5).
    """
    checks = data.get("checks")
    if not isinstance(checks, list):
        return
    routing = next(
        (c for c in checks
         if isinstance(c, dict) and c.get("check_id") == "routing_completeness"),
        None,
    )
    if routing is None or routing.get("status") != "pass":
        return
    unconnected = _drc_unconnected_count(proj, r, "fab-gate")
    if not unconnected:
        return
    routing["status"] = "fail"
    routing["message"] = (
        f"DRC finds {unconnected} unconnected pad(s) — the net-level routing "
        "check missed pad-level gaps"
    )
    details = routing.get("details") or {}
    details["drc_unconnected"] = unconnected
    routing["details"] = details
    _recount_gate(data)
    r.warn(
        f"fab-gate routing check downgraded to FAIL — DRC reports "
        f"{unconnected} unconnected pad(s) the gate's net-level check missed."
    )


def _reconcile_connectivity(data: dict, proj: Project, r: Result) -> None:
    """Cross-check analyze_pcb's connectivity block against DRC unconnected pads.

    `connectivity.routing_complete` is computed from net-level routing only —
    it can report True while DRC finds pad-level gaps. Mirror the fab-gate
    reconciliation on analyze_pcb's own verdict (Round-5 field report R5-3).
    """
    conn = data.get("connectivity")
    if not isinstance(conn, dict) or conn.get("routing_complete") is not True:
        return
    unconnected = _drc_unconnected_count(proj, r, "analyze pcb")
    if not unconnected:
        return
    conn["routing_complete"] = False
    conn["drc_unconnected"] = unconnected
    r.warn(
        f"analyze pcb connectivity downgraded — DRC reports {unconnected} "
        "unconnected pad(s) the net-level routing check missed; "
        "routing_complete is now false."
    )


def _flag_empty_thermal(data: dict, r: Result) -> None:
    """Downgrade a thermal score computed from zero assessed components.

    `compute_thermal_score` returns 100 when there are no findings — even
    when `components_assessed` is 0, i.e. nothing was actually evaluated. A
    confident 100 from an empty assessment is false-green (Round-3 B6).
    """
    summary = data.get("summary")
    if not isinstance(summary, dict):
        return
    if summary.get("components_assessed", 0) == 0:
        summary["thermal_score"] = None
        summary["thermal_score_status"] = "insufficient_data"
        r.warn(
            "thermal_score set to insufficient_data — 0 components were "
            "assessed (no load currents / MPNs to classify power parts); "
            "the design is unevaluated, not verified."
        )


def _flag_insufficient_cross(data: dict, r: Result) -> None:
    """Flag a cross-domain report that surfaced nothing as unevaluated.

    `cross_analysis` cross-checks (connector current vs trace, ESD gaps,
    decoupling) need load-current / datasheet inputs. Without them it runs
    no checks and returns 0 findings — which reads as a clean bill of health.
    Mark a zero-finding cross report `insufficient_data` (Round-5 R5-6).
    """
    summary = data.get("summary")
    if not isinstance(summary, dict):
        return
    if summary.get("total_findings", 0) == 0:
        summary["assessment_status"] = "insufficient_data"
        r.warn(
            "analyze cross assessment_status set to insufficient_data — 0 "
            "findings, but the cross-checks need load-current / datasheet "
            "inputs to run; this is unevaluated, not a clean bill of health."
        )


@contextmanager
def _sch_pcb_json(proj: Project) -> Iterator[tuple[Path, Path]]:
    """Run the schematic + PCB analyzers, yield their JSON as temp-file paths.

    The cross/thermal/fab-gate analyzers consume the *output* of the sch/pcb
    analyzers rather than raw KiCad files. This produces both into a
    throwaway temp dir, cleaned up on exit.
    """
    for label, p in (("Schematic", proj.sch), ("PCB", proj.pcb)):
        if not p.is_file():
            raise CommandError(
                "not_found",
                f"{label} file not found: {p} — this analysis needs both "
                "the .kicad_sch and the .kicad_pcb.",
            )
    with tempfile.TemporaryDirectory(prefix="kcd-analyze-") as td:
        tdp = Path(td)
        sch = tdp / "sch.json"
        sch.write_text(
            json.dumps(analyzers.run_analyzer("analyze_schematic.py", proj.sch))
        )
        pcb = tdp / "pcb.json"
        pcb.write_text(
            json.dumps(analyzers.run_analyzer("analyze_pcb.py", proj.pcb))
        )
        yield sch, pcb


@contextmanager
def _sch_json(proj: Project) -> Iterator[Path]:
    """Run the schematic analyzer, yield its JSON as a temp-file path."""
    if not proj.sch.is_file():
        raise CommandError("not_found", f"Schematic file not found: {proj.sch}")
    with tempfile.TemporaryDirectory(prefix="kcd-analyze-") as td:
        sch = Path(td) / "sch.json"
        sch.write_text(
            json.dumps(analyzers.run_analyzer("analyze_schematic.py", proj.sch))
        )
        yield sch


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
        r.data = _compact(data)


@analyze_app.command("pcb")
def analyze_pcb_cmd(
    project: str = typer.Argument(...),
    full: bool = typer.Option(
        False, "--full", help="Run the deeper (slower) PCB analysis pass."
    ),
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
        data = analyzers.run_analyzer(
            "analyze_pcb.py", proj.pcb, extra_args=["--full"] if full else None
        )
        _lift_findings(data, r)
        _reconcile_connectivity(data, proj, r)
        _dedup_net_maps(data)
        _save_artifact(
            data, Path(out) if out else None,
            f"{proj.name}-analyze-pcb.json",
            "analyze_pcb_json", r,
        )
        r.data = _compact(data)


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
        r.data = _compact(data)


@analyze_app.command("cross")
def analyze_cross_cmd(
    project: str = typer.Argument(...),
    out: str | None = typer.Option(None, "--out"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Cross-domain schematic-to-PCB analysis.

    Runs the schematic and PCB analyzers, then cross-checks the two —
    connector current, ESD gaps, decoupling adequacy, schematic/PCB
    consistency. Read-only; needs both .kicad_sch and .kicad_pcb present.
    """
    with run_command("analyze.cross", json_) as r:
        proj = resolve(project)
        with _sch_pcb_json(proj) as (sch, pcb):
            data = analyzers.run_analyzer_argv(
                "cross_analysis.py", ["-s", str(sch), "-p", str(pcb)]
            )
        _lift_findings(data, r)
        _flag_insufficient_cross(data, r)
        _save_artifact(
            data, Path(out) if out else None,
            f"{proj.name}-analyze-cross.json", "analyze_cross_json", r,
        )
        r.data = _compact(data)


@analyze_app.command("thermal")
def analyze_thermal_cmd(
    project: str = typer.Argument(...),
    ambient: float | None = typer.Option(
        None, "--ambient", help="Ambient temperature in degrees C."
    ),
    out: str | None = typer.Option(None, "--out"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Thermal analysis — junction temperatures and thermal-via adequacy.

    Runs the schematic and PCB analyzers, then estimates junction
    temperatures and checks thermal relief. Read-only.
    """
    with run_command("analyze.thermal", json_) as r:
        proj = resolve(project)
        extra = ["--ambient", str(ambient)] if ambient is not None else []
        with _sch_pcb_json(proj) as (sch, pcb):
            data = analyzers.run_analyzer_argv(
                "analyze_thermal.py", ["-s", str(sch), "-p", str(pcb), *extra]
            )
        _flag_empty_thermal(data, r)
        _lift_findings(data, r)
        _save_artifact(
            data, Path(out) if out else None,
            f"{proj.name}-analyze-thermal.json", "analyze_thermal_json", r,
        )
        r.data = _compact(data)


@analyze_app.command("fab-gate")
def analyze_fab_gate_cmd(
    project: str = typer.Argument(...),
    strict: bool = typer.Option(
        False, "--strict", help="Fail the gate on warnings, not just errors."
    ),
    out: str | None = typer.Option(None, "--out"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Ready-for-fab gate — structured pass/fail checks over the design.

    Runs the schematic and PCB analyzers, then a gate covering routing,
    BOM, DFM, and rule-check readiness. Read-only.
    """
    with run_command("analyze.fab-gate", json_) as r:
        proj = resolve(project)
        with _sch_pcb_json(proj) as (sch, pcb):
            argv = ["-s", str(sch), "-p", str(pcb)]
            if strict:
                argv.append("--strict")
            data = analyzers.run_analyzer_argv("fab_release_gate.py", argv)
        _reconcile_routing(data, proj, r)
        _lift_findings(data, r)
        _save_artifact(
            data, Path(out) if out else None,
            f"{proj.name}-analyze-fab-gate.json", "analyze_fab_gate_json", r,
        )
        r.data = _compact(data)


@analyze_app.command("whatif")
def analyze_whatif_cmd(
    project: str = typer.Argument(...),
    changes: list[str] | None = typer.Argument(
        None, help="Component-value changes, e.g. R1=10k C3=100n."
    ),
    suggest_fixes: bool = typer.Option(
        False, "--suggest-fixes", help="Suggest component-value fixes."
    ),
    out: str | None = typer.Option(None, "--out"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """What-if parameter sweep over the schematic.

    Runs the schematic analyzer, then re-evaluates affected subcircuits
    under the given component-value changes. Read-only.
    """
    with run_command("analyze.whatif", json_) as r:
        if not (changes or suggest_fixes):
            raise CommandError(
                "bad_args",
                "Pass at least one REF=VALUE change (e.g. R1=10k) or "
                "--suggest-fixes.",
            )
        proj = resolve(project)
        with _sch_json(proj) as sch:
            argv = [str(sch), *(changes or [])]
            if suggest_fixes:
                argv.append("--suggest-fixes")
            data = analyzers.run_analyzer_argv("what_if.py", argv)
        _lift_findings(data, r)
        _save_artifact(
            data, Path(out) if out else None,
            f"{proj.name}-analyze-whatif.json", "analyze_whatif_json", r,
        )
        r.data = _compact(data)


@analyze_app.command("lifecycle")
def analyze_lifecycle_cmd(
    project: str = typer.Argument(...),
    temp_range: str | None = typer.Option(
        None, "--temp-range",
        help="Design temp range: a preset (commercial/industrial/extended/"
             "automotive/military) or 'min,max'.",
    ),
    out: str | None = typer.Option(None, "--out"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Component lifecycle + temperature audit.

    Runs the schematic analyzer, then audits the BOM for obsolescence
    (EOL/NRND) and temperature-range fit. Queries distributor APIs — set
    DIGIKEY_CLIENT_ID / MOUSER_API_KEY / LCSC credentials in the
    environment; without them the audit degrades to offline checks only.
    """
    with run_command("analyze.lifecycle", json_) as r:
        proj = resolve(project)
        with _sch_json(proj) as sch:
            argv = [str(sch)]
            if temp_range:
                argv += ["--temp-range", temp_range]
            data = analyzers.run_analyzer_argv("lifecycle_audit.py", argv)
        _lift_findings(data, r)
        _save_artifact(
            data, Path(out) if out else None,
            f"{proj.name}-analyze-lifecycle.json", "analyze_lifecycle_json", r,
        )
        r.data = _compact(data)


# Analyzer types the vendored `diff_analysis.py` can diff (its `diff_funcs`
# dict). A JSON of any other type (gerber, cross_analysis, ...) crashes the
# vendored differ with a KeyError — guard before invoking it.
_DIFF_SUPPORTED = {"schematic", "pcb", "emc", "spice"}


def _diff_analyzer_type(p: Path, label: str) -> str | None:
    """Read the `analyzer_type` field from an analyzer JSON file."""
    try:
        return json.loads(p.read_text()).get("analyzer_type")
    except (OSError, ValueError) as e:
        raise CommandError(
            "bad_json", f"{label} is not readable analyzer JSON: {p} — {e}"
        ) from e


@analyze_app.command("diff")
def analyze_diff_cmd(
    base: str = typer.Argument(..., help="Base (old) analyzer JSON file."),
    head: str = typer.Argument(..., help="Head (new) analyzer JSON file."),
    out: str | None = typer.Option(None, "--out"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Diff two analyzer JSON runs — component, signal, and finding deltas.

    `base` and `head` are JSON files from earlier `kcd analyze` runs (saved
    as envelope artifacts). Read-only.
    """
    with run_command("analyze.diff", json_) as r:
        base_p = Path(base).expanduser()
        head_p = Path(head).expanduser()
        for label, p in (("base", base_p), ("head", head_p)):
            if not p.is_file():
                raise CommandError("not_found", f"{label} JSON not found: {p}")
        base_type = _diff_analyzer_type(base_p, "base")
        head_type = _diff_analyzer_type(head_p, "head")
        for label, t in (("base", base_type), ("head", head_type)):
            if t is not None and t not in _DIFF_SUPPORTED:
                raise CommandError(
                    "unsupported_diff",
                    f"analyze diff does not support {t!r} analyzer JSONs "
                    f"({label}); supported: "
                    f"{', '.join(sorted(_DIFF_SUPPORTED))}.",
                )
        if base_type and head_type and base_type != head_type:
            raise CommandError(
                "unsupported_diff",
                "analyze diff needs two JSONs of the same analyzer type — "
                f"got base={base_type!r}, head={head_type!r}.",
            )
        data = analyzers.run_analyzer_argv(
            "diff_analysis.py", [str(base_p), str(head_p)]
        )
        _lift_findings(data, r)
        _save_artifact(
            data, Path(out) if out else None,
            "analyze-diff.json", "analyze_diff_json", r,
        )
        r.data = _compact(data)
