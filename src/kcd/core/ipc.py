"""kipy (KiCad IPC) connection helper.

KiCad 10's IPC API lets us talk to a running KiCad instance over a socket.
This module manages the connection and gives us a graceful fallback when
KiCad isn't running — commands that need IPC will raise `IpcUnavailable`,
which callers can catch and fall back to offline S-expression edits.
"""

from __future__ import annotations

from typing import Any


class IpcUnavailable(RuntimeError):
    """Raised when kipy cannot reach a running KiCad instance."""


def connect(timeout_ms: int = 2000) -> Any:
    """Connect to a running KiCad via the IPC API.

    Returns a kipy.KiCad instance. Raises IpcUnavailable on any failure
    (KiCad not running, IPC not enabled, kipy not installed, etc).
    """
    try:
        from kipy import KiCad
    except ImportError as e:
        raise IpcUnavailable(
            "kicad-python (kipy) is not installed. Install with: pip install kicad-python"
        ) from e

    try:
        return KiCad(timeout_ms=timeout_ms)
    except Exception as e:
        raise IpcUnavailable(
            f"Could not reach KiCad over IPC: {e}. "
            "Make sure KiCad 10+ is running and the IPC API is enabled "
            "(Preferences → Plugins → enable the IPC API)."
        ) from e


def get_board(kicad: Any | None = None) -> Any:
    """Return the currently open Board, or raise IpcUnavailable if none is open."""
    k = kicad or connect()
    try:
        return k.get_board()
    except Exception as e:
        raise IpcUnavailable(
            f"No board open in KiCad, or IPC error: {e}. "
            "Open the .kicad_pcb file in KiCad's PCB editor first."
        ) from e
