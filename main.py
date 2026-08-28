"""Poll SAES SIP POWER snapshots and relay them to InfluxDB."""

from __future__ import annotations

import argparse
import math
import signal
import threading
import time
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import FrameType

import influxdb_client
from influxdb_client.client.write_api import SYNCHRONOUS, WriteApi

from saes_sip_power_client import (
    SAESSIPPowerClient,
    SAESSIPPowerSettings,
    SourceSample,
)
from supervisor.supervisor_helper import log, log_error, log_warn

DEFAULT_SETTINGS_PATH = Path("settings.toml")
DEFAULT_AUTH_PATH = Path("auth.toml")
FieldValue = bool | int | float | str
InfluxRecord = dict[str, object]


class EmptySampleError(ValueError):
    """Raised when a normalized sample has no writable fields."""


@dataclass(frozen=True)
class AppSettings:
    """Hold validated collector, source, and credential settings.

    Paths are absolute and resolved relative to the selected settings file.
    Numeric values have already passed type, finiteness, and range validation.
    """

    measurement: str
    interval_s: float
    reconnect_delay_s: float
    exception_threshold: int
    auth_path: Path
    source: SAESSIPPowerSettings


@dataclass(frozen=True)
class InfluxConfig:
    """Hold authenticated InfluxDB client options and write destination."""

    client_options: dict[str, str]
    org: str
    bucket: str


def _number(values: Mapping[str, object], key: str, *, positive: bool) -> float:
    """Read one finite numeric setting and enforce its allowed sign."""

    value = values.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"settings.{key} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"settings.{key} must be finite")
    if (positive and number <= 0) or (not positive and number < 0):
        qualifier = "positive" if positive else "nonnegative"
        raise ValueError(f"settings.{key} must be {qualifier}")
    return number


def load_settings(path: str | Path) -> AppSettings:
    """Load and validate application settings without reading credentials."""

    settings_path = Path(path).expanduser().resolve()
    with settings_path.open("rb") as file:
        values: dict[str, object] = tomllib.load(file)
    measurement = values.get("measurement")
    if not isinstance(measurement, str) or not measurement.strip():
        raise ValueError("settings.measurement must be a nonempty string")
    threshold = values.get("exception_threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, int) or threshold <= 0:
        raise ValueError("settings.exception_threshold must be a positive integer")
    source_values = values.get("source")
    if not isinstance(source_values, dict):
        raise TypeError("settings must contain a [source] table")
    auth_value = values.get("auth_path", str(DEFAULT_AUTH_PATH))
    if not isinstance(auth_value, str) or not auth_value.strip():
        raise ValueError("settings.auth_path must be a nonempty path string")
    auth_path = Path(auth_value).expanduser()
    if not auth_path.is_absolute():
        auth_path = settings_path.parent / auth_path
    return AppSettings(
        measurement=measurement.strip(),
        interval_s=_number(values, "interval_s", positive=True),
        reconnect_delay_s=_number(values, "reconnect_delay_s", positive=False),
        exception_threshold=threshold,
        auth_path=auth_path.resolve(),
        source=SAESSIPPowerSettings.from_mapping(source_values),
    )


def load_influx_config(path: str | Path) -> InfluxConfig:
    """Load validated InfluxDB credentials and destination metadata."""

    with Path(path).open("rb") as file:
        values: dict[str, object] = tomllib.load(file)
    table = values.get("influxdb")
    if not isinstance(table, dict):
        raise TypeError("auth file must contain an [influxdb] table")
    required: dict[str, str] = {}
    for key in ("url", "token", "org", "bucket"):
        value = table.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"influxdb.{key} must be a nonempty string")
        required[key] = value.strip()
    options = {
        "url": required["url"],
        "token": required["token"],
        "org": required["org"],
    }
    return InfluxConfig(options, org=required["org"], bucket=required["bucket"])


def build_influx_record(sample: SourceSample, *, measurement: str) -> InfluxRecord:
    """Map one normalized snapshot to the stable Grafana-facing schema."""

    if sample.observed_at.utcoffset() is None:
        raise ValueError("sample.observed_at must be timezone-aware")
    fields: dict[str, FieldValue] = {
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
        "OutputVoltageRampInterval[ms]": sample.output_voltage_ramp_interval_ms,
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
    if not fields:
        raise EmptySampleError("sample contains no writable fields")
    return {
        "measurement": measurement,
        "tags": {"source": "SAES SIP POWER", "Serial number": sample.device_id},
        "fields": fields,
        "time": sample.observed_at,
    }


def build_parser() -> argparse.ArgumentParser:
    """Build the stable command-line interface for the relay."""

    parser = argparse.ArgumentParser(description="Relay SAES SIP POWER to InfluxDB")
    parser.add_argument("--settings", type=Path, default=DEFAULT_SETTINGS_PATH)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the sequential snapshot loop and translate failures to exit codes."""

    args = build_parser().parse_args(argv)

    # Dry-run stops at the real source boundary and deliberately never opens auth.
    try:
        settings = load_settings(args.settings)
        influx_config = (
            None if args.dry_run else load_influx_config(settings.auth_path)
        )
    except (OSError, TypeError, ValueError, tomllib.TOMLDecodeError) as error:
        log_error(f"Configuration error: {type(error).__name__}: {error}")
        return 2

    stop_event = threading.Event()

    def request_stop(_signum: int, _frame: FrameType | None) -> None:
        """Translate SIGINT or SIGTERM into a graceful loop stop."""

        stop_event.set()

    for signal_number in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signal_number, request_stop)

    source_client = SAESSIPPowerClient(settings.source)
    influx_client: influxdb_client.InfluxDBClient | None = None
    write_api: WriteApi | None = None

    try:
        if influx_config is not None:
            influx_client = influxdb_client.InfluxDBClient(
                **influx_config.client_options
            )
            write_api = influx_client.write_api(write_options=SYNCHRONOUS)

        lifetime_exception_count = 0
        iteration = 1
        next_poll = time.monotonic()

        while not stop_event.is_set():
            try:
                # One source failure gets one fresh socket and one local retry.
                try:
                    if not source_client.is_connected:
                        source_client.connect()
                    sample = source_client.read_sample()
                except Exception as first_error:
                    log_warn(
                        "Source read failed; reconnecting before one retry: "
                        f"{type(first_error).__name__}: {first_error}"
                    )
                    if settings.reconnect_delay_s:
                        time.sleep(settings.reconnect_delay_s)
                    source_client.reconnect()
                    sample = source_client.read_sample()

                record = build_influx_record(
                    sample, measurement=settings.measurement
                )
                records = [record]

                if write_api is None:
                    uploaded = False
                else:
                    write_api.write(
                        bucket=influx_config.bucket,
                        org=influx_config.org,
                        record=records,
                    )
                    uploaded = True

                verb = "Uploaded" if uploaded else "Dry-run record, not uploaded:"
                log(f"Iteration {iteration}: {verb} {records!r}")
            except Exception as error:
                # A one-shot command has no later cycle in which to recover.
                if args.once:
                    raise
                lifetime_exception_count += 1
                log_error(
                    f"Iteration {iteration} failed "
                    f"({lifetime_exception_count}/{settings.exception_threshold} "
                    f"lifetime): {type(error).__name__}: {error}"
                )
                if lifetime_exception_count >= settings.exception_threshold:
                    raise

            if args.once:
                break

            # Schedule from cycle-start deadlines; work time reduces the wait.
            iteration += 1
            next_poll += settings.interval_s
            now = time.monotonic()
            if next_poll <= now:
                next_poll = now + settings.interval_s
            stop_event.wait(next_poll - now)
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        log_error(f"Fatal collector error: {type(error).__name__}: {error}")
        return 1
    finally:
        try:
            source_client.close()
        finally:
            try:
                if write_api is not None:
                    write_api.close()
            finally:
                if influx_client is not None:
                    influx_client.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
