# seas-pump-to-influxdb

`seas-pump-to-influxdb` reads the complete current state of one SAES SIP POWER
ion-pump controller and writes each snapshot to InfluxDB for Grafana. It uses
the controller's Ethernet UDP **Read All** command and is deliberately
read-only: this application cannot start or stop the high-voltage output,
clear alarms, reset the controller, or change any setting.

The supplied configuration targets the controller currently at
`192.168.50.34`. Each sample includes electrical readings, status and alarm
flags, switch state and thresholds, controller settings, firmware identity,
and network information.

> SIP POWER operates an ion pump at hazardous high voltage. This relay does not
> replace the installation, interlock, grounding, or safety instructions in
> `manuals/saes-sip_power-user_manual-rev_4.pdf`. Do not manipulate the high-voltage
> cable or grounding wire while the supply is operating.

## Quick start: first safe reading

### Prerequisites

- Windows or Linux with network reachability to the controller
- UDP traffic to the controller's fixed port 2527 permitted by the host and
  network firewalls
- [uv](https://docs.astral.sh/uv/) and Python 3.11 or newer
- An Ethernet-equipped SAES SIP POWER; the default settings use
  `192.168.50.34:2527`
- InfluxDB 2.x credentials only when upload is enabled; dry-run needs none

Install the locked project environment:

```powershell
uv sync
```

Copy the settings template.

Windows:

```powershell
Copy-Item settings.toml.template settings.toml
```

Linux:

```bash
cp settings.toml.template settings.toml
```

The template already points to `192.168.50.34`. If the controller address is
different, edit `source.host` in `settings.toml`. Then request one real device
snapshot without opening an authentication file or writing to InfluxDB:

```powershell
uv run python main.py --once --dry-run
```

Success produces one timestamped line beginning with `Iteration 1: Dry-run
record, not uploaded:`. The printed record must show the controller's serial
number, `IPAddress`, and current fields. Exit code 0 means the frame was
received, validated, normalized, and mapped to the documented InfluxDB schema.

The command sends only the two-byte Read All request (`01 05`) to the configured
unicast address. It never broadcasts and never sends a controller write or
control command.

## Configuration

`settings.toml` is ignored by Git. All intervals are seconds unless the key
states another unit.

| Setting | Default | Meaning and valid values |
| --- | ---: | --- |
| `measurement` | `SAESSIPPower` | Nonempty InfluxDB measurement name. Changing it is a schema migration. |
| `interval_s` | `30` | Positive interval between cycle start times. |
| `reconnect_delay_s` | `1` | Nonnegative delay before one socket replacement and retry. |
| `exception_threshold` | `3` | Positive cumulative unresolved-failure limit before the process exits nonzero. |
| `auth_path` | `auth.toml` | Authentication file path, resolved relative to `settings.toml`. Dry-run never opens it. |
| `source.host` | `192.168.50.34` | Controller IPv4 address or DNS name. |
| `source.port` | `2527` | UDP port in the range 1-65535. SIP POWER documents 2527 as hard-coded. |
| `source.timeout_s` | `3` | Positive finite timeout for each UDP response. |

The relay supports one controller per process. To collect a second controller,
run a second checkout or service with its own settings, measurement or bucket,
and log paths.

### InfluxDB authentication

For upload, create the ignored file selected by `auth_path`:

```toml
[influxdb]
url = "http://INFLUXDB_HOST:8086"
token = "<INFLUXDB_API_TOKEN>"
org = "REPLACE_WITH_ORG"
bucket = "REPLACE_WITH_BUCKET"
```

Keep this file private. Do not commit it, paste its values into logs, or place
credentials in `settings.toml`. After the dry-run succeeds, an operator who is
authorized to write to that bucket can perform exactly one upload:

```powershell
uv run python main.py --once
```

Success says `Iteration 1: Uploaded` and exits 0. Confirm the point in InfluxDB
before enabling continuous operation.

## Acquisition and recovery behavior

Each cycle requests the controller's current state. The first cycle starts
immediately. Later cycles use monotonic cycle-start deadlines: time spent
reading and writing is subtracted from the wait, cycles never overlap, and an
overrun schedules the next cycle from the current time.

The UDP socket accepts replies only from the configured peer. A source timeout,
socket error, malformed length, wrong protocol version, or wrong response
command causes the relay to wait `reconnect_delay_s`, replace the socket, and
retry the read once. Only an unresolved retry or write failure increments the
lifetime failure count. Successful cycles do not reset that count. At
`exception_threshold`, the process exits nonzero so Supervisor can restart it.

SIP POWER does not include a sample timestamp in Read All. The InfluxDB point
therefore uses the relay host's aware UTC acquisition time immediately after a
valid response arrives. `IOUT`, `VOUT`, and `VIN` are controller values sampled
in the same time slice according to the manual.

SIGINT and SIGTERM request a clean stop. The relay closes the UDP socket and
InfluxDB resources on normal exit, stop, and fatal failure. Ordinary status is
written to stdout; warnings and errors go to stderr for Supervisor capture. No
separate local measurement log is created.

## InfluxDB schema

The default measurement is `SAESSIPPower`.

Tags:

| Tag | Value |
| --- | --- |
| `source` | Constant `SAES SIP POWER` |
| `Serial number` | Decimal controller serial number returned by Read All |

Fields are written with the following exact names and types:

| Field | Type | Meaning / unit |
| --- | --- | --- |
| `HasEthernet` | boolean | Ethernet feature flag |
| `HasDisplay` | boolean | Front-panel display feature flag |
| `HardwareRevision` | string | `major.minor` hardware revision |
| `SoftwareVersion` | string | `major.minor` firmware version |
| `OutputCurrent[nA]` | integer | Ion-pump output current in nA |
| `OutputVoltage[V]` | integer | Ion-pump output voltage in V |
| `InputVoltage[V]` | float | Input voltage converted from the reported dV value |
| `InternalTemperature[K]` | integer | Controller internal temperature in K |
| `ArcingEvents` | integer | Arcing events since the last start or restart |
| `TotalWorkingTime[h]` | integer | Total hours spent supplying current |
| `Uptime[s]` | integer | Seconds since the last start or restart |
| `Enabled` | boolean | High-voltage output enable status |
| `NeedRestart` | boolean | Restart-required status |
| `OutputCurrentGradient` | string | `HOLD`, `UP`, `DOWN`, or `RESERVED` |
| `GlobalAlarm` | boolean | At least one alarm latch is set |
| `SafeAlarm` | boolean | Safety input alarm latch |
| `InterlockAlarm` | boolean | Interlock input alarm latch |
| `OverTemperatureAlarm` | boolean | Internal over-temperature alarm latch |
| `InputVoltageAlarm` | boolean | Input under/over-voltage alarm latch |
| `OutputOverVoltageAlarm` | boolean | Output over-voltage alarm latch |
| `OutputOverCurrentAlarm` | boolean | Output over-current alarm latch |
| `ArcingAlarm` | boolean | Arcing alarm latch |
| `CommunicationAlarm` | boolean | Keepalive communication alarm latch |
| `Switch1On` | boolean | SW1 output state |
| `Switch2On` | boolean | SW2 output state |
| `Switch3On` | boolean | SW3 output state |
| `OutputVoltageSetpoint[V]` | integer | Configured output-voltage set point in V |
| `OutputVoltageRampInterval[ms]` | integer | Configured voltage ramp interval in ms |
| `Switch1Mode` | string | `OFF`, `SIMPLE`, `WINDOW`, or `RESERVED` |
| `Switch2Mode` | string | `OFF`, `SIMPLE`, `WINDOW`, or `RESERVED` |
| `Switch3Mode` | string | `OFF`, `SIMPLE`, `WINDOW`, or `RESERVED` |
| `Switch1Threshold[nA]` | integer | SW1 threshold in nA |
| `Switch2MinThreshold[nA]` | integer | SW2 simple/minimum threshold in nA |
| `Switch2MaxThreshold[nA]` | integer | SW2 maximum threshold in nA |
| `Switch3MinThreshold[nA]` | integer | SW3 simple/minimum threshold in nA |
| `Switch3MaxThreshold[nA]` | integer | SW3 maximum threshold in nA |
| `KeepaliveInterval[ms]` | integer | Configured keepalive interval in ms; zero disables it |
| `ConversionRate[A/Torr]` | integer | Controller conversion-rate value in A/Torr |
| `ModbusID` | integer | Configured Modbus slave ID |
| `IPAddress` | string | Controller IPv4 address returned by Read All |
| `IPNetmask` | string | Controller IPv4 netmask |
| `MACAddress` | string | Uppercase colon-separated controller MAC address |
| `OutputPower[W]` | float | Derived simultaneously sampled `IOUT * VOUT` in W |
| `Pressure[Torr]` | float, optional | `OutputCurrent[nA] * 1e-9 / ConversionRate[A/Torr]`; omitted when conversion rate is zero |

The fields reflect the full non-reserved Read All response. A response with
missing bytes is rejected rather than partially written. Do not rename fields,
tags, or the measurement after dashboards and alerts depend on them.

## Running continuously

The CLI accepts the same options in every mode:

```text
--settings PATH   settings file (default: settings.toml)
--once            process one snapshot and exit
--dry-run         print mapped records without loading auth or writing
```

For an interactive continuous run:

```powershell
uv run python main.py
```

Prepared service wrappers execute the existing `.venv` interpreter directly
and never resolve dependencies during restart.

Windows:

```powershell
.\Startup.ps1
```

Linux:

```bash
./Startup.sh
```

### Supervisor on Linux

Copy `supervisor/linux.conf.template` to `/etc/supervisor/conf.d/` and replace
every `USERNAME` and project path if the checkout is not under
`/home/USERNAME/Projects/seas-pump-to-influxdb`. The template runs
`Startup.sh`, uses the repository as its working directory, restarts only
unexpected exits, and writes:

- `/var/log/supervisor/seas-pump-to-influxdb_out.log`
- `/var/log/supervisor/seas-pump-to-influxdb_err.log`

After reviewing the paths:

```bash
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl status seas-pump-to-influxdb
```

### Supervisor on Windows

Copy and adapt `supervisor/windows.conf.template` for the installed Windows
Supervisor service. It expects the checkout at
`%USERPROFILE%\Projects\seas-pump-to-influxdb`, runs `Startup.ps1`, restarts
only unexpected exits, and writes rotating stdout/stderr logs under the
Supervisor configuration directory's `logs` folder. Verify the expanded
command, project directory, and log paths before starting the program.

## Troubleshooting

`timed out` or `Read All failed`:

- Verify `source.host` and that the PC has a route to the controller subnet.
- Confirm the controller has the Ethernet option and is powered.
- Permit outbound and return UDP traffic on port 2527 in host/network firewalls.
- Do not test with a broadcast address; SIP POWER ignores broadcast Read All.
- Check that another host has not changed the controller IP since settings were
  copied.

`Read All response must be exactly 302 bytes` or an unexpected version/command:

- Confirm the endpoint is a SIP POWER, not another UDP service.
- Retain the error text but do not log or commit raw datagrams.
- Check the controller firmware against the included Rev. 4 manual before
  changing the parser.

Dry-run works but upload fails:

- Confirm `auth_path` resolves relative to the selected settings file.
- Verify `[influxdb]` contains nonempty `url`, `token`, `org`, and `bucket`.
- Check token write permission, organization/bucket spelling, and InfluxDB
  network reachability.
- Dry-run success does not validate InfluxDB credentials.

One expected field is absent:

- Only `Pressure[Torr]` is optional; it is omitted when the controller reports
  a zero conversion rate.
- A disconnected high-voltage cable may legitimately produce
  `OutputCurrent[nA] = 0`, as noted by the vendor manual.
- Alarm booleans are latched controller state; this read-only relay never clears
  them.

## Validation status

On 2026-08-28, the completed app successfully parsed a current 302-byte
version-1 Read All Answer from `192.168.50.34:2527` with `--once --dry-run`.
The record reported the configured controller IP, hardware revision 2.2,
software version 2.0, and a 24.0 V input; no authentication file was opened and
nothing was uploaded. The repository's 27-test offline suite validates parsing,
malformed/missing frames, configuration, schema mapping, optional pressure,
dry-run credential isolation, one reconnect and retry, cumulative failure
threshold, cycle-start timing, and cleanup. InfluxDB upload and Supervisor
deployment still require the operator's credentials, authorization, and
selected deployment host.
