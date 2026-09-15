# seas-sip-power-to-influxdb Agent Instructions

## Goal

Maintain a small, synchronous, read-only snapshot relay from one SAES SIP POWER
controller to InfluxDB without accidentally changing its Grafana-facing schema
or the direct Sinclair-style script structure chosen by the user.

## Start here

Before editing anything:

1. Run `git status --short` and inspect every unstaged and staged diff. Existing
   changes may belong to the user or another agent; do not restore, rewrite,
   stage, or commit them merely to obtain a clean tree.
2. Read, in order:
   - this file;
   - `.agents/HANDOFF.md` for the exact current worktree and next decision;
   - `.agents/DECISIONS.md` for durable design choices;
   - `.agents/VALIDATION.md` for evidence and its date;
   - `.agents/PROTOCOL.md` before changing device access or parsing.
3. Read the relevant implementation, tests, README, and recent Git history.
   Treat handoff notes as navigation, not as a substitute for the source.
4. Use the `to-influxdb-development` skill for relay implementation,
   configuration, schema, recovery, deployment, or README work. Refresh its
   repository evidence as instructed by the skill.

## File ownership

- `saes_sip_power_client.py` owns connection lifecycle, UDP framing, protocol
  validation, parsing, and normalized `snake_case` samples.
- `main.py` owns CLI parsing, trusted local settings, polling policy, exact
  InfluxDB names, upload, failure accounting, signals, and cleanup. It is a
  sequential top-level script. Do not introduce `main()`, orchestration helper
  methods, configuration loaders, record builders, or service/runner classes
  without an explicit user request.
- `settings.toml.template` documents deployer settings. Ignored `settings.toml`
  contains local values. When the settings layout or comments change, keep
  their key order, comments, and formatting aligned; local values may differ.
- `README.md` is the user manual. Preserve its current concise Sinclair relay
  shape: `Requirements`, numbered `Installation`, numbered `Usage`,
  `Data written to InfluxDB`, `Troubleshooting`, `Validation status`, and
  `Developer's note`.
- `.agents/` contains developer protocol, decisions, validation evidence, and
  current handoff state. Update it when evidence or unresolved work changes.
- Startup wrappers execute the prepared `.venv` interpreter and must not run
  dependency resolution during a restart.

## Runtime contract

Unless the user explicitly requests a migration:

- One controller is polled synchronously through read-only UDP Read All.
- Settings are flat: `interval_s`, `host`, optional `port`, and `timeout_s`.
  Omitted `port` uses `DEFAULT_PORT` 2527. Do not add a `[source]` section,
  configurable measurement, reconnect delay, or exception-threshold setting.
- The operational measurement is `seas-sip-power`. On 2026-09-15 the user
  confirmed that real data is already uploaded under this name and requested
  that stale tests and documentation be aligned with it. `SAESSIPPower` was
  the historical name before `625cbe5`; do not restore it during maintenance.
  Exact tags, field names, field types, and aware UTC acquisition timestamp
  semantics remain compatibility surfaces for InfluxDB, Grafana dashboards,
  alerts, and queries.
- One source failure replaces the socket immediately and retries once. There is
  no configured delay. An unresolved cycle increments one lifetime counter;
  success does not reset it, and the hard-coded third failure exits nonzero.
- CLI compatibility is `--settings`, `--once`, and `--dry-run`.
- Local measurement logging and multi-device operation are deliberately absent.
  Supervisor owns continuous-process stdout and stderr logs.
- Trusted deployer TOML values are read directly. Do not add commercial-style
  parsing, schema frameworks, assertions, or redundant type/value validation.

## Coding and documentation rules

- Prefer simplicity and direct readability over method-based decomposition.
  Keep source-specific complexity inside the reusable client, not in an
  application framework.
- Add precise type hints and useful docstrings to actual Python functions,
  methods, classes, callbacks, and test helpers. Do not create functions merely
  to host type hints or docstrings.
- Keep source-facing attributes in `snake_case` and map them to human-readable
  InfluxDB names only in `main.py`.
- Preserve measurement, tags, fields, value types, timestamp, CLI, timing,
  retry, and cleanup behavior unless the requested scope explicitly changes
  them. A measurement rename is an InfluxDB/Grafana migration, not formatting.
- Update README in the same change whenever commands, settings/defaults, schema,
  timestamps, acquisition/recovery, credential location, startup wrappers, or
  Supervisor paths change.
- Keep README operator-centered. Put implementation details only at the end
  under the exact heading `## Developer's note`.
- Use `git clone --recurse-submodules ...` as the primary installation path and
  document `git submodule update --init --recursive` for an existing
  nonrecursive checkout.
- Keep credentials only in the private `imaq-secret` submodule. Never inspect,
  print, copy, or commit credential contents.
- Use plain `uv sync` for dependency installation or updates so `uv.lock` may
  refresh. Do not routinely replace it with lock-preserving variants.

## Verification and commits

- Run `uv run pytest -q` and `uv run ruff check .` after relevant changes.
- Before live access, run offline checks first. Then use
  `uv run python main.py --settings settings.toml --once --dry-run` for one
  read-only check. Never upload without explicit authorization.
- Compare README settings, commands, measurement, tags, all field names/types,
  timestamps, paths, and success criteria against the finished repository.
- Distinguish committed baseline evidence, current dirty-worktree evidence,
  historical live evidence, and checks that were not run.
- Make focused Git commits at meaningful checkpoints and before material or
  difficult-to-reverse work. Exclude unrelated user/agent changes from the
  commit and report anything intentionally left uncommitted.
