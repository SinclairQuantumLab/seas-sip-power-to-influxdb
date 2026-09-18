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
  baseline. Library commit `b4dc57d` contains only those two additions and is
  published before this relay's gitlink update. The old relay-level
  `device-docs/` directory is gone.
- `main.py`, application tests, schema, polling and upload policy remain here.
  Parent pytest and Ruff checks exclude the library. Its README owns demo setup
  and usage instructions; avoid duplicating those instructions in this repo.
- The separate Codex thread `Developing py-seas-sip-power` uses the library
  directory. Its local identifiers are in ignored
  `.agents/local/library-thread.json`.

## Library work in progress

At cleanup time the library worktree contains separate staged/unstaged changes
for Jupytext, access modes and the expanded remote interface. This cleanup
preserves those changes. Consult the library's current handoff for their status;
the relay's recorded gitlink, rather than a dirty editable checkout, defines
the reproducible dependency version. Publish intended library changes before
updating that gitlink and validate the relay against the selected revision.

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
Cleanup passed all 16 relay tests and Ruff in an isolated checkout using library
`b4dc57d`, without consuming the concurrent library development changes.
Historical test counts describe their corresponding revisions, not the current
suite. The last agent-recorded live read was on 2026-08-28; the user's
2026-09-15 upload confirmation is separate operator evidence. This cleanup
performs no hardware access, InfluxDB query/upload or service restart.

The settings template's pre-existing trailing whitespace and comment-layout
difference from local settings are unrelated to the library split and remain.

## Reference provenance

This cleanup follows the ownership boundary established by extraction commit
`6acf938`; it introduces no new runtime convention. The skill-source preflight
reported `current-dirty`, ahead 0 / behind 0 of
`origin/feature/to-influxdb-development`; existing skill changes were preserved.
The refreshed organization inventory has 15 nonempty, unarchived relay
repositories (LFI3751 uses `master`, the others `main`). Earlier comparative
evidence remains in `TAKEOVER-2026-09-15.md` and the skill's repository corpus.
