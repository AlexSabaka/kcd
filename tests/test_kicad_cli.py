"""Unit tests for the kicad-cli subprocess adapter — no real kicad-cli needed."""

from __future__ import annotations

import subprocess

import pytest

from kcd.adapters import kicad_cli


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
