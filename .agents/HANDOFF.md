# seas-pump-to-influxdb handoff

## Current state

The repository contains a completed read-only, synchronous snapshot relay for
one SAES SIP POWER over Ethernet UDP. `main.py` is a direct top-level polling
script with no application functions or classes: CLI parsing, configuration,
InfluxDB setup, acquisition, record mapping, upload, recovery, and cleanup run
sequentially from top to bottom. Only the stateful UDP protocol boundary remains
a reusable client. The main script uses the established Sinclair paired section
comments and uppercase IMAQ/InfluxDB configuration names. It reads trusted local
TOML values directly without an application validation or narrowing layer, and
passes `AUTH["influxdb"]` directly to the InfluxDB client. The common private
`imaq-secret` repository is tracked as a submodule at `imaq-secret`.
Deployment settings are flat and contain only the polling interval and source
address/timeout; the optional port defaults to 2527. The measurement and
three-failure lifetime threshold are fixed in `main.py`, and source retry is
immediate.
Dual-platform startup, Supervisor templates, tests, lockfile, and the operator
README are present. Offline checks and a current real-device dry-run passed
after the simplicity refactor on 2026-08-28.

## Next action

With an authorized checkout of the private `imaq-secret` submodule, run exactly
one `uv run python main.py --once` upload and confirm the point before starting
`Startup.ps1`, `Startup.sh`, or Supervisor.

## Blockers and unknowns

- The `imaq-secret` submodule is tracked at the common Sinclair path. Its
  credential contents were not inspected or printed, and no upload
  authorization was supplied, so upload was intentionally not attempted.
- No deployment host or Supervisor installation has been selected.
