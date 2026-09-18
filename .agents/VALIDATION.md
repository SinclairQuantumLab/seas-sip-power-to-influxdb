# SAES SIP POWER validation

Evidence below separates current offline checks, operator-confirmed operation,
and historical live reads. Lack of an agent-run check is not evidence that the
relay is unused.

## Current alignment checks - 2026-09-15

### Final workspace and file-layout checks - 2026-09-15

After the user restarted Codex, default shell execution, the Git root, and this
thread's stored working directory all point to `seas-sip-power-to-influxdb`.
Origin uses the renamed GitHub repository and the old directory is absent.

The tests moved to `.agents/` are now discovered by the root pytest command;
their import path and `main.py` location are explicit. The SIP POWER manual
move preserves its exact bytes, and README/PROTOCOL reference `device-docs/`.
The user's NEXTorr Z manual and specs are included alongside it.

- `uv run pytest -q`: all 18 tests passed in the actual worktree.
- `uv run ruff check .`: passed.
- `uv run python main.py --help`: passed with all three existing CLI flags.
- The moved environment's pytest launcher initially failed to canonicalize its
  old script path. `uv sync --reinstall` repaired the installed entry points;
  `uv venv --allow-existing` regenerated activation scripts, then `uv sync`
  confirmed the environment. Locked dependency versions are unchanged.
- No live controller access, InfluxDB upload/query, or Supervisor restart.

### Repository rename checks - 2026-09-15

The rename changes project metadata, documentation, and Supervisor template
paths, without changing runtime code or the `seas-sip-power` measurement.
`uv sync` and Ruff passed. The existing 18 tests passed under Python 3.11.14
in an isolated temporary snapshot containing the current runtime, Supervisor
helpers, project metadata, and committed root tests. The first incomplete
snapshot omitted the Supervisor helpers; that setup error was corrected.

In the actual worktree, the user's pre-existing move of both tests into
`.agents/` makes `uv run pytest -q` report no tests collected (exit 5).
The moved files are byte-identical to their committed versions; the move and
its test-discovery/path follow-up are excluded from the rename commit.
No controller access, upload, or Supervisor restart was performed.

### Measurement alignment

Starting commit: `595fd37`, the user's merge of remote `eedb35c` and local
handoff notes. The following results apply to that runtime plus the test and
documentation alignment recorded in the same commit as this document:

- Before changes: `uv run pytest -q` reported 16 passed, 2 failed. Both failures
  expected historical `SAESSIPPower` while the runtime emitted `seas-sip-power`.
- After updating the two expectations: `uv run pytest -q` passed all 18 tests.
- `uv run ruff check .`: passed.
- Scoped `git diff --check` for the changed tests and documents: passed.
- README/schema comparison: operational measurement `seas-sip-power`, both
  tags, all 44 field names/types, UTC timestamp policy, and all three CLI flags
  match the runtime. Optional pressure is retained as `None` locally and omitted
  from InfluxDB line protocol, as verified by the existing test.
- Runtime code, source protocol, settings, startup wrappers, and dependencies
  were unchanged. Source and writer doubles performed all test I/O.
- No new live device check, InfluxDB upload or query, or Supervisor check was
  performed. Credential contents were not inspected.

The user's existing manual move is unrelated and remains unstaged. The
settings template's pre-existing trailing whitespace also remains outside this
change; the scoped whitespace result does not claim the entire historical
repository is free of whitespace findings.

## Operator-confirmed operation - 2026-09-15

The user stated that real data is already uploaded to `seas-sip-power`, and
subsequently authorized aligning the tests and documentation with that name.
Both local and remote runtime code already used it. The older name in tests
and README was stale; the earlier request to decide the measurement is resolved.

This is operator-provided evidence. The running host, deployed commit,
Supervisor state, stored point contents, Grafana queries, and any historical
`SAESSIPPower` series were not independently inspected. No downstream migration
was needed to preserve the existing runtime name or attempted in this task.

## Historical offline evidence - 2026-08-28

At baseline `139d9a3`, measurement was `SAESSIPPower`, with flat settings,
default port 2527, immediate reconnect/retry, and the hard-coded three-failure
lifetime threshold. `uv sync` passed with CPython 3.11.14, all 18 tests passed,
and Ruff passed. README and tests matched the then-current schema.

Commit `625cbe5` changed runtime measurement to `seas-sip-power` without updating
tests and README. The recorded result was 16 passed, 2 failed (the two exact
measurement assertions), with Ruff passing and trailing whitespace in the
settings-template host example. Later commits `c4404bb` and `eedb35c` changed
successful-upload logs and optional-pressure handling; their focused test
verified `None` retention, omission from line protocol, and the selected log
values. These historical failures are superseded by the current alignment.

The suite covers direct settings loading, protocol field groups, truncated
and wrong-header frames, timestamps, record mapping, optional pressure,
credential isolation, direct read/write behavior, immediate reconnect/retry,
cumulative lifetime failure handling, cycle-start timing, writer failure, and
cleanup.

## Historical live read-only evidence - 2026-08-28

Environment: Windows host on the controller LAN, endpoint
`192.168.50.34:2527`, America/Chicago.

1. A PowerShell UDP probe sent the documented two-byte Read All request with a
   3-second timeout. The peer returned 302 bytes with version 1 and command 128.
2. The clean application path ran:

   ```text
   uv run python main.py --settings settings.toml --once --dry-run
   ```

   It exited 0 and produced one normalized `SAESSIPPower` record for serial
   25040035. Representative values were hardware 2.2, software 2.0, input
   24.0 V, internal temperature 302 K, and returned IP 192.168.50.34.

No raw response frame was retained, no controller state was changed, no
credential file was opened, and nothing was uploaded during that check.


## 2026-09-16 standard signal shutdown

The user authorized replacing synchronous signal-handler `threading.Event`
coordination with `signal.default_int_handler` for SIGINT and SIGTERM.
Both now interrupt reads, uploads, and `time.sleep` through `KeyboardInterrupt`,
run existing `finally` cleanup, and exit 130 without polling retries. Source
protocols, schema, normal scheduling, and ordinary failure policies are unchanged.

- `uv run --no-sync python -m pytest -q`: 24 passed.
- Six new cases invoke the registered handler during acquisition, upload, and
  sleep for each signal; they verify cleanup and absence of source retry.
- Ruff and Git whitespace checks passed.
- Tests use synthetic source and InfluxDB boundaries. No live device connection,
  upload, startup wrapper, service restart, or deployed configuration change was
  performed for this task. Windows service signal delivery is not qualified by
  these in-process handler tests.


## 2026-09-18 explicit HV control and notebook

- Baseline `3895a74`: 24 tests and Ruff passed; worktree was clean.
- Current change: 32 tests and Ruff passed. Added checks cover exact Start/Stop
  datagrams, absence of ACK reads, explicit readback, no Stop on close,
  disconnected use, and failed/short sends without automatic retries.
- All notebook code cells execute offline with a fake socket and synthetic
  settings from both repository-root and demo-folder working directories.
  Stored notebook outputs are empty. No input parsing or exception handling
  was added to the notebook.
- Optional `notebook` dependency group supplies ipykernel. Production relay
  dependencies, `main.py`, schema, polling, and recovery behavior are unchanged.
- No live device commands, InfluxDB access, or service restart was performed.
  Actual firmware acceptance and HV transitions remain unverified on hardware.

## 2026-09-18 standalone source library extraction

- py-seas-sip-power is a separate uv project, Git repository and editable path
  dependency. The source module is renamed to seas_sip_client, byte-for-byte
  identical to b18c3a3. Parent main.py changes only its import/grouping.
- Consumer: 16 tests passed, Ruff passed, CLI help passed.
- Library: 15 tests passed, Ruff passed, wheel/sdist built. The previous pair of
  notebook cwd cases is one library-local case, explaining 31 combined tests.
- The user's executed notebook was backed up locally before adapting imports
  and settings for the independent library. No live operation was performed.
- A fresh temporary consumer checkout fetched only the public library submodule,
  ran uv sync and all 16 relay tests successfully, and imported from that local
  editable source. The credential submodule was not initialized or read.
- The built library wheel was installed in an isolated environment and imported
  successfully from site-packages, with Start/Stop bytes 0101/0102.
