"""Poll SAES SIP POWER snapshots and relay them to InfluxDB."""

from __future__ import annotations

import argparse
import math
import signal
import threading
import time
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import Protocol

import influxdb_client
from influxdb_client.client.write_api import SYNCHRONOUS

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


class SourceClient(Protocol):
    """Define the single-source lifecycle used by the snapshot collector.

    Implementations connect on demand, return one or more normalized samples,
    replace stale communication state on ``reconnect``, and release resources
    idempotently. Calls are synchronous and the collector never invokes them
    concurrently.
    """

    @property
    def is_connected(self) -> bool:
        """Report whether a source resource is currently owned."""

        ...

    def connect(self) -> None:
        """Prepare source communication."""

        ...

    def reconnect(self) -> None:
        """Replace stale source communication state."""

        ...

    def read_samples(self) -> list[SourceSample]:
        """Read one current snapshot cycle."""

        ...

    def close(self) -> None:
        """Release source resources idempotently."""

        ...


class RecordWriter(Protocol):
    """Define the synchronous record-write and cleanup boundary.

    Implementations own any InfluxDB resources they create. ``write`` returns
    whether records were uploaded, allowing dry-run to share collector logic,
    and ``close`` must be idempotent.
    """

    def write(self, records: Sequence[Mapping[str, object]]) -> bool:
        """Write one complete cycle and report whether it was uploaded."""

        ...

    def close(self) -> None:
        """Release writer-owned resources idempotently."""

        ...


class StopEvent(Protocol):
    """Describe the shutdown event boundary used by the polling scheduler.

    Implementations expose synchronous state inspection and a timed wait. The
    collector owns neither event creation nor signal registration and may reuse
    one event for its entire single-threaded lifecycle.
    """

    def is_set(self) -> bool:
        """Report whether shutdown was requested."""

        ...

    def wait(self, timeout: float | None = None) -> bool:
        """Wait up to a timeout and report whether the event became set."""

        ...


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


class InfluxDBWriter:
    """Synchronously write complete cycles through one InfluxDB client.

    The writer owns the client and synchronous write API created from ``config``.
    A successful ``write`` means the API call returned without an exception;
    errors propagate to collector failure accounting. ``close`` is idempotent
    and releases both write API and client resources. Calls are blocking and
    concurrent use is unsupported.

    Args:
        config: Validated client options, organization, and bucket.
    """

    def __init__(self, config: InfluxConfig) -> None:
        """Create the owned client and synchronous write API."""

        self._client = influxdb_client.InfluxDBClient(**config.client_options)
        self._write_api = self._client.write_api(write_options=SYNCHRONOUS)
        self.org = config.org
        self.bucket = config.bucket
        self._closed = False

    def write(self, records: Sequence[Mapping[str, object]]) -> bool:
        """Upload one complete record sequence or propagate the write error."""

        self._write_api.write(bucket=self.bucket, org=self.org, record=list(records))
        return True

    def close(self) -> None:
        """Close the owned write API and InfluxDB client idempotently."""

        if self._closed:
            return
        self._closed = True
        try:
            self._write_api.close()
        finally:
            self._client.close()


class DryRunWriter:
    """Exercise record construction without credentials or network writes.

    The writer owns no external resource. ``write`` deliberately returns false
    so collector output identifies the records as dry-run data, and ``close`` is
    an idempotent no-op.
    """

    def write(self, records: Sequence[Mapping[str, object]]) -> bool:
        """Accept validated records while reporting that no upload occurred."""

        return False

    def close(self) -> None:
        """Complete cleanup without touching an external resource."""

        return None


class SnapshotCollector:
    """Schedule snapshot reads, recovery, mapping, writes, and cleanup.

    The collector owns the supplied source client and writer for its full
    lifecycle. It prevents overlapping cycles, reconnects and retries one failed
    source read locally, and counts only unresolved cycle failures against a
    lifetime threshold that success never resets. ``run`` closes both resources
    on normal return, stop signals, and fatal exceptions. One collector is meant
    for one thread; callers must not invoke cycles concurrently.

    Args:
        settings: Validated scheduling, recovery, source, and credential settings.
        client: Connected-on-demand source adapter owned by this collector.
        writer: Upload or dry-run writer owned by this collector.
        sleep: Injectable reconnect delay function.
        monotonic: Injectable monotonic cycle clock.
    """

    def __init__(
        self,
        settings: AppSettings,
        client: SourceClient,
        writer: RecordWriter,
        *,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Store owned collaborators and initialize lifetime failure state."""

        self.settings = settings
        self.client = client
        self.writer = writer
        self.sleep = sleep
        self.monotonic = monotonic
        self.lifetime_exception_count = 0

    def _read_with_recovery(self) -> list[SourceSample]:
        """Read samples, replacing the connection before one local retry."""

        try:
            if not self.client.is_connected:
                self.client.connect()
            return self.client.read_samples()
        except Exception as first_error:
            log_warn(
                "Source read failed; reconnecting before one retry: "
                f"{type(first_error).__name__}: {first_error}"
            )
        if self.settings.reconnect_delay_s:
            self.sleep(self.settings.reconnect_delay_s)
        self.client.reconnect()
        return self.client.read_samples()

    def poll_once(self, iteration: int) -> list[InfluxRecord]:
        """Read, map, and write one non-overlapping snapshot cycle."""

        samples = self._read_with_recovery()
        if not samples:
            raise EmptySampleError("source returned no samples")
        records = [
            build_influx_record(sample, measurement=self.settings.measurement)
            for sample in samples
        ]
        uploaded = self.writer.write(records)
        verb = "Uploaded" if uploaded else "Dry-run record, not uploaded:"
        log(f"Iteration {iteration}: {verb} {records!r}")
        return records

    def run_cycle(self, iteration: int) -> bool:
        """Run one recoverable cycle and enforce the lifetime threshold."""

        try:
            self.poll_once(iteration)
            return True
        except Exception as error:
            self.lifetime_exception_count += 1
            count = self.lifetime_exception_count
            threshold = self.settings.exception_threshold
            log_error(
                f"Iteration {iteration} failed ({count}/{threshold} lifetime): "
                f"{type(error).__name__}: {error}"
            )
            if count >= threshold:
                raise
            return False

    def run(self, *, once: bool, stop_event: StopEvent) -> None:
        """Run once or on monotonic cycle-start deadlines until stopped."""

        try:
            if once:
                self.poll_once(1)
                return
            next_poll = self.monotonic()
            iteration = 1
            while not stop_event.is_set():
                self.run_cycle(iteration)
                iteration += 1
                next_poll += self.settings.interval_s
                now = self.monotonic()
                if next_poll <= now:
                    next_poll = now + self.settings.interval_s
                stop_event.wait(next_poll - now)
        finally:
            self.close()

    def close(self) -> None:
        """Close the source client and writer even if source cleanup fails."""

        try:
            self.client.close()
        finally:
            self.writer.close()


def build_parser() -> argparse.ArgumentParser:
    """Build the stable command-line interface for the relay."""

    parser = argparse.ArgumentParser(description="Relay SAES SIP POWER to InfluxDB")
    parser.add_argument("--settings", type=Path, default=DEFAULT_SETTINGS_PATH)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the relay and translate configuration or runtime failures to exits."""

    args = build_parser().parse_args(argv)
    try:
        settings = load_settings(args.settings)
        writer: RecordWriter = (
            DryRunWriter()
            if args.dry_run
            else InfluxDBWriter(load_influx_config(settings.auth_path))
        )
    except (OSError, TypeError, ValueError, tomllib.TOMLDecodeError) as error:
        log_error(f"Configuration error: {type(error).__name__}: {error}")
        return 2

    client = SAESSIPPowerClient(settings.source)
    collector = SnapshotCollector(settings, client, writer)
    stop_event = threading.Event()

    def request_stop(_signum: int, _frame: FrameType | None) -> None:
        """Translate SIGINT or SIGTERM into a graceful collector stop."""

        stop_event.set()

    for signal_number in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signal_number, request_stop)
    try:
        collector.run(once=args.once, stop_event=stop_event)
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        log_error(f"Fatal collector error: {type(error).__name__}: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
