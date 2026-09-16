# seas-sip-power-to-influxdb

Read one SAES SIP POWER ion-pump controller through its Ethernet UDP interface
and relay each controller-wide snapshot to InfluxDB for Grafana. Device access
is read-only: the app sends Read All but never sends a command that changes the
controller state or settings.

## Requirements

- A powered, Ethernet-equipped SAES SIP POWER reachable from the relay computer
- UDP traffic to the controller's port 2527 permitted by the host and network

## Installation

1. Clone the repository and its credential submodule into the standard project
   directory:

    ```bash
    cd "$HOME/Projects"
    git clone --recurse-submodules https://github.com/SinclairQuantumLab/seas-sip-power-to-influxdb.git
    cd seas-sip-power-to-influxdb
    ```

    > **NOTE**: the `--recurse-submodules` option clones [`imaq-secret`](https://github.com/SinclairQuantumLab/imaq-secret.git) repo for the credential to access to our InfluxDB together at the right location in this repo.

    For an existing checkout cloned without submodules, run:

    ```bash
    git submodule update --init --recursive
    ```

2. Install the project dependencies:

    ```bash
    uv sync
    ```

3. Create and edit a `settings.toml` file from the
   `settings.toml.template` template:

    ```bash
    cp settings.toml.template settings.toml
    ```

    Set `host` to the controller hostname or IP address. `port` is optional and
    defaults to 2527. `interval_s` controls the polling interval, and
    `timeout_s` limits one UDP response wait.

4. Optional: to register the app with Supervisor, use the appropriate template
   in the `supervisor` folder for the operating system.

   When moving an existing checkout to the new repository name, update its
   Git remote and Supervisor command/directory paths to
   `seas-sip-power-to-influxdb`, then run `uv sync` in the new directory.
   The InfluxDB measurement remains `seas-sip-power`.

## Usage

1. Read and print one real snapshot without loading InfluxDB credentials or
   uploading data:

    ```bash
    uv run python main.py --settings settings.toml --once --dry-run
    ```

2. After reviewing the dry-run record, upload one snapshot:

    ```bash
    uv run python main.py --settings settings.toml --once
    ```

    Uploads read `imaq-secret/auth.toml`. Query the new point back and verify its
    schema and timestamp before continuous operation.

3. Run continuously:

    ```bash
    uv run python main.py --settings settings.toml
    ```

The first polling cycle starts immediately. Later cycles use cycle-start
deadlines, so acquisition time is subtracted from the wait. If a source
operation fails, the relay replaces the UDP socket immediately and retries
once. The third unresolved lifetime failure exits the process so Supervisor can
restart it. Successful cycles do not reset that counter.

`Ctrl+C` (SIGINT) and SIGTERM use Python's `signal.default_int_handler`:
they interrupt the current read, upload, or sleep through `KeyboardInterrupt`
and run the existing `finally` cleanup (exit code 130). Shutdown does not wait
for a complete polling cycle. An interrupted upload may already have reached
InfluxDB; it is not retried during shutdown.

Stop a foreground process with `Ctrl+C`. The relay closes its UDP and InfluxDB
clients during normal shutdown and signal handling. Supervisor owns the
continuous-process stdout and stderr logs. Startup wrappers execute the
prepared `.venv` interpreter directly:

- Windows: `Startup.ps1`
- Linux: `Startup.sh`

## Data written to InfluxDB

Each successful Read All response becomes one point with this fixed schema:

| Kind | Exact InfluxDB name | Type or value |
| --- | --- | --- |
| Measurement | `seas-sip-power` | fixed |
| Tag | `source` | `SAES SIP POWER` |
| Tag | `Serial number` | controller serial number |
| Field | `HasEthernet` | boolean |
| Field | `HasDisplay` | boolean |
| Field | `HardwareRevision` | string |
| Field | `SoftwareVersion` | string |
| Field | `OutputCurrent[nA]` | integer |
| Field | `OutputVoltage[V]` | integer |
| Field | `InputVoltage[V]` | float |
| Field | `InternalTemperature[K]` | integer |
| Field | `ArcingEvents` | integer |
| Field | `TotalWorkingTime[h]` | integer |
| Field | `Uptime[s]` | integer |
| Field | `Enabled` | boolean |
| Field | `NeedRestart` | boolean |
| Field | `OutputCurrentGradient` | string |
| Field | `GlobalAlarm` | boolean |
| Field | `SafeAlarm` | boolean |
| Field | `InterlockAlarm` | boolean |
| Field | `OverTemperatureAlarm` | boolean |
| Field | `InputVoltageAlarm` | boolean |
| Field | `OutputOverVoltageAlarm` | boolean |
| Field | `OutputOverCurrentAlarm` | boolean |
| Field | `ArcingAlarm` | boolean |
| Field | `CommunicationAlarm` | boolean |
| Field | `Switch1On` | boolean |
| Field | `Switch2On` | boolean |
| Field | `Switch3On` | boolean |
| Field | `OutputVoltageSetpoint[V]` | integer |
| Field | `OutputVoltageRampInterval[ms]` | integer |
| Field | `Switch1Mode` | string |
| Field | `Switch2Mode` | string |
| Field | `Switch3Mode` | string |
| Field | `Switch1Threshold[nA]` | integer |
| Field | `Switch2MinThreshold[nA]` | integer |
| Field | `Switch2MaxThreshold[nA]` | integer |
| Field | `Switch3MinThreshold[nA]` | integer |
| Field | `Switch3MaxThreshold[nA]` | integer |
| Field | `KeepaliveInterval[ms]` | integer |
| Field | `ConversionRate[A/Torr]` | integer |
| Field | `ModbusID` | integer |
| Field | `IPAddress` | string |
| Field | `IPNetmask` | string |
| Field | `MACAddress` | string |
| Field | `OutputPower[W]` | float |
| Field | `Pressure[Torr]` | float, optional |

The point timestamp is the relay computer's aware UTC time immediately after a
valid response arrives. `OutputPower[W]` is calculated from the simultaneously
reported output current and voltage. When the controller reports a zero
conversion rate, `Pressure[Torr]` appears as `None` in dry-run output and logs
and is omitted from the InfluxDB point. A truncated or malformed response
rejects the whole snapshot instead of writing a partial point.

## Troubleshooting

- If reads time out, verify `host`, the route to the controller subnet, and UDP
  port 2527 in the host and network firewalls. Increase `timeout_s` if needed;
  changing `interval_s` does not change request timeouts.
- If a response has the wrong length, version, or command, confirm the endpoint
  is a SIP POWER and check its firmware against the included Rev. 4 manual.
- If uploads fail, run `git submodule update --init --recursive`, verify the
  private InfluxDB configuration, and return to `--once --dry-run` to isolate
  controller access from InfluxDB.
- If `Pressure[Torr]` is absent, the controller reported a zero conversion
  rate. Other fields are required.
- If Supervisor cannot start the app, run `Startup.ps1` or `Startup.sh`
  manually and inspect Supervisor's stderr log.

## Validation status

On 2026-09-15, the operator confirmed that real data is being uploaded to
`seas-sip-power`. Tests and documentation now use that operational name.

The latest recorded read-only device check was on 2026-08-28 against
`192.168.50.34:2527`: a 302-byte response for serial 25040035 was parsed
successfully. That check used the former measurement name `SAESSIPPower`.

All 18 offline tests and Ruff passed on 2026-09-15. The tests cover protocol
parsing, malformed responses, schema mapping, optional pressure, dry-run
credential isolation, reconnect and retry, cumulative failure handling,
timing, and cleanup. This documentation update did not perform a new live
device check, query stored InfluxDB data, or verify Supervisor deployment.

## Developer's note

- `saes_sip_power_client.py` owns the Ethernet connection, Read All protocol,
  response parsing, and normalized sample.
- `main.py` owns polling, the fixed InfluxDB schema, upload, failure accounting,
  signals, and cleanup.
- Protocol details come from
  `device-docs/saes-sip_power-user_manual-rev_4.pdf`. The app sends only the
  two-byte Read All request (`01 05`) to the configured unicast address; it does
  not broadcast or send controller write commands.
- Offline tests live in `.agents/`; run `uv run pytest -q` and
  `uv run ruff check .` from the repository root.
