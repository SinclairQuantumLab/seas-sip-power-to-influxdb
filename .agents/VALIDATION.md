# SAES SIP POWER validation

## Current live checks - 2026-08-28

Environment: Windows host on the controller LAN, endpoint
`192.168.50.34:2527`, America/Chicago.

1. A PowerShell UDP transport probe sent one documented read-only Read All
   header with a 3-second receive timeout. Result: response peer
   `192.168.50.34:2527`, length 302, version 1, command 128.
2. The finished direct top-level script ran after removal of application helper
   functions and `main()`, and after alignment with the Sinclair family section
   comments and `imaq-secret` path:

   ```text
   uv run python main.py --settings settings.toml.template --once --dry-run
   ```

   Result: exit 0 and one normalized `SAESSIPPower` record for serial 25040035.
   Representative checks were hardware 2.2, software 2.0, input 24.0 V,
   internal temperature 302 K, and returned IP 192.168.50.34. The output was
   disabled and the Safe/Interlock alarm latches were true at that instant.
   The command did not open credentials or write to InfluxDB.

No raw response frame was retained and no controller state was changed.

## Offline and structural checks - 2026-08-28

- `uv sync`: passed with CPython 3.11.14; `uv.lock` retained.
- `uv run pytest -q`: 18 passed.
- `uv run ruff check .`: all checks passed.
- `audit_relay.py . --strict`: all enforced findings passed; no WARN or ERROR.
- Baseline/current AST comparison: all 45 InfluxDB field/tag-to-sample mappings
  and all three CLI flags were identical. The finished `main.py` contains no
  function or class definitions.
- Sinclair family style check: application configuration, IMAQ secret,
  InfluxDB configuration, source connection, and query sections use the common
  paired comment markers. The tracked `imaq-secret` gitlink uses the common
  Sinclair submodule URL; credential contents were not inspected.

The suite executes `main.py` as a script and covers direct settings loading,
source framing and every field group, truncated and wrong-header frames,
timestamps, record mapping, optional pressure, credential isolation, the direct
read/write path, reconnect/retry, cumulative lifetime threshold, cycle-start
timing, writer failure, and cleanup. Input-value validation tests were removed
with the validation layer; the script trusts the local deployer-controlled TOML
in the same style as the comparable Sinclair relays.

## Not run

- InfluxDB upload: requires the authorized `imaq-secret/auth.toml` submodule
  content and explicit operator authorization.
- Continuous live polling: one current dry-run cycle was sufficient for the
  read path; service operation was not started.
- Supervisor deployment: no deployment host has been selected.
