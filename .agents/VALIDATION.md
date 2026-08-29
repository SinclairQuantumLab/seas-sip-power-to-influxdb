# SAES SIP POWER validation

Evidence is separated below so a later agent does not treat a historical clean
result as proof about the current dirty worktree.

## Current dirty-worktree checks - 2026-08-28

Base commit: `139d9a3 Align README with relay installation style`.

Uncommitted application/configuration changes:

- `main.py`: measurement candidate `SAESSIPPower` -> `seas-sip-power`.
- `settings.toml.template`: placeholder host/comment changes with one trailing
  whitespace finding.

Results:

- `uv run pytest -q`: 2 failed, 16 passed. The failures are
  `test_direct_script_maps_complete_schema` and
  `test_direct_script_loads_settings`; both expect `SAESSIPPower` while dirty
  `main.py` emits `seas-sip-power`.
- `uv run ruff check .`: passed.
- `git diff --check`: failed only on trailing whitespace in the dirty settings
  template.
- README/code schema comparison: measurement differs; README still documents
  committed `SAESSIPPower`.
- Live device check: not run for this dirty state.
- InfluxDB upload: not run.

The current worktree is therefore not a verified release candidate.

## Last verified committed baseline - 2026-08-28

The committed baseline used measurement `SAESSIPPower`, flat settings, omitted
port defaulting to 2527, immediate reconnect/retry, and a hard-coded
three-failure lifetime threshold.

Offline results before the later dirty edits:

- `uv sync`: passed with CPython 3.11.14; `uv.lock` retained.
- `uv run pytest -q`: 18 passed.
- `uv run ruff check .`: passed.
- All 44 InfluxDB field names, both tag names, measurement, timestamp mapping,
  and all three CLI flags matched the tests and README.
- `main.py` contained no function or class definitions.
- The tracked `imaq-secret` gitlink used the common Sinclair submodule URL;
  credential contents were not inspected.

The suite covers direct settings loading, all protocol field groups, truncated
and wrong-header frames, timestamps, record mapping, optional pressure,
credential isolation, direct read/write behavior, immediate reconnect/retry,
cumulative lifetime failure handling, cycle-start timing, writer failure, and
cleanup.

## Last live read-only evidence - 2026-08-28

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
credential file was opened, and nothing was uploaded to InfluxDB.

## Not validated

- The current dirty measurement/template candidate has no live evidence.
- InfluxDB upload requires explicit authorization and has not been run.
- Continuous live polling has not been run.
- Supervisor deployment has not been activated or checked on a selected host.

