# seas-sip-power-to-influxdb handoff

Last updated: 2026-09-18 (America/Chicago).

## Read first

Read root `AGENTS.md`, then `.agents/DECISIONS.md`, `.agents/VALIDATION.md`, and
`.agents/PROTOCOL.md`. Do not inspect the contents of `imaq-secret`.

## Current ownership

- This checkout is `C:\Users\Joon\Projects\seas-sip-power-to-influxdb`, with
  the matching GitHub origin. The old folder was removed and the Codex thread's
  working directory was verified after restart.
- `py-seas-sip-power/` is an independent public library Git submodule, installed
  as a uv editable dependency. Import `seas_sip_client`. Device implementation,
  tests, all manuals and the demo belong there; follow its own `AGENTS.md` and
  `.agents/HANDOFF.md` for library work.
- All manuals are now in `py-seas-sip-power/device-docs/`. The user's NEXTorr Z
  manual/specifications move was verified byte-for-byte against the parent Git
  baseline. Published library commit `b4dc57d` contains only those two additions.
  The old relay-level `device-docs/` directory is gone.
- `main.py`, application tests, schema, polling and upload policy remain here.
  Parent pytest and Ruff checks exclude the library. Its README owns demo setup
  and usage instructions; avoid duplicating those instructions in this repo.
- The separate Codex thread `Developing py-seas-sip-power` uses the library
  directory. Its local identifiers are in ignored
  `.agents/local/library-thread.json`.

## Latest library review and next step

The user requested a commit checkpoint and review before adapting this relay.
Library implementation `95bc12b` and handoff `a1c1d1f` are committed, clean and
published; origin/main was fetched and matched `a1c1d1f` at review time. Parent
checkpoint `a8bdc77` pins that revision. `uv sync` refreshes only the library's
optional/development metadata in the parent lockfile; it adds no runtime package.

The library now provides `SAESSIPPower(ConnectionSettings(...))`, selected with
`ConnectionTypeEnum`, returning `DeviceStatus`. It supports UDP, Modbus TCP/RTU,
explicit enum-controlled read/write access, the full remote command interface
and a Jupytext demo. Its AGENTS.md has a dedicated consumer integration section.
The current relay still uses the compatible `SAESSIPPowerClient` and
`SAESSIPPowerSettings`; its source and application tests have not been migrated.

Recommended next implementation: adopt the common device API with explicit
`ConnectionTypeEnum.UDP` and `AccessModeEnum.READ_ONLY`, retaining flat settings,
one `read_sample()` per acquisition, lifecycle/retry behavior and the exact
InfluxDB mapping. Update test constructors/fixtures and cover read-only access
and the real UDP-to-record boundary. No adapter/service layer is needed.

Keep transport expansion a separate decision: Modbus cannot observe Modbus ID,
may lack network/keepalive fields, and uses four or five reads per snapshot.
That affects field presence and acquisition/timeout semantics despite the common
Python interface. Never substitute configured values for missing observations.
The `status` property performs I/O each time; cache a returned snapshot locally
when building a record. The new `is_single_response` metadata is not an InfluxDB
field in the current schema. Control or broadcast support in the library does
not change this relay's read-only scope.

The operator's pre-extraction notebook is preserved in ignored
`.agents/local/demo-before-library-split.ipynb`. Library notebook migration and
output preservation are managed in its own repository.

## Runtime contract

- `main.py` remains a direct sequential top-level script. It only calls the
  library's synchronous UDP Read All path; no control command is added here.
- Flat settings are `interval_s`, `host`, optional `port` (default 2527), and
  `timeout_s`. CLI flags are `--settings`, `--once`, and `--dry-run`.
- One source failure gets immediate socket replacement and one retry. The
  third unresolved lifetime failure exits nonzero; success does not reset it.
- Measurement is `seas-sip-power`, confirmed operational by the user on
  2026-09-15. Tags are `source` and `Serial number`; preserve all field names,
  types and aware host UTC acquisition timestamps.
- The record includes `Pressure[Torr]`; unavailable pressure is `None`, omitted
  by InfluxDB line-protocol serialization. Dry-run prints the complete record.
- SIGINT/SIGTERM interrupt current work through `KeyboardInterrupt`, run
  `finally` cleanup and exit 130. Supervisor owns stdout/stderr logs.

## Evidence and remaining work

See the dated entries in `VALIDATION.md` for extraction and cleanup checks.
Current review: 16 relay tests, 299 library tests and both Ruff checks pass
against `a1c1d1f`. A fake-socket comparison also preserves all 44 relay field
values/types and identity through the common UDP API, including missing pressure.
Historical test counts describe their corresponding revisions, not the current
suite. The last agent-recorded live read was on 2026-08-28; the user's
2026-09-15 upload confirmation is separate operator evidence. This cleanup
and the current review perform no hardware access, InfluxDB query/upload or
service restart. Parent checkpoint/review commits are local pending the next
consumer-development step; no parent push was requested in this review.

The settings template's pre-existing trailing whitespace and comment-layout
difference from local settings are unrelated to the library split and remain.

## Reference provenance

The review compares this relay's `9d0c13b` baseline and library
`b4dc57d..a1c1d1f`, both on `main`; it introduces no new family convention.
The skill-source preflight reported `skipped-diverged`, ahead 106 / behind 106 of
`origin/feature/to-influxdb-development`. No skill history repair or edit was
attempted. This is a source-freshness limitation, not a consumer-library failure.
The refreshed organization inventory has 15 nonempty, unarchived relay
repositories (LFI3751 uses `master`, the others `main`). Earlier comparative
evidence remains in `TAKEOVER-2026-09-15.md` and the skill's repository corpus.
