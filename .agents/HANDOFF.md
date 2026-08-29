# seas-pump-to-influxdb handoff

Last updated: 2026-08-28 (America/Chicago).

## Read first

Read root `AGENTS.md`, then `.agents/DECISIONS.md`, `.agents/VALIDATION.md`, and
`.agents/PROTOCOL.md`. Do not inspect the contents of `imaq-secret`.

## Current repository state

Measurement/configuration state was introduced by `625cbe5 Refactor handoff
documentation and update measurement name to 'seas-sip-power'`. Later
documentation and upload-log commits may be above it; use
`git log -5 --oneline` for the exact current HEAD.

That commit was created by another actor while the handoff-documentation task
was in progress. It combined the agent-document changes with the measurement
rename and settings-template edits that had previously been unstaged. The
working tree was clean immediately after that commit. Do not amend, reset, or
rewrite it merely to separate those concerns.

Current application/configuration state:

- `main.py` emits measurement `seas-sip-power`.
- Tests and README still expect/document `SAESSIPPower`.
- A successful upload log shows only `Pressure[Torr]`, `OutputCurrent[nA]`,
  `OutputVoltage[V]`, and `and more.` in that order. The local record always
  contains optional pressure, using `None` when unavailable; the pinned
  InfluxDB client omits that field from line protocol, while logs and dry-run
  display the `None` value.
- `settings.toml.template` uses `<HOST>` and an inline host example, with
  trailing whitespace after that example.
- Ignored local `settings.toml` still uses `192.168.50.34` and the earlier
  comment layout.
- Tests fail because the measurement migration is incomplete; current HEAD is
  not ready for upload or deployment.

## Last fully verified baseline

`139d9a3 Align README with relay installation style` is the last fully verified
baseline.

At that commit the repository is a completed read-only, synchronous snapshot
relay for one SAES SIP POWER over Ethernet UDP:

- `main.py` is a direct top-level script with no application functions,
  orchestration helpers, classes, or `main()` wrapper.
- `saes_sip_power_client.py` is the reusable stateful UDP/protocol boundary.
- Flat settings contain `interval_s`, `host`, optional `port`, and `timeout_s`.
- Omitted port defaults to 2527.
- Measurement is fixed as `SAESSIPPower`; the hard-coded lifetime exception
  threshold is three; reconnect and one retry are immediate.
- `--settings`, `--once`, and `--dry-run` are supported.
- The README follows the concise numbered installation/usage style requested by
  the user and documents all 44 fields.
- The common private `imaq-secret` repository is tracked as a submodule.

The last clean baseline passed 18 tests and Ruff. A real read-only dry-run
against `192.168.50.34:2527` also succeeded on 2026-08-28. Details and evidence
boundaries are in `.agents/VALIDATION.md`.

## Reference provenance

The Sinclair relay inventory was refreshed on 2026-08-28 and contained ten
accessible reference relays plus this target. The closest runtime references
remain
`ULE-Ion-pump-to-influxdb` `main`, `LFI3751-to-influxdb` `master`, and
`nut-to-influxdb` `main` for direct polling and immediate retry. ULE also uses
the pressure/current/voltage log order, while NUT establishes that unavailable
selected values may be logged as `None`. The concise README shape was adapted
from `hicube-neo-to-influxdb` `main` and checked against
`iqair-to-influxdb` `main`. HiCube explicitly filters `None` fields before its
upload, while this target deliberately leaves its sole optional value in the
record for the pinned InfluxDB client to omit.

These references are provenance, not runtime dependencies or universal
templates. Refresh the skill corpus again for a later relay task as instructed
by the skill.

## Changes introduced by `625cbe5`

Two application/configuration changes were committed together with the initial
handoff-document refresh:

1. `main.py` changes `MEASUREMENT` from committed `SAESSIPPower` to
   `seas-sip-power`.
2. `settings.toml.template` replaces the concrete host with `<HOST>`, moves the
   optional-port explanation beside it, and currently has trailing whitespace
   after the host example.

The ignored local `settings.toml` still contains `host = "192.168.50.34"` and
the earlier comments. It therefore no longer mirrors the committed template's
comment/order shape.

Do not silently revert or deploy these changes. The commit message supports an
intent to rename the measurement, but the required schema-migration scope was
not completed or validated.

## Current verification state

Checks run against the application/configuration state now committed at
`625cbe5` on 2026-08-28:

- `uv run pytest -q`: **2 failed, 16 passed**. Both failures are exact
  measurement assertions expecting committed `SAESSIPPower` while current
  `main.py` emits `seas-sip-power`.
- The focused optional-pressure/upload-summary test passes and confirms that
  the record retains `Pressure[Torr]=None`, line protocol omits that field, and
  the full record is absent from a successful-upload log.
- `uv run ruff check .`: passed.
- `git diff --check 139d9a3 625cbe5`: reports trailing whitespace in the
  committed `settings.toml.template` host line.
- README still documents `SAESSIPPower`, so it disagrees with current
  `main.py`.
- No live device read or InfluxDB upload was performed for this migrated state.

These failures are not defects in the last committed baseline; they expose an
unfinished schema migration in current HEAD.

## Decision required before implementation

Confirm whether `seas-sip-power` should be completed as an intentional
measurement migration. The commit message suggests that direction, but it does
not by itself authorize affected Grafana/dashboard/history changes. Do not infer
the full migration scope only from the newer general Spinal-Case preference:
the previous measurement is a deployed compatibility surface.

If the rename is intentional, the same migration must deliberately cover tests,
README schema/validation wording, Grafana dashboards, alerts, queries, and
deployment expectations. Record what was migrated and whether existing history
must remain queryable.

If the rename is not intentional, revert it in a new focused commit after
obtaining user direction; do not rewrite `625cbe5`, use a broad reset, or
overwrite the settings-template work.

Separately confirm the desired template comments and example host. Keep
`settings.toml.template` and ignored `settings.toml` aligned in structure and
comments while allowing their host values to differ.

## Recommended continuation order

1. Inspect `git status`, `625cbe5`, and this handoff again.
2. Resolve the measurement-migration intent with the user.
3. Resolve the settings-template comment/placeholder intent without losing the
   existing local controller value.
4. Make the smallest consistent code/test/README/settings change.
5. Run tests, Ruff, scoped `git diff --check`, and schema/command comparison.
6. Run one `--once --dry-run` only after offline checks pass and controller
   access is appropriate.
7. Commit the resolved work as a focused checkpoint, excluding unrelated
   changes.

## External blockers

- No InfluxDB upload has been authorized or performed. Do not inspect or expose
  `imaq-secret/auth.toml`.
- Supervisor has not been activated on a selected deployment host.
- Continuous live polling has not been validated; only one-shot dry-runs have.
