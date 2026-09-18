# py-seas-sip-power demo

From the repository root, run `uv sync --group notebook`. Open `demo.ipynb`
in VS Code and select this repository's `.venv` Python interpreter.
The notebook reads the existing root `settings.toml` and imports the shared
`saes_sip_power_client.py`; there is no separate package or duplicated driver.

Run cells individually: connect, read, Start + 10 polling samples, Stop + read,
close. Start/Stop change pump HV output. Keepalive is not changed; while HV is
started remotely, keep polling through the same client within the configured
interval. Closing the connection alone does not stop HV.

The notebook deliberately has no exception handling or input validation.
