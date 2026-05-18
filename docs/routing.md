# Routing with kcd

## What works

- **Single straight tracks** via `kcd route track` — uses kipy IPC. Requires KiCad 10 open with the PCB editor and the IPC API enabled.
- **FreeRouting orchestration** via `kcd route freeroute` — runs FreeRouting headlessly on a `.dsn` file to produce a `.ses` file you import back into KiCad.

## What doesn't (yet)

- **Differential pair routing**, including length tuning, is not implemented. The kicad-mcp-pro project had this as a v2 goal too — it's a tar pit because length-tuning requires interactive feedback to lay out meanders that stay within design rules.
- **Push-and-shove routing** (KiCad's interactive router) is not exposed via IPC.
- **Direct headless Specctra DSN export from kicad-cli** is unreliable across platforms on KiCad 10. You'll need to export the `.dsn` from KiCad's PCB Editor manually (File → Export → Specctra DSN).

## FreeRouting setup

1. Download a release JAR from https://github.com/freerouting/freerouting/releases
2. Note the path (e.g. `~/tools/freerouting-2.1.0.jar`)
3. Set the env var:
   ```bash
   export KCD_FREEROUTING_JAR=~/tools/freerouting-2.1.0.jar
   ```
   Add this to your shell profile if you want it persistent.

You also need `java` on PATH. Any JRE 11+ works.

## End-to-end FreeRouting workflow

```bash
# 1. Snapshot
kcd snapshot create ./proj -m "before autoroute" --json

# 2. In KiCad's PCB editor: File → Export → Specctra DSN → save as proj.dsn
#    (manual step; kicad-cli's headless export of DSN is flaky on KiCad 10)

# 3. Run FreeRouting
kcd route freeroute ./proj --dsn proj.dsn --out-ses proj.ses --passes 100 --opt-passes 20

# 4. In KiCad's PCB editor: File → Import → Specctra Session → select proj.ses
#    (manual step)

# 5. Verify with DRC
kcd drc ./proj --json
```

## When FreeRouting fails

Common failure modes and fixes:

- **`No DSN file found`** — Export it from KiCad first (step 2 above).
- **`java not found`** — Install a JRE (e.g. `apt install openjdk-17-jre`).
- **Timeout after 600s** — Increase `--timeout`, or reduce `--passes`. Large boards (>500 nets) routinely need 30-60 minutes.
- **DSN parse error** — Your KiCad version's DSN export may differ from what FreeRouting expects. Update FreeRouting to the latest release.
- **No .ses produced despite success** — Check FreeRouting's working directory for a partial result. Sometimes it writes to the JAR's directory instead of where we asked.

## Single-track routing

```bash
kcd route track ./proj \
    --net VCC \
    --from 100,50 \
    --to 110,50 \
    --layer F.Cu \
    --width 0.25 \
    --json
```

Coordinates are in millimeters in KiCad's coordinate system. Use `kcd inspect ref <proj> <REF> --json` to find pad positions.

This auto-snapshots before adding the track. If the track ends up wrong (wrong net, overlapping a pad, etc.), `kcd snapshot restore <proj> HEAD~1 --yes`.

## Why no diff-pair length tuning in v1

Three reasons:
1. KiCad's interactive length tuner (the one in PCB Editor) is not exposed via IPC.
2. Implementing meander generation from scratch is a multi-thousand-line effort with corner cases for layer changes, vias, and clearance to neighboring tracks.
3. FreeRouting handles diff-pair *routing* reasonably well but doesn't tune length precisely.

If you need tuned diff pairs, the realistic workflow is:
1. Route the diff pair with `kcd route freeroute` (FreeRouting handles the pairing constraint if your `.dsn` declares it).
2. Open the result in KiCad PCB editor.
3. Use KiCad's interactive length tuner (Route → Tune Length / Tune Differential Pair).

This is on the roadmap for v0.3+ but realistically depends on KiCad exposing length-tuning over IPC.
