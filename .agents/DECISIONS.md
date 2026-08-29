# seas-pump-to-influxdb durable decisions

These are accepted repository decisions, not suggestions from a generic relay
template. Current uncommitted candidates are listed separately in
`.agents/HANDOFF.md` and do not become decisions merely by appearing in a diff.

## Application shape

- `main.py` is intentionally a sequential top-level script. Configuration,
  InfluxDB setup, source connection, polling, record construction, upload,
  recovery, and cleanup should remain readable from top to bottom.
- Do not introduce `main()`, settings/auth loaders, record-builder helpers,
  application classes, or service frameworks unless explicitly requested.
- The reusable `SAESSIPPowerClient` class is the appropriate boundary for
  stateful UDP connection and protocol complexity.

## Settings and credentials

- Trusted local settings are read directly from TOML without a validation or
  narrowing framework.
- The flat settings contract is `interval_s`, `host`, optional `port`, and
  `timeout_s`. Port defaults to 2527 when omitted.
- Measurement, reconnect delay, and exception threshold are not settings.
- Credentials come only from `imaq-secret/auth.toml` for upload-enabled runs.
  Dry-run does not open that file.

## Source and recovery

- Acquisition is one-device, synchronous snapshot polling over connected IPv4
  UDP using the read-only Read All command.
- One source failure receives one immediate socket replacement and retry.
- There is no retry delay. Only an unresolved retry or write failure increments
  the lifetime count. Successful cycles do not reset it. The third failure exits
  nonzero for Supervisor.
- Polling uses cycle-start deadlines, so source/write duration is subtracted
  from the next wait and cycles do not overlap.

## InfluxDB compatibility

- Committed measurement: `SAESSIPPower`.
- Committed tags: `source` and `Serial number`.
- `main.py` is the only boundary that maps normalized `snake_case` sample
  attributes to exact human-readable InfluxDB field names.
- Read All has no source timestamp. The record uses aware UTC acquisition time
  immediately after a valid response arrives.
- `Pressure[Torr]` is the only optional field and is omitted when conversion
  rate is zero. `OutputPower[W]` is derived from simultaneous current/voltage.
- Renaming the measurement, tags, fields, types, or timestamp behavior is a
  coordinated InfluxDB/Grafana migration, never a formatting cleanup.

## Operation and documentation

- `--settings`, `--once`, and `--dry-run` are preserved CLI surfaces.
- Startup wrappers run the prepared `.venv` interpreter and do not resolve
  dependencies during restart.
- Supervisor owns stdout/stderr logs. No separate local measurement log exists.
- README uses the concise Sinclair relay installation/usage style established
  in commit `139d9a3`, including the recursive-submodule note and numbered
  installation/usage steps.
- Multi-device mode is not implemented.

## Explicitly unresolved

- The dirty `seas-sip-power` measurement name is only a migration candidate.
  It conflicts with the committed contract, tests, and README until the user
  explicitly decides the migration scope.
- The dirty settings-template placeholder/comment change is not yet reconciled
  with ignored local `settings.toml`.

