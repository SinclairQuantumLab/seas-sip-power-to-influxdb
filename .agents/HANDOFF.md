# seas-pump-to-influxdb handoff

Last updated: 2026-08-28 (America/Chicago).

## Read first

Read root `AGENTS.md`, then `.agents/DECISIONS.md`, `.agents/VALIDATION.md`, and
`.agents/PROTOCOL.md`. Do not inspect the contents of `imaq-secret`.

## Committed baseline

`HEAD` is `139d9a3 Align README with relay installation style`.

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

The Sinclair relay inventory was refreshed on 2026-08-28 and still contained
nine accessible relay repositories listed by the `to-influxdb-development`
skill. The closest runtime references remain `ULE-Ion-pump-to-influxdb` `main`,
`LFI3751-to-influxdb` `master`, and `nut-to-influxdb` `main` for direct polling
and immediate retry. The concise README shape was adapted from the user's local
HiCube Neo example and checked against `iqair-to-influxdb` `main`.

These references are provenance, not runtime dependencies or universal
templates. Refresh the skill corpus again for a later relay task as instructed
by the skill.

## Current uncommitted worktree: preserve it

Two pre-existing, unstaged changes are present and were not created, completed,
staged, or committed by the handoff-documentation work:

1. `main.py` changes `MEASUREMENT` from committed `SAESSIPPower` to
   `seas-sip-power`.
2. `settings.toml.template` replaces the concrete host with `<HOST>`, moves the
   optional-port explanation beside it, and currently has trailing whitespace
   after the host example.

The ignored local `settings.toml` still contains `host = "192.168.50.34"` and
the earlier comments. It therefore no longer mirrors the edited template's
comment/order shape.

Do not discard or silently finish these changes. Their author and final intent
have not been established in this handoff task.

## Current verification state

Checks run on the dirty worktree on 2026-08-28:

- `uv run pytest -q`: **2 failed, 16 passed**. Both failures are exact
  measurement assertions expecting committed `SAESSIPPower` while current
  `main.py` emits `seas-sip-power`.
- `uv run ruff check .`: passed.
- `git diff --check`: reports trailing whitespace in the edited
  `settings.toml.template` host line.
- README still documents `SAESSIPPower`, so it disagrees with dirty `main.py`.
- No live device read or InfluxDB upload was performed for the dirty state.

These failures are not defects in the last committed baseline; they expose an
unfinished schema-migration candidate in the worktree.

## Decision required before implementation

Determine from the user whether `seas-sip-power` is an intentional measurement
migration. Do not infer intent from the newer general Spinal-Case preference:
the existing measurement is a deployed compatibility surface.

If the rename is intentional, the same migration must deliberately cover tests,
README schema/validation wording, Grafana dashboards, alerts, queries, and
deployment expectations. Record what was migrated and whether existing history
must remain queryable.

If the rename is not intentional, restore only that specific pre-existing diff
after obtaining user direction; do not use a broad reset or overwrite the
settings-template work.

Separately confirm the desired template comments and example host. Keep
`settings.toml.template` and ignored `settings.toml` aligned in structure and
comments while allowing their host values to differ.

## Recommended continuation order

1. Inspect `git status`, the two dirty diffs, and this handoff again.
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
