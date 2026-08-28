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

print()
print("----- SAES SIP POWER ion pump controller -> InfluxDB uploader -----")
print()


# >>>>> app configuration >>>>>

# >>> load & parse config files >>>
PARSER = argparse.ArgumentParser(description="Relay SAES SIP POWER to InfluxDB")
PARSER.add_argument("--settings", type=Path, default=Path("settings.toml"))
PARSER.add_argument("--once", action="store_true")
PARSER.add_argument("--dry-run", action="store_true")
ARGS = PARSER.parse_args()

try:
    SETTINGS_PATH = ARGS.settings.expanduser().resolve()
    with SETTINGS_PATH.open("rb") as f:
        SETTINGS: dict[str, object] = tomllib.load(f)

    MEASUREMENT_value = SETTINGS.get("measurement")
    if not isinstance(MEASUREMENT_value, str) or not MEASUREMENT_value.strip():
        raise ValueError("settings.measurement must be a nonempty string")
    MEASUREMENT = MEASUREMENT_value.strip()

    INTERVAL_value = SETTINGS.get("interval_s")
    if isinstance(INTERVAL_value, bool) or not isinstance(
        INTERVAL_value, (int, float)
    ):
        raise TypeError("settings.interval_s must be a number")
    INTERVAL_s = float(INTERVAL_value)
    if not math.isfinite(INTERVAL_s) or INTERVAL_s <= 0:
        raise ValueError("settings.interval_s must be finite and positive")

    RECONNECT_DELAY_value = SETTINGS.get("reconnect_delay_s")
    if isinstance(RECONNECT_DELAY_value, bool) or not isinstance(
        RECONNECT_DELAY_value, (int, float)
    ):
        raise TypeError("settings.reconnect_delay_s must be a number")
    RECONNECT_DELAY_s = float(RECONNECT_DELAY_value)
    if not math.isfinite(RECONNECT_DELAY_s) or RECONNECT_DELAY_s < 0:
        raise ValueError("settings.reconnect_delay_s must be finite and nonnegative")

    EX_THRESHOLD_value = SETTINGS.get("exception_threshold")
    if (
        isinstance(EX_THRESHOLD_value, bool)
        or not isinstance(EX_THRESHOLD_value, int)
        or EX_THRESHOLD_value <= 0
    ):
        raise ValueError("settings.exception_threshold must be a positive integer")
    EX_THRESHOLD = EX_THRESHOLD_value

    AUTH_PATH_value = SETTINGS.get("auth_path", "imaq-secret/auth.toml")
    if not isinstance(AUTH_PATH_value, str) or not AUTH_PATH_value.strip():
        raise ValueError("settings.auth_path must be a nonempty path string")
    AUTH_PATH = Path(AUTH_PATH_value).expanduser()
    if not AUTH_PATH.is_absolute():
        AUTH_PATH = SETTINGS_PATH.parent / AUTH_PATH
    AUTH_PATH = AUTH_PATH.resolve()

    SOURCE_values = SETTINGS.get("source")
    if not isinstance(SOURCE_values, dict):
        raise TypeError("settings must contain a [source] table")
    SOURCE_SETTINGS = SAESSIPPowerSettings.from_mapping(SOURCE_values)
except (OSError, TypeError, ValueError, tomllib.TOMLDecodeError) as ex:
    log_error(f"Configuration error: {type(ex).__name__}: {ex}")
    raise SystemExit(2) from ex
# <<< load & parse config files <<<

print(
    f"Polling interval = {INTERVAL_s} s, "
    f"exception threshold = {EX_THRESHOLD}."
)
print(
    f"SAES SIP POWER controller = "
    f"{SOURCE_SETTINGS.host}:{SOURCE_SETTINGS.port}."
)
print(f"Settings file = {SETTINGS_PATH}.")
print(f"InfluxDB upload = {'disabled (dry-run)' if ARGS.dry_run else 'enabled'}.")
print()

# <<<<< app configuration <<<<<


# >>> load IMAQ secret >>>
AUTH: dict[str, object] | None = None
if not ARGS.dry_run:
    try:
        with AUTH_PATH.open("rb") as f:
            AUTH = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as ex:
        log_error(f"IMAQ secret error: {type(ex).__name__}: {ex}")
        raise SystemExit(2) from ex
# <<< load IMAQ secret <<<


STOP_EVENT = threading.Event()
for SIGNAL_NUMBER in (signal.SIGINT, signal.SIGTERM):
    signal.signal(SIGNAL_NUMBER, lambda _signum, _frame: STOP_EVENT.set())


# >>> InfluxDB configuration >>>
INFLUXDB_CONFIG: dict[str, str] | None = None
INFLUXDB_ORG: str | None = None
INFLUXDB_BUCKET: str | None = None

if AUTH is not None:
    try:
        INFLUXDB_values = AUTH.get("influxdb")
        if not isinstance(INFLUXDB_values, dict):
            raise TypeError("IMAQ secret must contain an [influxdb] table")

        INFLUXDB_URL_value = INFLUXDB_values.get("url")
        INFLUXDB_TOKEN_value = INFLUXDB_values.get("token")
        INFLUXDB_ORG_value = INFLUXDB_values.get("org")
        INFLUXDB_BUCKET_value = INFLUXDB_values.get("bucket")
        for key, value in (
            ("url", INFLUXDB_URL_value),
            ("token", INFLUXDB_TOKEN_value),
            ("org", INFLUXDB_ORG_value),
            ("bucket", INFLUXDB_BUCKET_value),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"influxdb.{key} must be a nonempty string")

        assert isinstance(INFLUXDB_URL_value, str)
        assert isinstance(INFLUXDB_TOKEN_value, str)
        assert isinstance(INFLUXDB_ORG_value, str)
        assert isinstance(INFLUXDB_BUCKET_value, str)
        INFLUXDB_ORG = INFLUXDB_ORG_value.strip()
        INFLUXDB_BUCKET = INFLUXDB_BUCKET_value.strip()
        INFLUXDB_CONFIG = {
            "url": INFLUXDB_URL_value.strip(),
            "token": INFLUXDB_TOKEN_value.strip(),
            "org": INFLUXDB_ORG,
        }
    except (TypeError, ValueError) as ex:
        log_error(f"InfluxDB configuration error: {type(ex).__name__}: {ex}")
        raise SystemExit(2) from ex

INFLUXDB_CLIENT: influxdb_client.InfluxDBClient | None = None
INFLUXDB_WRITE_API: WriteApi | None = None

try:
    if INFLUXDB_CONFIG is not None:
        # Initialize the InfluxDB Client and the Write API.
        INFLUXDB_CLIENT = influxdb_client.InfluxDBClient(**INFLUXDB_CONFIG)
        INFLUXDB_WRITE_API = INFLUXDB_CLIENT.write_api(write_options=SYNCHRONOUS)
        print(
            f"InfluxDB client initialized for org='{INFLUXDB_ORG}', "
            f"bucket='{INFLUXDB_BUCKET}'."
        )
        print()
except Exception as ex:
    log_error(f"InfluxDB initialization error: {type(ex).__name__}: {ex}")
    try:
        if INFLUXDB_WRITE_API is not None:
            INFLUXDB_WRITE_API.close()
    finally:
        if INFLUXDB_CLIENT is not None:
            INFLUXDB_CLIENT.close()
    raise SystemExit(1) from ex
# <<< InfluxDB configuration <<<


# >>> SAES SIP POWER connection >>>
SIP_POWER_CLIENT = SAESSIPPowerClient(SOURCE_SETTINGS)
# <<< SAES SIP POWER connection <<<


exit_code = 0
try:
    lifetime_exception_count = 0
    iteration = 1
    next_poll = time.monotonic()

    print("Entering main polling loop...")
    print()

    while not STOP_EVENT.is_set():
        msg_il = f"Iteration {iteration}: "

        try:
            # >>>>> query readings >>>>>

            # One unresolved source failure receives one reconnect and retry.
            try:
                if not SIP_POWER_CLIENT.is_connected:
                    SIP_POWER_CLIENT.connect()
                sample = SIP_POWER_CLIENT.read_sample()
            except Exception as ex:
                log_error(msg_il)
                log_error(
                    f"SAES SIP POWER query failed: {type(ex).__name__}: {ex}"
                )
                log_warn(
                    "Re-establishing SAES SIP POWER connection and retrying once..."
                )
                if RECONNECT_DELAY_s:
                    time.sleep(RECONNECT_DELAY_s)
                SIP_POWER_CLIENT.reconnect()
                log_warn("SAES SIP POWER reconnection succeeded.")
                sample = SIP_POWER_CLIENT.read_sample()

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
                "measurement": MEASUREMENT,
                "tags": {
                    "source": "SAES SIP POWER",
                    "Serial number": sample.device_id,
                },
                "fields": fields,
                "time": sample.observed_at,
            }
            influxdb_records = [influxdb_record]

            # <<<<< query readings <<<<<

            if INFLUXDB_WRITE_API is None:
                log(msg_il + f"Dry-run record, not uploaded: {influxdb_records!r}")
            else:
                assert INFLUXDB_BUCKET is not None
                assert INFLUXDB_ORG is not None
                INFLUXDB_WRITE_API.write(
                    bucket=INFLUXDB_BUCKET,
                    org=INFLUXDB_ORG,
                    record=influxdb_records,
                )
                log(msg_il + f"Uploaded {influxdb_records!r}")
        except Exception as ex:
            # A one-shot command has no later cycle in which to recover.
            if ARGS.once:
                raise
            lifetime_exception_count += 1
            log_error(msg_il)
            log_error(
                "Error during measurement/upload "
                f"({lifetime_exception_count}/{EX_THRESHOLD} lifetime): "
                f"{type(ex).__name__}: {ex}"
            )
            if lifetime_exception_count >= EX_THRESHOLD:
                log_error("Exception threshold reached. Raising to supervisor.")
                raise

        if ARGS.once:
            break

        # Cycle-start deadlines avoid adding acquisition time to every period.
        iteration += 1
        next_poll += INTERVAL_s
        now = time.monotonic()
        if next_poll <= now:
            next_poll = now + INTERVAL_s
        STOP_EVENT.wait(next_poll - now)
except KeyboardInterrupt:
    log_warn("KeyboardInterrupt received.")
    exit_code = 130
except Exception as ex:
    log_error(f"Fatal collector error: {type(ex).__name__}: {ex}")
    exit_code = 1
finally:
    log("Shutting down gracefully...", end=" ")
    try:
        SIP_POWER_CLIENT.close()
    except Exception as ex:
        log_warn(f"SAES SIP POWER cleanup failed: {type(ex).__name__}: {ex}")
    try:
        if INFLUXDB_WRITE_API is not None:
            INFLUXDB_WRITE_API.close()
    except Exception as ex:
        log_warn(f"InfluxDB write API cleanup failed: {type(ex).__name__}: {ex}")
    try:
        if INFLUXDB_CLIENT is not None:
            INFLUXDB_CLIENT.close()
    except Exception as ex:
        log_warn(f"InfluxDB client cleanup failed: {type(ex).__name__}: {ex}")
    print("Done")

if exit_code:
    raise SystemExit(exit_code)
