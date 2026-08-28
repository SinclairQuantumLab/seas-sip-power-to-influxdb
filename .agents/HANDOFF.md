# seas-pump-to-influxdb handoff

## Current state

The repository contains a completed read-only, synchronous snapshot relay for
one SAES SIP POWER over Ethernet UDP. `main.py` is a direct top-level polling
script with no application functions or classes: CLI parsing, configuration,
InfluxDB setup, acquisition, record mapping, upload, recovery, and cleanup run
sequentially from top to bottom. Only the stateful UDP protocol boundary remains
a reusable client. Dual-platform startup, Supervisor templates, tests, lockfile,
and the operator README are present. Offline checks and a current real-device
dry-run passed after the direct-script rewrite on 2026-08-28.

## Next action

Create the ignored `auth.toml` with authorized InfluxDB values, then run exactly
one `uv run python main.py --once` upload and confirm the point before starting
`Startup.ps1`, `Startup.sh`, or Supervisor.

## Blockers and unknowns

- No InfluxDB credentials or upload authorization were supplied, so upload was
  intentionally not attempted.
- No deployment host or Supervisor installation has been selected.
- The private `imaq-secret` repository was not added because that separate
  credential-submodule action was not authorized.
