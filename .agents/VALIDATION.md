# SAES SIP POWER validation

Evidence below separates current offline checks, operator-confirmed operation,
and historical live reads. Lack of an agent-run check is not evidence that the
relay is unused.

## Current alignment checks - 2026-09-15

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
