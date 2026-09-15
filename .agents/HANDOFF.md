# seas-sip-power-to-influxdb handoff

Last updated: 2026-09-15 (America/Chicago).

## Read first

Read root `AGENTS.md`, then `.agents/DECISIONS.md`, `.agents/VALIDATION.md`, and
`.agents/PROTOCOL.md`. Do not inspect the contents of `imaq-secret`.

## Current state

The user requested the repository and local directory name
`seas-sip-power-to-influxdb` on 2026-09-15 and renamed the GitHub repository.
Package metadata, installation commands, and Supervisor templates now use
that name. The runtime client and InfluxDB measurement remain unchanged.

The checkout now resides at
`C:\Users\Joon\Projects\seas-sip-power-to-influxdb`; origin uses the matching
GitHub URL. Windows prevented renaming the open original directory, so all
contents were moved into the new directory instead. Only the empty old
directory and its empty `.git` directory remain. The new checkout, submodule,
`uv sync`, CLI help, and Ruff were verified after the move.

Codex trusted-project configuration was updated and `codex app` opened the new
workspace. This active thread still carries its original working directory;
use the new workspace for subsequent work. No Codex database or conversation
history was manually rewritten.

The user also moved the two root test files into `.agents/` without changing
their contents. Those moves are preserved and excluded from the rename commit.
Plain pytest no longer discovers them, and the moved script test still assumes
`main.py` is beside it. Completing that test-layout change remains separate work.

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

- The user's unstaged manual move from `manuals/` to `device-docs/` is preserved
  and excluded from this change. The file content is identical. README and
  PROTOCOL still reference the committed `manuals/` path; reconcile these when
  completing the move.
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
