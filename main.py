"""Poll one SAES SIP POWER and relay each read-only snapshot to InfluxDB."""

from __future__ import annotations

import argparse
import signal
import threading
import time
import tomllib
from pathlib import Path

import influxdb_client
from influxdb_client.client.write_api import SYNCHRONOUS

from saes_sip_power_client import (
    DEFAULT_PORT,
    SAESSIPPowerClient,
    SAESSIPPowerSettings,
)
from supervisor.supervisor_helper import log, log_error, log_warn

print()
print("----- SAES SIP POWER ion pump controller -> InfluxDB uploader -----")
print()


# >>>>> app configuration >>>>>

MEASUREMENT = "seas-sip-power"
EX_THRESHOLD = 3

# >>> load & parse config files >>>
PARSER = argparse.ArgumentParser(description="Relay SAES SIP POWER to InfluxDB")
PARSER.add_argument("--settings", type=Path, default=Path("settings.toml"))
PARSER.add_argument("--once", action="store_true")
PARSER.add_argument("--dry-run", action="store_true")
ARGS = PARSER.parse_args()

SETTINGS_PATH = ARGS.settings.expanduser().resolve()
with SETTINGS_PATH.open("rb") as f:
    SETTINGS = tomllib.load(f)

INTERVAL_s = SETTINGS["interval_s"]
SOURCE_SETTINGS = SAESSIPPowerSettings(
    host=SETTINGS["host"],
    port=SETTINGS.get("port", DEFAULT_PORT),
    timeout_s=SETTINGS["timeout_s"],
)
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
if not ARGS.dry_run:
    with open("imaq-secret/auth.toml", "rb") as f:
        AUTH = tomllib.load(f)
# <<< load IMAQ secret <<<


STOP_EVENT = threading.Event()
for SIGNAL_NUMBER in (signal.SIGINT, signal.SIGTERM):
    signal.signal(SIGNAL_NUMBER, lambda _signum, _frame: STOP_EVENT.set())


# >>> InfluxDB configuration >>>
INFLUXDB_CLIENT = None
INFLUXDB_WRITE_API = None
INFLUXDB_ORG = None
INFLUXDB_BUCKET = None

if not ARGS.dry_run:
    INFLUXDB_CLIENT = influxdb_client.InfluxDBClient(**AUTH["influxdb"])
    INFLUXDB_WRITE_API = INFLUXDB_CLIENT.write_api(write_options=SYNCHRONOUS)
    INFLUXDB_ORG = AUTH["influxdb"]["org"]
    INFLUXDB_BUCKET = AUTH["influxdb"]["bucket"]
    print(
        f"InfluxDB client initialized for org='{INFLUXDB_ORG}', "
        f"bucket='{INFLUXDB_BUCKET}'."
    )
    print()
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
                SIP_POWER_CLIENT.reconnect()
                log_warn("SAES SIP POWER reconnection succeeded.")
                sample = SIP_POWER_CLIENT.read_sample()

            fields = {
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
                "Pressure[Torr]": sample.pressure_torr,
            }

            influxdb_record = {
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

            if ARGS.dry_run:
                log(msg_il + f"Dry-run record, not uploaded: {influxdb_records!r}")
            else:
                INFLUXDB_WRITE_API.write(
                    bucket=INFLUXDB_BUCKET,
                    org=INFLUXDB_ORG,
                    record=influxdb_records,
                )
                log(
                    f"{msg_il}Uploaded: "
                    f"Pressure[Torr]={fields['Pressure[Torr]']!r}, "
                    f"OutputCurrent[nA]={fields['OutputCurrent[nA]']!r}, "
                    f"OutputVoltage[V]={fields['OutputVoltage[V]']!r}, and more."
                )
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
