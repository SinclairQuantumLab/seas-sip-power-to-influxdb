# seas-sip-power-to-influxdb handoff

Last updated: 2026-09-18 (America/Chicago).

## Read first

Read root `AGENTS.md`, then `.agents/DECISIONS.md`, `.agents/VALIDATION.md`, and
`.agents/PROTOCOL.md`. Do not inspect the contents of `imaq-secret`.

## Current state

The shared client now has explicit `start()` and `stop()` methods for HV output.
`py-seas-sip-power/demo.ipynb` demonstrates connection, readback, Start with ten
polls, Stop with readback, and close. Install its kernel with
`uv sync --group notebook`. No live control commands were sent. `main.py` and
the InfluxDB schema remain unchanged; the relay still only reads the device.
The new methods have no ACK or retry. Keepalive is documented and unchanged.

The September 16 shutdown update uses `signal.default_int_handler` for SIGINT
and SIGTERM, replacing the synchronous stop Event. The first signal interrupts
current work; `finally` closes resources and the relay exits 130. All 24 offline
tests and Ruff pass. See the dated entry in `VALIDATION.md`; no live operation
or service restart was performed for this change.

The user requested the repository and local directory name
`seas-sip-power-to-influxdb` on 2026-09-15 and renamed the GitHub repository.
Package metadata, installation commands, and Supervisor templates now use
that name. The runtime client and InfluxDB measurement remain unchanged.

The checkout now resides at
`C:\Users\Joon\Projects\seas-sip-power-to-influxdb`; origin uses the matching
GitHub URL. Windows prevented renaming the open original directory, so all
contents were moved into the new directory instead. The user deleted the empty
old directory; its absence is verified.

Codex trusted-project configuration and this thread's stored working directory
and Git origin were updated, with a local database backup. After the user
restarted Codex, default shell execution, Git root, and stored thread metadata
all resolve to the new workspace. Conversation history was not rewritten.

The user's test move into `.agents/` is completed with explicit pytest discovery
and import paths and a corrected path to root `main.py`. The SIP POWER manual
now lives under `device-docs/` alongside the user's NEXTorr Z manual and specs.
README and protocol references use the new location.

The user confirmed on 2026-09-15 that real data is already uploaded to
`seas-sip-power` and requested alignment of stale tests and documentation.
The measurement decision is resolved. Preserve the current runtime name;
there is no pending decision to restore `SAESSIPPower`.

The user pulled the two remote commits `c4404bb` and `eedb35c` without conflicts
in merge `595fd37`. This follow-up changes tests and documentation only:

- Both exact measurement assertions now expect `seas-sip-power`.
- README documents the operational measurement and distinguishes the user's
  upload confirmation from agent-run offline checks and historical live reads.
- Root agent instructions and current handoff/decision/protocol notes no longer
  describe the measurement name as an unresolved migration.
- Runtime code, tags, all 44 fields, value types, acquisition timestamps,
  settings, retry policy, and startup wrappers are unchanged.
- No database, dashboard, alert, query, or history migration was performed.

## Runtime summary

- `main.py` remains a direct sequential top-level script; the reusable
  `saes_sip_power_client.py` owns connected IPv4 UDP Read All and parsing.
- One device is polled synchronously. Flat settings are `interval_s`, `host`,
  optional `port` (default 2527), and `timeout_s`.
- One source failure receives an immediate socket replacement and one retry.
  The third unresolved lifetime failure exits nonzero; success does not reset
  the counter. The CLI supports `--settings`, `--once`, and `--dry-run`.
- Tags are `source` and `Serial number`. Timestamp is aware host UTC acquisition
  time because Read All has no source timestamp.
- The record always contains `Pressure[Torr]`; unavailable pressure is `None`,
  which the InfluxDB client omits when serializing line protocol.
- Successful-upload logs show pressure, current, voltage, and `and more.`.
  Dry-run prints the complete record. Supervisor owns stdout/stderr logs.

## Validation and evidence

At the final rename follow-up, all 18 tests pass directly in this worktree with
`uv run pytest -q`; Ruff and CLI help also pass. Moving the existing virtual
environment left stale entry-point paths, fixed with `uv sync --reinstall`.
`uv venv --allow-existing` regenerated activation scripts for the new path,
followed by `uv sync`. Dependency versions and runtime behavior are unchanged.

The worktree based on merge `595fd37`, with the aligned tests and documentation,
passed all 18 tests and Ruff on 2026-09-15. Before the alignment it had 16
passes and two failures caused by stale measurement expectations.

The last agent-recorded live read was a successful dry-run on 2026-08-28 under
the former `SAESSIPPower` measurement. The user's 2026-09-15 confirmation
establishes current uploads to `seas-sip-power`; the agent did not independently
query InfluxDB or identify the running deployment. No new device access,
upload, continuous-run check, or Supervisor verification was performed here.
See `VALIDATION.md` for details.

## Existing changes and remaining housekeeping

- `settings.toml.template` has an existing trailing space on its host example.
  Its comment layout differs from ignored local `settings.toml`. These settings
  files were not changed by the measurement-documentation task.
- Local settings at review time use host `192.168.50.34`, interval 2 seconds,
  default port 2527, and timeout 3 seconds; the template interval is 30 seconds.

## Reference provenance

The 2026-09-15 takeover refreshed the organization inventory to 13 accessible
relay candidates; scope and branch details are in `TAKEOVER-2026-09-15.md`.
The loaded skill preflight was rerun for this follow-up and reported
`current-dirty`, ahead 0 / behind 0; existing skill edits were preserved.

Historical runtime references remain `ULE-Ion-pump-to-influxdb` `main`,
`LFI3751-to-influxdb` `master`, and `nut-to-influxdb` `main` for direct polling
and immediate retry. ULE supplies the pressure/current/voltage log order; NUT
shows selected missing values as `None`. README provenance is HiCube Neo and
IQAir (`main`). These are design references, not runtime dependencies. This
follow-up aligns the target with its user-confirmed behavior and introduces
no new family convention.
