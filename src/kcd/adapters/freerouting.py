"""FreeRouting orchestration via Specctra `.dsn` round-trip.

KiCad 10 still does not expose a clean headless Specctra DSN export through
kicad-cli reliably across platforms. The pragmatic approach:

1. Have the user export `.dsn` from KiCad's PCB Editor (File → Export → Specctra).
   OR: try kicad-cli pcb export specctradsn (newer builds).
2. Run FreeRouting on the .dsn to produce a .ses.
3. Have the user import the .ses back in KiCad (File → Import → Specctra Session).

We automate steps 2 and 3-via-IPC where possible. Step 1 still benefits from
a running KiCad to push the export through IPC if available.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class FreeroutingError(RuntimeError):
    pass


@dataclass
class FreeroutingResult:
    dsn: Path
    ses: Path
    passes: int
    log: str


def autoroute(
    jar_path: str,
    dsn_path: Path,
    out_ses: Path,
    optimization_passes: int = 20,
    routing_passes: int = 100,
    timeout_seconds: int = 600,
) -> FreeroutingResult:
    """Run FreeRouting headlessly on a `.dsn` file, producing a `.ses` file.

    Requires `java` on PATH and a FreeRouting JAR (https://github.com/freerouting/freerouting).
    """
    if not Path(jar_path).is_file():
        raise FreeroutingError(f"FreeRouting JAR not found: {jar_path}")
    if not dsn_path.is_file():
        raise FreeroutingError(f"DSN file not found: {dsn_path}")
    out_ses.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "java", "-jar", jar_path,
        "-de", str(dsn_path),
        "-do", str(out_ses),
        "-mp", str(routing_passes),
        "-op", str(optimization_passes),
    ]

    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_seconds
        )
    except subprocess.TimeoutExpired as e:
        raise FreeroutingError(
            f"FreeRouting timed out after {timeout_seconds}s. "
            "Increase --timeout or reduce passes."
        ) from e
    except FileNotFoundError as e:
        raise FreeroutingError(
            "`java` not found on PATH. FreeRouting requires a JRE."
        ) from e

    if proc.returncode != 0:
        raise FreeroutingError(
            f"FreeRouting failed (exit {proc.returncode}):\n"
            f"stderr: {proc.stderr.strip()}"
        )

    if not out_ses.is_file():
        raise FreeroutingError(
            "FreeRouting completed but did not produce a .ses file. "
            "Check the DSN input."
        )

    return FreeroutingResult(
        dsn=dsn_path,
        ses=out_ses,
        passes=routing_passes,
        log=proc.stdout,
    )
