"""`kcd render` subcommands."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import typer

from kcd.adapters import kicad_cli
from kcd.core import config as cfg_mod
from kcd.core.output import CommandError, run_command
from kcd.core.project import resolve

render_app = typer.Typer(help="Render schematics and PCBs so the agent can SEE them.")


@render_app.command("sch")
def sch(
    project: str = typer.Argument(...),
    out: Path = typer.Option(..., "-o", "--out", help="Output path (file or dir)"),
    format_: str = typer.Option("svg", "-f", "--format", help="svg | pdf | png"),
    dpi: int = typer.Option(300, "--dpi", help="DPI for PNG rasterization"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Render the schematic. Output goes to a directory for SVG (one file per sheet),
    or a single file for PDF/PNG."""
    with run_command("render.sch", json_) as r:
        cfg = cfg_mod.load()
        proj = resolve(project)
        fmt = format_.lower()
        if fmt == "svg":
            out_dir = out if out.is_dir() or not out.suffix else out.parent
            kicad_cli.export_sch_svg(cfg.kicad_cli, proj.sch, out_dir)
            for svg in sorted(out_dir.glob("*.svg")):
                r.add_artifact("schematic_svg", str(svg))
        elif fmt == "pdf":
            kicad_cli.export_sch_pdf(cfg.kicad_cli, proj.sch, out)
            r.add_artifact("schematic_pdf", str(out))
        elif fmt == "png":
            try:
                kicad_cli.export_sch_png(cfg.kicad_cli, proj.sch, out, dpi=dpi)
                r.add_artifact("schematic_png", str(out), dpi=dpi)
            except kicad_cli.CliError:
                fmt = "svg"
                kicad_cli.export_sch_svg(cfg.kicad_cli, proj.sch, out.parent)
                for svg in sorted(out.parent.glob("*.svg")):
                    r.add_artifact("schematic_svg", str(svg))
                r.warn(
                    "PNG rasterization failed; emitted SVG instead — the SVG "
                    "renders fine, only the inline PNG preview is unavailable."
                )
        else:
            raise CommandError("invalid_format", f"Unknown format {format_!r}; use svg, pdf, or png")
        r.data = {"project": proj.name, "format": fmt}


# --- region cropping for `render pcb` (Round-5 field report R5-1/R5-2) -------
# A full-board PCB render is too coarse for fine placement work. `--region-*`
# crops the SVG to a sub-area: the board-area SVG (kicad-cli page-size-mode 2)
# spans the board outline bbox, so a mm window is the same fraction of the
# viewBox as it is of the board.

_VIEWBOX_RE = re.compile(r'viewBox\s*=\s*"([^"]+)"')
_REGION_DPI_CAP = 2400


def _resolve_region(
    region_ref: str | None,
    region_bbox: str | None,
    region_window: float,
) -> tuple[float, float, float, float] | None:
    """Resolve the region options to an absolute-mm bbox, or None.

    `--region-bbox` is explicit corners; `--region-ref` centres a
    `--region-window` mm square on a footprint (resolved over live IPC).
    """
    if region_ref and region_bbox:
        raise CommandError(
            "bad_region", "Use either --region-ref or --region-bbox, not both."
        )
    if region_bbox:
        parts = region_bbox.split(",")
        if len(parts) != 4:
            raise CommandError(
                "bad_region",
                f"--region-bbox needs 'x1,y1,x2,y2' in mm, got {region_bbox!r}.",
            )
        try:
            x1, y1, x2, y2 = (float(p) for p in parts)
        except ValueError:
            raise CommandError(
                "bad_region",
                f"--region-bbox needs numeric mm values, got {region_bbox!r}.",
            ) from None
        return (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
    if region_ref:
        from kcd.adapters import kipy_pcb
        fp = kipy_pcb.find_footprint(region_ref)
        cx, cy = fp["x_mm"], fp["y_mm"]
        half = region_window / 2.0
        return (cx - half, cy - half, cx + half, cy + half)
    return None


def _region_viewbox(
    region: tuple[float, float, float, float],
    board_bbox: dict[str, float],
    viewbox: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """Map an absolute-mm region onto an SVG viewBox sub-rectangle.

    Fractions are clamped to the board, so a window that runs off the edge
    still yields a valid box.
    """
    rx1, ry1, rx2, ry2 = region
    bx, by = board_bbox["min_x"], board_bbox["min_y"]
    bw, bh = board_bbox["width"], board_bbox["height"]
    vx, vy, vw, vh = viewbox
    if bw <= 0 or bh <= 0:
        raise ValueError("board bounding box has zero area")

    def _clamp(v: float) -> float:
        return max(0.0, min(1.0, v))

    fx0, fx1 = _clamp((rx1 - bx) / bw), _clamp((rx2 - bx) / bw)
    fy0, fy1 = _clamp((ry1 - by) / bh), _clamp((ry2 - by) / bh)
    if fx1 <= fx0 or fy1 <= fy0:
        raise ValueError("region does not overlap the board area")
    return (vx + fx0 * vw, vy + fy0 * vh,
            (fx1 - fx0) * vw, (fy1 - fy0) * vh)


def _scale_svg_dim(text: str, attr: str, factor: float) -> str:
    """Scale a numeric SVG root dimension (`width` / `height`) by `factor`."""
    m = re.search(rf'\b{attr}\s*=\s*"([0-9.]+)([a-zA-Z%]*)"', text)
    if not m:
        return text
    val = float(m.group(1)) * factor
    return f'{text[:m.start()]}{attr}="{val:.6f}{m.group(2)}"{text[m.end():]}'


def _crop_svg_region(
    svg: Path,
    region: tuple[float, float, float, float],
    board_bbox: dict[str, float],
) -> None:
    """Rewrite a PCB SVG in place so it shows only `region` (absolute mm)."""
    text = svg.read_text()
    m = _VIEWBOX_RE.search(text)
    if not m:
        raise CommandError(
            "no_viewbox", "PCB SVG has no viewBox — cannot crop to a region."
        )
    vx, vy, vw, vh = (float(n) for n in m.group(1).replace(",", " ").split())
    try:
        nx, ny, nw, nh = _region_viewbox(region, board_bbox, (vx, vy, vw, vh))
    except ValueError as e:
        raise CommandError("bad_region", str(e)) from e
    text = (f'{text[:m.start()]}viewBox="{nx:.6f} {ny:.6f} {nw:.6f} {nh:.6f}"'
            f'{text[m.end():]}')
    text = _scale_svg_dim(text, "width", nw / vw)
    text = _scale_svg_dim(text, "height", nh / vh)
    svg.write_text(text)


def _region_dpi(dpi: int, region: tuple[float, float, float, float],
                board_bbox: dict[str, float]) -> int:
    """Raise the rasterization dpi so a cropped region keeps full-board detail.

    Zooming in should not cost pixels: scale dpi by board-width / region-width
    so the region renders at the pixel density a full-board view would.
    """
    region_w = region[2] - region[0]
    if region_w <= 0:
        return dpi
    return min(_REGION_DPI_CAP, round(dpi * board_bbox["width"] / region_w))


# --- side selection + layer transparency for `render pcb` (Round-6) ----------
# kicad-cli composites the SVG flat with no opacity control, so a board with a
# B.Cu ground pour renders as an opaque fill that hides everything underneath.
# `--side` picks a clean single-side layer set; `--side both` exports the two
# sides separately and stacks them with the back copper faded.

_SIDE_LAYERS = {
    "top": ["F.Cu", "F.SilkS", "Edge.Cuts"],
    "bottom": ["B.Cu", "B.SilkS", "Edge.Cuts"],
}
_SVG_OPEN_RE = re.compile(r"<svg\b[^>]*>", re.IGNORECASE)


def _svg_inner(svg_text: str) -> str:
    """The markup between an SVG's root `<svg ...>` and its closing `</svg>`."""
    m = _SVG_OPEN_RE.search(svg_text)
    end = svg_text.rfind("</svg>")
    if m is None or end < 0:
        raise CommandError("bad_svg", "kicad-cli SVG is missing its <svg> root.")
    return svg_text[m.end():end]


def _composite_layers(front: str, back: str, back_opacity: float) -> str:
    """Stack two board-area PCB SVGs into one — `back` faded under `front`.

    Both are `--page-size-mode 2` exports, so they share a viewBox and
    overlay exactly. The front SVG's root element is kept; the back SVG's
    content is inserted first inside a reduced-opacity `<g>`, so the back
    copper shows through the front's gaps without hiding the front.
    """
    m = _SVG_OPEN_RE.search(front)
    if m is None:
        raise CommandError("bad_svg", "kicad-cli SVG is missing its <svg> root.")
    return (
        f"{front[:m.end()]}\n"
        f'<g opacity="{back_opacity:.3f}">{_svg_inner(back)}</g>\n'
        f"<g>{_svg_inner(front)}</g>\n"
        "</svg>\n"
    )


def _export_board_svg(
    cli: str,
    pcb: Path,
    dest: Path,
    *,
    side: str,
    explicit_layers: list[str] | None,
    back_opacity: float,
) -> None:
    """Write a board SVG to `dest`, honoring `--side` / an explicit `--layers`.

    An explicit `--layers` wins outright. Otherwise `--side top|bottom`
    renders that side's layer set (mirroring the bottom so its text reads),
    and `--side both` composites the two sides with the back faded.
    """
    if explicit_layers is not None:
        kicad_cli.export_pcb_svg(cli, pcb, dest, layers=explicit_layers)
        return
    if side == "both":
        with tempfile.TemporaryDirectory(prefix="kcd-side-") as td:
            front_p = Path(td) / "front.svg"
            back_p = Path(td) / "back.svg"
            kicad_cli.export_pcb_svg(cli, pcb, front_p, layers=_SIDE_LAYERS["top"])
            kicad_cli.export_pcb_svg(
                cli, pcb, back_p, layers=_SIDE_LAYERS["bottom"]
            )
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(_composite_layers(
                front_p.read_text(), back_p.read_text(), back_opacity
            ))
        return
    kicad_cli.export_pcb_svg(
        cli, pcb, dest,
        layers=_SIDE_LAYERS[side], mirror=(side == "bottom"),
    )


@render_app.command("pcb")
def pcb(
    project: str = typer.Argument(...),
    out: Path = typer.Option(..., "-o", "--out"),
    format_: str = typer.Option("svg", "-f", "--format", help="svg | pdf | png"),
    side: str = typer.Option(
        "top", "--side",
        help="top | bottom | both — which side's layers to render; 'both' "
             "stacks them with the back faded. Ignored when --layers is set.",
    ),
    layers: str | None = typer.Option(
        None, "--layers",
        help="Comma-separated layer names — explicit override of --side.",
    ),
    back_opacity: float = typer.Option(
        0.35, "--back-opacity",
        help="Back-copper opacity for --side both (0..1, default 0.35).",
    ),
    dpi: int = typer.Option(300, "--dpi", help="DPI for PNG rasterization"),
    region_ref: str | None = typer.Option(
        None, "--region-ref",
        help="Crop to a window around this footprint ref (needs KiCad open).",
    ),
    region_bbox: str | None = typer.Option(
        None, "--region-bbox", help="Crop to 'x1,y1,x2,y2' in mm.",
    ),
    region_window: float = typer.Option(
        20.0, "--region-window",
        help="Square window side in mm for --region-ref (default 20). "
             "~20-24 mm is neighbourhood scale; use ~8-10 mm to see 0402 "
             "pads / 0.15 mm stubs.",
    ),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Render PCB layers to SVG, PDF, or PNG (flat 2D layer view).

    `--side` picks which copper side to show — kicad-cli composites layers
    flat with no opacity, so rendering both coppers lets a ground pour hide
    everything. Default `top`; `--side both` stacks the two sides with the
    back faded (`--back-opacity`). `--region-ref` / `--region-bbox` crop to a
    sub-area so fine placement is visible (svg/png only, needs KiCad open).
    """
    with run_command("render.pcb", json_) as r:
        cfg = cfg_mod.load()
        proj = resolve(project)
        fmt = format_.lower()
        side_l = side.lower()
        if side_l not in ("top", "bottom", "both"):
            raise CommandError(
                "bad_side", f"--side must be top, bottom, or both; got {side!r}."
            )
        explicit_layers = (
            [s.strip() for s in layers.split(",") if s.strip()] if layers else None
        )
        composite = side_l == "both" and explicit_layers is None
        if composite and not 0.0 <= back_opacity <= 1.0:
            raise CommandError(
                "bad_opacity", "--back-opacity must be between 0 and 1."
            )
        if explicit_layers is not None:
            reported_layers = explicit_layers
        elif composite:
            reported_layers = _SIDE_LAYERS["top"] + _SIDE_LAYERS["bottom"]
        else:
            reported_layers = _SIDE_LAYERS[side_l]

        region = _resolve_region(region_ref, region_bbox, region_window)
        board_b: dict[str, float] | None = None
        if region is not None:
            if fmt == "pdf":
                raise CommandError(
                    "bad_region", "--region-* applies to svg/png, not pdf."
                )
            from kcd.adapters import kipy_pcb
            board_b = kipy_pcb.board_bbox()

        if fmt == "svg":
            _export_board_svg(
                cfg.kicad_cli, proj.pcb, out,
                side=side_l, explicit_layers=explicit_layers,
                back_opacity=back_opacity,
            )
            if region is not None and board_b is not None:
                _crop_svg_region(out, region, board_b)
            r.add_artifact("pcb_svg", str(out), layers=reported_layers)
        elif fmt == "pdf":
            if composite:
                raise CommandError(
                    "bad_side", "--side both applies to svg/png, not pdf."
                )
            pdf_layers = explicit_layers or _SIDE_LAYERS[side_l]
            kicad_cli.export_pcb_pdf(cfg.kicad_cli, proj.pcb, out, layers=pdf_layers)
            r.add_artifact("pcb_pdf", str(out), layers=pdf_layers)
        elif fmt == "png":
            try:
                svg_tmp = out.parent / f".{out.stem}.svg"
                _export_board_svg(
                    cfg.kicad_cli, proj.pcb, svg_tmp,
                    side=side_l, explicit_layers=explicit_layers,
                    back_opacity=back_opacity,
                )
                rdpi = dpi
                if region is not None and board_b is not None:
                    _crop_svg_region(svg_tmp, region, board_b)
                    rdpi = _region_dpi(dpi, region, board_b)
                kicad_cli._rasterize_svg(svg_tmp, out, rdpi)
                r.add_artifact("pcb_png", str(out), layers=reported_layers, dpi=rdpi)
            except kicad_cli.CliError:
                fmt = "svg"
                svg_out = out.with_suffix(".svg")
                _export_board_svg(
                    cfg.kicad_cli, proj.pcb, svg_out,
                    side=side_l, explicit_layers=explicit_layers,
                    back_opacity=back_opacity,
                )
                if region is not None and board_b is not None:
                    _crop_svg_region(svg_out, region, board_b)
                r.add_artifact("pcb_svg", str(svg_out), layers=reported_layers)
                r.warn(
                    "PNG rasterization failed; emitted SVG instead — the SVG "
                    "renders fine, only the inline PNG preview is unavailable."
                )
        else:
            raise CommandError(
                "invalid_format", f"Unknown format {format_!r}; use svg, pdf, or png"
            )
        r.data = {
            "project": proj.name, "format": fmt,
            "side": "custom" if explicit_layers is not None else side_l,
            "layers": reported_layers,
        }
        if region is not None:
            r.data["region_mm"] = [round(v, 3) for v in region]


@render_app.command("3d")
def three_d(
    project: str = typer.Argument(...),
    out: Path = typer.Option(..., "-o", "--out"),
    side: str = typer.Option("top", "--side", help="top | bottom | front | back | left | right"),
    quality: str = typer.Option("high", "--quality", help="basic | high | user"),
    background: str = typer.Option("default", "--background"),
    json_: bool = typer.Option(False, "--json"),
) -> None:
    """Render a photorealistic 3D image of the PCB."""
    with run_command("render.3d", json_) as r:
        cfg = cfg_mod.load()
        proj = resolve(project)
        kicad_cli.render_pcb_png(
            cfg.kicad_cli, proj.pcb, out, side=side, background=background, quality=quality
        )
        r.add_artifact("pcb_render", str(out), side=side, quality=quality)
        r.data = {"project": proj.name, "side": side}
