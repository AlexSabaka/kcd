"""End-to-end agentic-loop integration test (Dove session-3 suggestion).

Walks the full agent workflow against a live KiCad and asserts the round-trip
state matches expectations:

    project_current → snapshot → move-fp → re-inspect (verify edit)
                                       → restore  → re-inspect (verify revert)

The last step is what catches Dove session-3 #18 regressions: if
`snapshot.restore` doesn't sync KiCad's in-memory board state, the post-
restore `inspect_pcb` reads the *moved* position from KiCad's stale memory
instead of the restored disk file.

This test is skipped by default. To run it locally:

    1. Open a KiCad project in the PCB editor (any project will do).
    2. Set environment:
           KCD_INTEGRATION=1
           KCD_INTEGRATION_PROJECT=/path/to/the/project.kicad_pro
    3. Run: pytest tests/test_agentic_loop.py -v -s

If KiCad isn't reachable when the test runs, it skips with an informative
message rather than failing — IPC unavailability isn't a test failure, it's
a configuration condition.
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("KCD_INTEGRATION") != "1",
    reason="Set KCD_INTEGRATION=1 to enable (requires KiCad live + PCB open)",
)


def _kcd(*args: str) -> dict[str, Any]:
    """Invoke the kcd CLI in JSON mode and parse the envelope."""
    proc = subprocess.run(
        ["kcd", *args, "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if not proc.stdout.strip():
        raise RuntimeError(f"kcd produced no stdout. stderr: {proc.stderr}")
    return json.loads(proc.stdout)


def _require_kicad_open() -> str:
    """Return the project path from env, or skip if KiCad isn't reachable."""
    project = os.environ.get("KCD_INTEGRATION_PROJECT")
    if not project:
        pytest.skip(
            "Set KCD_INTEGRATION_PROJECT=/path/to/proj.kicad_pro to run"
        )

    pcb = _kcd("inspect", "pcb", project)
    if not pcb["ok"]:
        pytest.skip(
            f"KiCad not reachable for {project}: "
            f"{pcb.get('error', {}).get('message', 'unknown')}"
        )
    if not pcb["data"]["footprints"]:
        pytest.skip(f"No footprints found on {project} — pick a populated board")
    return project


def test_snapshot_restore_syncs_kicad_memory() -> None:
    """The Dove #18 regression catcher.

    Move a footprint, restore the pre-move snapshot, and verify that
    `inspect_pcb` (which reads from KiCad's in-memory state) reports the
    *pre-move* position. If revert_board didn't fire (or didn't take), the
    moved position will surface here and the assertion fails — surfacing the
    desync that #18 was specifically designed to prevent.
    """
    project = _require_kicad_open()

    snap = _kcd("snapshot", "create", project, "-m", "agentic-loop integration test")
    assert snap["ok"], snap
    snapshot_ref = snap["data"]["short"]

    pcb = _kcd("inspect", "pcb", project)
    assert pcb["ok"], pcb
    target = pcb["data"]["footprints"][0]
    ref = target["reference"]
    x_before = float(target["x_mm"])
    y_before = float(target["y_mm"])
    x_moved = x_before + 5.0
    y_moved = y_before + 5.0

    try:
        moved = _kcd(
            "edit", "move-fp",
            "--ref", ref,
            "--x", str(x_moved),
            "--y", str(y_moved),
        )
        assert moved["ok"], moved

        # Sanity: KiCad's in-memory state reflects the move.
        pcb2 = _kcd("inspect", "pcb", project)
        fp2 = next(fp for fp in pcb2["data"]["footprints"] if fp["reference"] == ref)
        assert abs(float(fp2["x_mm"]) - x_moved) < 0.01, (
            f"move-fp didn't take: expected ({x_moved}, {y_moved}), got "
            f"({fp2['x_mm']}, {fp2['y_mm']})"
        )

        # Restore the pre-move snapshot — disk reverts, AND KiCad's memory
        # must sync via revert_board.
        restored = _kcd("snapshot", "restore", project, snapshot_ref, "--yes")
        assert restored["ok"], restored
        assert restored["data"].get("kicad_reverted") is True, (
            f"expected kicad_reverted=True (KiCad open), got "
            f"{restored['data'].get('kicad_reverted')!r}. Restore data: "
            f"{restored['data']}"
        )

        # The #18 assertion: in-memory state must now read pre-move.
        pcb3 = _kcd("inspect", "pcb", project)
        fp3 = next(fp for fp in pcb3["data"]["footprints"] if fp["reference"] == ref)
        assert abs(float(fp3["x_mm"]) - x_before) < 0.01, (
            f"#18 regression: {ref} still at moved position after restore. "
            f"Expected ({x_before}, {y_before}), got "
            f"({fp3['x_mm']}, {fp3['y_mm']}). KiCad's in-memory state didn't "
            f"sync from the restored disk file."
        )
    finally:
        # Best-effort cleanup: try to restore again if test failed mid-way.
        try:
            _kcd("snapshot", "restore", project, snapshot_ref, "--yes")
        except Exception:
            pass
