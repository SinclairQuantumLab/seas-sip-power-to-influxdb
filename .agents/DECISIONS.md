# seas-sip-power-to-influxdb durable decisions

These are accepted repository decisions, not suggestions from a generic relay
template. The user confirmed the operational measurement on 2026-09-15;
current work and historical evidence are recorded separately in
`.agents/HANDOFF.md` and `.agents/VALIDATION.md`.

## Application shape

- On 2026-09-18 the user authorized explicit client Start/Stop methods, then
  extracted them into the independent public `py-seas-sip-power` library.
  The relay consumes `seas_sip_client` via Git submodule + uv editable source.
  Control API and notebook decisions belong to the library. The relay remains
  read-only; no control CLI, automatic Stop on close, or keepalive changes.

- `main.py` is intentionally a sequential top-level script. Configuration,
  InfluxDB setup, source connection, polling, record construction, upload,
  recovery, and cleanup should remain readable from top to bottom.
- Do not introduce `main()`, settings/auth loaders, record-builder helpers,
  application classes, or service frameworks unless explicitly requested.
- The reusable `SAESSIPPowerClient` class is the appropriate boundary for
  stateful UDP connection and protocol complexity.
- Device implementation, tests, all manuals and demo belong to the library;
  relay schema, polling and application tests stay here. Parent pytest and Ruff
  exclude the independent library; run its checks from its own directory.

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

- Operational measurement: `seas-sip-power`, emitted since `625cbe5` and
  confirmed by the user as receiving real uploads on 2026-09-15. Tests and
  README now match it. Preserve this name during maintenance.
- `SAESSIPPower` belongs to historical baseline `139d9a3`. The earlier
  handoff's request to resolve the name is superseded by the user's direction.
  This clarification does not establish which host runs the relay or whether
  old measurement history exists; no database or dashboard migration was done.
- Committed tags: `source` and `Serial number`.
- `main.py` is the only boundary that maps normalized `snake_case` sample
  attributes to exact human-readable InfluxDB field names.
- Read All has no source timestamp. The record uses aware UTC acquisition time
  immediately after a valid response arrives.
- `Pressure[Torr]` is the only optional field. The local record dictionary
  always includes it; a zero conversion rate maps it to `None`, which the
  pinned InfluxDB client omits during line-protocol serialization.
  `OutputPower[W]` is derived from simultaneous current/voltage.
- Renaming the measurement, tags, fields, types, or timestamp behavior is a
  coordinated InfluxDB/Grafana migration, never a formatting cleanup.

## Operation and documentation

- `--settings`, `--once`, and `--dry-run` are preserved CLI surfaces.
- Startup wrappers run the prepared `.venv` interpreter and do not resolve
  dependencies during restart.
- Supervisor owns stdout/stderr logs. No separate local measurement log exists.
- After a successful upload, stdout summarizes `Pressure[Torr]`,
  `OutputCurrent[nA]`, and `OutputVoltage[V]` in that order, followed by
  `and more.`. Unavailable pressure is shown as `None`; dry-run keeps the full
  record representation for pre-upload review.
- README uses the concise Sinclair relay installation/usage style established
  in commit `139d9a3`, including the recursive-submodule note and numbered
  installation/usage steps.
- Multi-device mode is not implemented.

## Explicitly unresolved

- The committed settings-template placeholder/comment change is not yet
  reconciled with ignored local `settings.toml` and contains trailing whitespace.
