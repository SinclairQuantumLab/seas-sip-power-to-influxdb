# seas-pump-to-influxdb Agent Instructions

## Goal

Maintain a sync snapshot relay from SAES SIP Power to InfluxDB without
changing its documented Grafana schema accidentally.

## File ownership

- `saes_sip_power_client.py` is the source of truth for discovery, connection,
  protocol parsing, and normalized samples.
- `main.py` is the source of truth for settings, acquisition policy, InfluxDB
  record names, failure accounting, CLI behavior, signals, and cleanup.
- `README.md` is the self-contained user manual for introduction, first use,
  configuration, operation, schema interpretation, deployment, and
  troubleshooting. It is not the developer architecture guide.
- Startup wrappers execute the prepared `.venv` interpreter and must not run
  dependency resolution during a restart.

## Working rules

- Use plain `uv sync` for dependency installation and updates so it can refresh
  `uv.lock`. Do not routinely replace it with `uv lock`, `uv sync --locked`
  (or `uv sync --lock`), `uv sync --frozen`, or similar lock-preserving
  commands; an exceptional constraint must be concrete and reported.
- Add precise parameter, return, attribute, callback, and collection type hints
  wherever Python can express the contract. Narrow untyped SDK or configuration
  values before they enter application logic instead of propagating `Any`.
- Give every Python module, class, function, and method a useful docstring,
  including tests and private helpers. Reusable clients, collectors, writers,
  protocols, and similar library classes need detailed class docstrings covering
  responsibility, inputs and outputs, state, failure behavior, concurrency, and
  resource lifecycle as applicable; do not merely restate the class name.
- Keep deployer values in ignored `settings.toml` and credentials in the private
  `imaq-secret` submodule. Never print or commit credential values.
- Make `git clone --recurse-submodules ...` the README's primary installation
  path whenever `imaq-secret` is tracked. Document the exact recovery command
  `git submodule update --init --recursive` separately for an existing
  nonrecursive checkout.
- Keep source-facing attributes in `snake_case` and map them to documented,
  human-readable InfluxDB names only in `main.py`.
- Preserve measurement, tag, field, timestamp, and CLI compatibility unless a
  migration is explicitly requested.
- Update README in the same change whenever commands, settings or defaults,
  schema names or types, timestamp semantics, acquisition or recovery behavior,
  credential location, startup wrappers, or Supervisor paths change.
- Keep README user-centered and self-contained. Preserve useful user-authored
  wording, warnings, comments, field notes, representative output, and section
  shape when modernizing it; make the smallest visible change that restores
  accuracy and usability.
- Do not put contributor setup, implementation TODOs, internal architecture, or
  test/lint instructions in the user journey. If README genuinely needs them,
  put them at the end under the exact heading `## Developer's note`.
- Treat other Sinclair READMEs as source-specific examples, not a fixed template.
  Do not shorten required source installation or troubleshooting detail merely
  to make repositories look uniform.
- One unresolved source failure receives one reconnect and retry. Lifetime
  failures do not reset after success and raise at the configured threshold.
- Selected multi-device mode: false. Local measurement logging is not enabled or
  implemented; Supervisor owns stdout/stderr logs. Protocol notes are enabled.

## Verification

Run offline tests and Ruff before live access. Run `--once --dry-run` before one
authorized upload. State when hardware, network, account, or InfluxDB checks were
not available instead of treating historical results as current evidence. Read
the finished README from a new user's perspective and verify its commands,
settings, schema, paths, filenames, and success criteria against the repository.
