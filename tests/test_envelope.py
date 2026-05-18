"""Tests for the `run_command` envelope wrapper.

These verify the exception ladder maps known exception types to stable error
codes, and that unknown exceptions surface as `code="unexpected"` rather than
escaping as a Python traceback.
"""

from __future__ import annotations

import json

import pytest

from kcd.core.output import CommandError, run_command


def _envelope(capsys) -> dict:
    """Read the JSON envelope just emitted to stdout."""
    captured = capsys.readouterr()
    return json.loads(captured.out)


def test_happy_path_emits_ok_envelope(capsys) -> None:
    """No exception → ok=True, no SystemExit, data preserved."""
    with run_command("test.cmd", json_mode=True) as r:
        r.data = {"hello": "world"}
        r.add_artifact("file", "/tmp/x")

    env = _envelope(capsys)
    assert env["ok"] is True
    assert env["command"] == "test.cmd"
    assert env["data"] == {"hello": "world"}
    assert env["artifacts"][0] == {"kind": "file", "path": "/tmp/x"}
    assert env["error"] is None


def test_command_error_maps_to_explicit_code(capsys) -> None:
    """CommandError carries its own code/message verbatim."""
    with pytest.raises(SystemExit) as exc_info:
        with run_command("test.cmd", json_mode=True):
            raise CommandError("invalid_input", "missing field bar")

    assert exc_info.value.code == 1
    env = _envelope(capsys)
    assert env["ok"] is False
    assert env["error"]["code"] == "invalid_input"
    assert env["error"]["message"] == "missing field bar"


def test_file_not_found_maps_to_not_found(capsys) -> None:
    """FileNotFoundError (e.g. from resolve()) becomes a clean envelope."""
    with pytest.raises(SystemExit):
        with run_command("test.cmd", json_mode=True):
            raise FileNotFoundError("/no/such/project")

    env = _envelope(capsys)
    assert env["ok"] is False
    assert env["error"]["code"] == "not_found"
    assert "/no/such/project" in env["error"]["message"]


def test_unknown_exception_maps_to_unexpected(capsys) -> None:
    """Any unrecognized exception lands as `unexpected` with the type name preserved."""
    with pytest.raises(SystemExit):
        with run_command("test.cmd", json_mode=True):
            raise RuntimeError("kicad-skip blew up internally")

    env = _envelope(capsys)
    assert env["ok"] is False
    assert env["error"]["code"] == "unexpected"
    assert "RuntimeError" in env["error"]["message"]
    assert "kicad-skip blew up internally" in env["error"]["message"]
