"""Unit tests for the kicad-cli subprocess adapter — no real kicad-cli needed."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from kcd.adapters import kicad_cli
from kcd.adapters.kipy_pcb import _layer_name


def test_run_propagates_timeout_as_cli_error(monkeypatch) -> None:
    """TimeoutExpired must surface as CliError with returncode=-1 and a marker stderr."""

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout", 60))

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(kicad_cli.CliError) as exc_info:
        kicad_cli._run("kicad-cli", "--version", timeout=1)

    err = exc_info.value
    assert err.returncode == -1
    assert "timed out" in err.stderr
    assert "1s" in err.stderr  # the timeout value


def test_run_passes_stdin_devnull(monkeypatch) -> None:
    """kicad-cli must never inherit the parent's stdin — interactive prompts would hang."""
    captured: dict = {}

    class _FakeProc:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return _FakeProc()

    monkeypatch.setattr(subprocess, "run", fake_run)
    kicad_cli._run("kicad-cli", "--version")

    assert captured.get("stdin") is subprocess.DEVNULL


def test_layer_name_maps_kipy_ints_to_canonical_names() -> None:
    """kipy 0.7.1 returns layer values as the proto BoardLayer enum (int-ish).
    Agents need them as `F.Cu` / `B.Cu`, not `"3"` / `"34"`."""
    assert _layer_name(3) == "F.Cu"
    assert _layer_name(34) == "B.Cu"
    assert _layer_name(39) == "B.SilkS"


def test_layer_name_falls_back_on_unknown() -> None:
    """Unrecognized ints must not crash — fall back to str()."""
    assert _layer_name(999_999) == "999999"
    assert _layer_name("garbage") == "garbage"


# ---------------------------------------------------------------------------
# _rasterize_svg — bundled resvg_py, no external app (Round-4 field report B3-B)
# ---------------------------------------------------------------------------

def test_rasterize_svg_produces_a_png(tmp_path: Path) -> None:
    """The bundled resvg engine turns an SVG into a real PNG with no
    rsvg-convert / inkscape on PATH."""
    svg = tmp_path / "in.svg"
    svg.write_text(
        '<svg width="40" height="20" xmlns="http://www.w3.org/2000/svg">'
        '<rect width="40" height="20" fill="red"/></svg>'
    )
    out = tmp_path / "out.png"
    kicad_cli._rasterize_svg(svg, out, dpi=150)
    assert out.is_file()
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_rasterize_svg_raises_cli_error_on_bad_svg(tmp_path: Path) -> None:
    """A malformed SVG surfaces as CliError — the type the render commands
    catch to degrade gracefully to SVG output."""
    svg = tmp_path / "bad.svg"
    svg.write_text("this is not svg at all {{{")
    with pytest.raises(kicad_cli.CliError):
        kicad_cli._rasterize_svg(svg, tmp_path / "out.png", dpi=150)


# ---------------------------------------------------------------------------
# export_pcb_svg — crops to the board, no A4 worksheet frame (R5-1)
# ---------------------------------------------------------------------------

def test_export_pcb_svg_crops_to_board(tmp_path: Path, monkeypatch) -> None:
    """PCB SVG export must drop the A4 worksheet frame so the board fills the
    render — `--page-size-mode 2` + `--exclude-drawing-sheet`."""
    captured: list = []
    monkeypatch.setattr(kicad_cli, "_run", lambda *a, **k: captured.extend(a))
    kicad_cli.export_pcb_svg(
        "kicad-cli", tmp_path / "b.kicad_pcb", tmp_path / "b.svg"
    )
    assert "--exclude-drawing-sheet" in captured
    assert "--page-size-mode" in captured
    assert captured[captured.index("--page-size-mode") + 1] == "2"
