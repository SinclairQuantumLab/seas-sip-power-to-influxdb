"""Poll one SAES SIP POWER and relay each read-only snapshot to InfluxDB."""

from __future__ import annotations

import argparse
import math
import signal
import threading
import time
import tomllib
from pathlib import Path

import influxdb_client
from influxdb_client.client.write_api import SYNCHRONOUS, WriteApi

from saes_sip_power_client import SAESSIPPowerClient, SAESSIPPowerSettings
from supervisor.supervisor_helper import log, log_error, log_warn

parser = argparse.ArgumentParser(description="Relay SAES SIP POWER to InfluxDB")
parser.add_argument("--settings", type=Path, default=Path("settings.toml"))
parser.add_argument("--once", action="store_true")
parser.add_argument("--dry-run", action="store_true")
arguments = parser.parse_args()


# Load and narrow application settings before opening either external system.
try:
    settings_path = arguments.settings.expanduser().resolve()
    with settings_path.open("rb") as settings_file:
        settings_values: dict[str, object] = tomllib.load(settings_file)

    measurement_value = settings_values.get("measurement")
    if not isinstance(measurement_value, str) or not measurement_value.strip():
        raise ValueError("settings.measurement must be a nonempty string")
    measurement = measurement_value.strip()

    interval_value = settings_values.get("interval_s")
    if isinstance(interval_value, bool) or not isinstance(
        interval_value, (int, float)
    ):
        raise TypeError("settings.interval_s must be a number")
    interval_s = float(interval_value)
    if not math.isfinite(interval_s) or interval_s <= 0:
        raise ValueError("settings.interval_s must be finite and positive")

    reconnect_delay_value = settings_values.get("reconnect_delay_s")
    if isinstance(reconnect_delay_value, bool) or not isinstance(
        reconnect_delay_value, (int, float)
    ):
        raise TypeError("settings.reconnect_delay_s must be a number")
    reconnect_delay_s = float(reconnect_delay_value)
    if not math.isfinite(reconnect_delay_s) or reconnect_delay_s < 0:
        raise ValueError("settings.reconnect_delay_s must be finite and nonnegative")

    exception_threshold_value = settings_values.get("exception_threshold")
    if (
        isinstance(exception_threshold_value, bool)
        or not isinstance(exception_threshold_value, int)
        or exception_threshold_value <= 0
    ):
        raise ValueError("settings.exception_threshold must be a positive integer")
    exception_threshold = exception_threshold_value

    auth_path_value = settings_values.get("auth_path", "auth.toml")
    if not isinstance(auth_path_value, str) or not auth_path_value.strip():
        raise ValueError("settings.auth_path must be a nonempty path string")
    auth_path = Path(auth_path_value).expanduser()
    if not auth_path.is_absolute():
        auth_path = settings_path.parent / auth_path
    auth_path = auth_path.resolve()

    source_values = settings_values.get("source")
    if not isinstance(source_values, dict):
        raise TypeError("settings must contain a [source] table")
    source_settings = SAESSIPPowerSettings.from_mapping(source_values)

    influx_options: dict[str, str] | None = None
    influx_org: str | None = None
    influx_bucket: str | None = None

    # A dry-run deliberately stops credential access at this boundary.
    if not arguments.dry_run:
        with auth_path.open("rb") as auth_file:
            auth_values: dict[str, object] = tomllib.load(auth_file)
        influx_values = auth_values.get("influxdb")
        if not isinstance(influx_values, dict):
            raise TypeError("auth file must contain an [influxdb] table")

        influx_url_value = influx_values.get("url")
        influx_token_value = influx_values.get("token")
        influx_org_value = influx_values.get("org")
        influx_bucket_value = influx_values.get("bucket")
        for key, value in (
            ("url", influx_url_value),
            ("token", influx_token_value),
            ("org", influx_org_value),
            ("bucket", influx_bucket_value),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"influxdb.{key} must be a nonempty string")

        # The checks above narrow these four values to nonempty strings.
        assert isinstance(influx_url_value, str)
        assert isinstance(influx_token_value, str)
        assert isinstance(influx_org_value, str)
        assert isinstance(influx_bucket_value, str)
        influx_org = influx_org_value.strip()
        influx_bucket = influx_bucket_value.strip()
        influx_options = {
            "url": influx_url_value.strip(),
            "token": influx_token_value.strip(),
            "org": influx_org,
        }
except (OSError, TypeError, ValueError, tomllib.TOMLDecodeError) as error:
    log_error(f"Configuration error: {type(error).__name__}: {error}")
    raise SystemExit(2) from error


print()
print("----- SAES SIP POWER -> InfluxDB relay -----")
print()
print(f"Controller: {source_settings.host}:{source_settings.port}")
print(f"Polling interval: {interval_s} s")
print(f"Exception threshold: {exception_threshold} lifetime failures")
print(f"InfluxDB upload: {'disabled (dry-run)' if arguments.dry_run else 'enabled'}")
print()


stop_event = threading.Event()
for signal_number in (signal.SIGINT, signal.SIGTERM):
    signal.signal(signal_number, lambda _signum, _frame: stop_event.set())

source_client = SAESSIPPowerClient(source_settings)
influx_client: influxdb_client.InfluxDBClient | None = None
write_api: WriteApi | None = None
exit_code = 0

try:
    if influx_options is not None:
        influx_client = influxdb_client.InfluxDBClient(**influx_options)
        write_api = influx_client.write_api(write_options=SYNCHRONOUS)

    lifetime_exception_count = 0
    iteration = 1
    next_poll = time.monotonic()

    while not stop_event.is_set():
        try:
            # One unresolved source failure receives one reconnect and retry.
            try:
                if not source_client.is_connected:
                    source_client.connect()
                sample = source_client.read_sample()
            except Exception as first_error:
                log_warn(
                    "Source read failed; reconnecting before one retry: "
                    f"{type(first_error).__name__}: {first_error}"
                )
                if reconnect_delay_s:
                    time.sleep(reconnect_delay_s)
                source_client.reconnect()
                sample = source_client.read_sample()

            if sample.observed_at.utcoffset() is None:
                raise ValueError("sample.observed_at must be timezone-aware")

            fields: dict[str, bool | int | float | str] = {
                "HasEthernet": sample.has_ethernet,
                "HasDisplay": sample.has_display,
                "HardwareRevision": sample.hardware_revision,
                "SoftwareVersion": sample.software_version,
                "OutputCurrent[nA]": sample.output_current_na,
                "OutputVoltage[V]": sample.output_voltage_v,
                "InputVoltage[V]": sample.input_voltage_v,
                "InternalTemperature[K]": sample.internal_temperature_k,
                "ArcingEvents": sample.arcing_events,
                "TotalWorkingTime[h]": sample.total_working_time_h,
                "Uptime[s]": sample.uptime_s,
                "Enabled": sample.enabled,
                "NeedRestart": sample.need_restart,
                "OutputCurrentGradient": sample.output_current_gradient,
                "GlobalAlarm": sample.global_alarm,
                "SafeAlarm": sample.safe_alarm,
                "InterlockAlarm": sample.interlock_alarm,
                "OverTemperatureAlarm": sample.over_temperature_alarm,
                "InputVoltageAlarm": sample.input_voltage_alarm,
                "OutputOverVoltageAlarm": sample.output_over_voltage_alarm,
                "OutputOverCurrentAlarm": sample.output_over_current_alarm,
                "ArcingAlarm": sample.arcing_alarm,
                "CommunicationAlarm": sample.communication_alarm,
                "Switch1On": sample.switch_1_on,
                "Switch2On": sample.switch_2_on,
                "Switch3On": sample.switch_3_on,
                "OutputVoltageSetpoint[V]": sample.output_voltage_setpoint_v,
                "OutputVoltageRampInterval[ms]": (
                    sample.output_voltage_ramp_interval_ms
                ),
                "Switch1Mode": sample.switch_1_mode,
                "Switch2Mode": sample.switch_2_mode,
                "Switch3Mode": sample.switch_3_mode,
                "Switch1Threshold[nA]": sample.switch_1_threshold_na,
                "Switch2MinThreshold[nA]": sample.switch_2_min_threshold_na,
                "Switch2MaxThreshold[nA]": sample.switch_2_max_threshold_na,
                "Switch3MinThreshold[nA]": sample.switch_3_min_threshold_na,
                "Switch3MaxThreshold[nA]": sample.switch_3_max_threshold_na,
                "KeepaliveInterval[ms]": sample.keepalive_interval_ms,
                "ConversionRate[A/Torr]": sample.conversion_rate_a_per_torr,
                "ModbusID": sample.modbus_id,
                "IPAddress": sample.ip_address,
                "IPNetmask": sample.ip_netmask,
                "MACAddress": sample.mac_address,
                "OutputPower[W]": sample.output_power_w,
            }
            if sample.pressure_torr is not None:
                fields["Pressure[Torr]"] = sample.pressure_torr

            influxdb_record: dict[str, object] = {
                "measurement": measurement,
                "tags": {
                    "source": "SAES SIP POWER",
                    "Serial number": sample.device_id,
                },
                "fields": fields,
                "time": sample.observed_at,
            }
            influxdb_records = [influxdb_record]

            if write_api is None:
                log(
                    f"Iteration {iteration}: Dry-run record, not uploaded: "
                    f"{influxdb_records!r}"
                )
            else:
                assert influx_bucket is not None
                assert influx_org is not None
                write_api.write(
                    bucket=influx_bucket,
                    org=influx_org,
                    record=influxdb_records,
                )
                log(f"Iteration {iteration}: Uploaded {influxdb_records!r}")
        except Exception as error:
            # A one-shot command has no later cycle in which to recover.
            if arguments.once:
                raise
            lifetime_exception_count += 1
            log_error(
                f"Iteration {iteration} failed "
                f"({lifetime_exception_count}/{exception_threshold} lifetime): "
                f"{type(error).__name__}: {error}"
            )
            if lifetime_exception_count >= exception_threshold:
                raise

        if arguments.once:
            break

        # Cycle-start deadlines avoid adding acquisition time to every period.
        iteration += 1
        next_poll += interval_s
        now = time.monotonic()
        if next_poll <= now:
            next_poll = now + interval_s
        stop_event.wait(next_poll - now)
except KeyboardInterrupt:
    exit_code = 130
except Exception as error:
    log_error(f"Fatal collector error: {type(error).__name__}: {error}")
    exit_code = 1
finally:
    try:
        source_client.close()
    except Exception as error:
        log_warn(f"Source cleanup failed: {type(error).__name__}: {error}")
    try:
        if write_api is not None:
            write_api.close()
    except Exception as error:
        log_warn(f"InfluxDB write API cleanup failed: {type(error).__name__}: {error}")
    try:
        if influx_client is not None:
            influx_client.close()
    except Exception as error:
        log_warn(f"InfluxDB client cleanup failed: {type(error).__name__}: {error}")

if exit_code:
    raise SystemExit(exit_code)
