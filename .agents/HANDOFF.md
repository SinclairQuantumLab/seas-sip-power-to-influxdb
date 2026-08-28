# seas-pump-to-influxdb handoff

## Current state

The repository contains a completed read-only, synchronous snapshot relay for
one SAES SIP POWER over Ethernet UDP. The parser, full InfluxDB record mapping,
settings, retry and lifetime-failure behavior, cleanup, dual-platform startup,
Supervisor templates, tests, lockfile, and self-contained operator README are
present. Offline checks and one current real-device dry-run passed on 2026-08-28.

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
