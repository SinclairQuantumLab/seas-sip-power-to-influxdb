"""Test the direct relay script, schema, policy, and cleanup offline."""

from __future__ import annotations

import runpy
import signal
import sys
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import influxdb_client
import pytest

import saes_sip_power_client as source_module
from saes_sip_power_client import SAESSIPPowerSettings, SourceSample

SCRIPT_PATH = Path(__file__).with_name("main.py")


def sample(*, pressure_torr: float | None = 1e-9) -> SourceSample:
    """Build one deterministic normalized controller snapshot."""

    return SourceSample(
        observed_at=datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
        serial_number=123456,
        has_ethernet=True,
        has_display=True,
        hardware_revision="1.2",
        software_version="3.4",
        output_current_na=20,
        output_voltage_v=5000,
        input_voltage_v=24.0,
        internal_temperature_k=300,
        arcing_events=2,
        total_working_time_h=100,
        uptime_s=200,
        enabled=True,
        need_restart=False,
        output_current_gradient="HOLD",
        global_alarm=False,
        safe_alarm=False,
        interlock_alarm=False,
        over_temperature_alarm=False,
        input_voltage_alarm=False,
        output_over_voltage_alarm=False,
        output_over_current_alarm=False,
        arcing_alarm=False,
        communication_alarm=False,
        switch_1_on=True,
        switch_2_on=False,
        switch_3_on=True,
        output_voltage_setpoint_v=5000,
        output_voltage_ramp_interval_ms=1000,
        switch_1_mode="SIMPLE",
        switch_2_mode="WINDOW",
        switch_3_mode="OFF",
        switch_1_threshold_na=1,
        switch_2_min_threshold_na=2,
        switch_2_max_threshold_na=3,
        switch_3_min_threshold_na=4,
        switch_3_max_threshold_na=5,
        keepalive_interval_ms=0,
        conversion_rate_a_per_torr=20,
        modbus_id=11,
        ip_address="192.168.50.34",
        ip_netmask="255.255.255.0",
        mac_address="00:11:22:AA:BB:CC",
        output_power_w=0.0001,
        pressure_torr=pressure_torr,
    )


def write_settings(
    tmp_path: Path,
    *,
    interval_s: float = 10,
    port: int | None = None,
) -> Path:
    """Write one synthetic deployment settings file for a script test."""

    settings_path = tmp_path / "settings.toml"
    port_line = "" if port is None else f"port = {port}\n"
    settings_path.write_text(
        f"""
interval_s = {interval_s}
host = "192.168.50.34"
{port_line}timeout_s = 3
""".strip(),
        encoding="utf-8",
    )
    return settings_path


def write_auth(tmp_path: Path) -> Path:
    """Write synthetic nonsecret InfluxDB destination values."""

    auth_path = tmp_path / "imaq-secret" / "auth.toml"
    auth_path.parent.mkdir()
    auth_path.write_text(
        """
[influxdb]
url = "http://influxdb.example:8086"
token = "<SYNTHETIC_TEST_TOKEN>"
org = "lab"
bucket = "devices"
""".strip(),
        encoding="utf-8",
    )
    return auth_path


class FakeClient:
    """Provide ordered source outcomes to one direct-script execution.

    The fake accepts normalized samples or exceptions, returns them in order,
    and exposes connection, reconnection, and cleanup counters to the tests. It
    owns no external resource, performs no I/O, and is used synchronously by a
    single script execution. An optional callback advances deterministic time.
    """

    def __init__(
        self,
        outcomes: list[SourceSample | Exception],
        *,
        on_read: Callable[[], None] | None = None,
    ) -> None:
        """Store queued results and initialize lifecycle counters."""

        self.outcomes = outcomes
        self.on_read = on_read
        self.connected = False
        self.connect_count = 0
        self.reconnect_count = 0
        self.close_count = 0

    @property
    def is_connected(self) -> bool:
        """Report whether the fake currently represents an open connection."""

        return self.connected

    def connect(self) -> None:
        """Record initial connection acquisition."""

        self.connected = True
        self.connect_count += 1

    def reconnect(self) -> None:
        """Record one stale-connection replacement."""

        self.connected = True
        self.reconnect_count += 1

    def read_sample(self) -> SourceSample:
        """Return or raise the next queued source outcome."""

        if self.on_read is not None:
            self.on_read()
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def close(self) -> None:
        """Record resource release and clear connection state."""

        self.connected = False
        self.close_count += 1


class FakeWriteAPI:
    """Capture records sent through the synchronous InfluxDB write boundary.

    Each write preserves its bucket, organization, and record list for schema
    assertions, or raises a configured failure for cleanup testing. The fake
    performs no network I/O, is used by one script execution, and records when
    its owned write resource is closed.
    """

    def __init__(self, *, fail: bool = False) -> None:
        """Select write behavior and initialize captured state."""

        self.fail = fail
        self.writes: list[tuple[str, str, list[dict[str, object]]]] = []
        self.close_count = 0

    def write(
        self,
        *,
        bucket: str,
        org: str,
        record: list[dict[str, object]],
    ) -> None:
        """Capture one cycle or raise the configured failure."""

        if self.fail:
            raise RuntimeError("write failed")
        self.writes.append((bucket, org, record))

    def close(self) -> None:
        """Record write-API cleanup."""

        self.close_count += 1


class FakeInfluxClient:
    """Model the InfluxDB client resource owned by the relay script.

    The fake receives already narrowed client options, returns one supplied
    synchronous write API, and exposes cleanup state. It validates no account
    data, opens no network connection, and is owned by one script execution
    until the direct top-level cleanup block closes it.
    """

    def __init__(self, write_api: FakeWriteAPI, options: dict[str, str]) -> None:
        """Store supplied state and initialize the close counter."""

        self.api = write_api
        self.options = options
        self.close_count = 0

    def write_api(self, *, write_options: object) -> FakeWriteAPI:
        """Return the supplied synchronous write API."""

        assert write_options is not None
        return self.api

    def close(self) -> None:
        """Record InfluxDB client cleanup."""

        self.close_count += 1


class FakeStopEvent:
    """Control a continuous script run without real sleeping or signals.

    The fake shares a deterministic monotonic clock, records requested wait
    durations, advances time by each wait, and reports stopped after a selected
    count. Tests use it synchronously in place of ``threading.Event``; it owns
    no resource and retains its timing observations after the script exits.
    """

    def __init__(self, clock: list[float], *, stop_after_waits: int) -> None:
        """Store the shared clock and allowed wait count."""

        self.clock = clock
        self.stop_after_waits = stop_after_waits
        self.waits: list[float] = []
        self.requested = False

    def set(self) -> None:
        """Record an explicit signal-driven stop request."""

        self.requested = True

    def is_set(self) -> bool:
        """Report an explicit stop or exhausted wait allowance."""

        return self.requested or len(self.waits) >= self.stop_after_waits

    def wait(self, timeout: float | None = None) -> bool:
        """Record a wait and advance the deterministic clock."""

        assert timeout is not None
        self.waits.append(timeout)
        self.clock[0] += timeout
        return self.is_set()


def use_fake_source(
    monkeypatch: pytest.MonkeyPatch, client: FakeClient
) -> list[SAESSIPPowerSettings]:
    """Replace source construction and return captured typed settings."""

    captured: list[SAESSIPPowerSettings] = []

    def source_factory(settings: SAESSIPPowerSettings) -> FakeClient:
        """Capture source settings and return the selected fake client."""

        captured.append(settings)
        return client

    monkeypatch.setattr(source_module, "SAESSIPPowerClient", source_factory)
    return captured


def run_script(
    monkeypatch: pytest.MonkeyPatch, arguments: list[str]
) -> tuple[int, dict[str, object]]:
    """Execute the production file as a script and capture its exit result."""

    monkeypatch.setattr(sys, "argv", [str(SCRIPT_PATH), *arguments])
    monkeypatch.setattr(signal, "signal", lambda _number, _handler: None)
    try:
        namespace: dict[str, object] = runpy.run_path(
            str(SCRIPT_PATH), run_name="__main__"
        )
    except SystemExit as error:
        assert isinstance(error.code, int)
        return error.code, {}
    return 0, namespace


def test_direct_script_help_preserves_cli(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Expose the three documented options from the direct script parser."""

    exit_code, _namespace = run_script(monkeypatch, ["--help"])

    help_text = capsys.readouterr().out
    assert exit_code == 0
    assert "--settings" in help_text
    assert "--once" in help_text
    assert "--dry-run" in help_text


def test_direct_script_maps_complete_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Map identity, every field group, and acquisition time without drift."""

    settings_path = write_settings(tmp_path)
    write_auth(tmp_path)
    monkeypatch.chdir(tmp_path)
    source_client = FakeClient([sample()])
    write_api = FakeWriteAPI()
    created: list[FakeInfluxClient] = []
    use_fake_source(monkeypatch, source_client)

    def influx_factory(**options: str) -> FakeInfluxClient:
        """Create and retain one fake InfluxDB client."""

        client = FakeInfluxClient(write_api, options)
        created.append(client)
        return client

    monkeypatch.setattr(influxdb_client, "InfluxDBClient", influx_factory)

    exit_code, _namespace = run_script(
        monkeypatch, ["--settings", str(settings_path), "--once"]
    )

    assert exit_code == 0
    bucket, org, records = write_api.writes[0]
    record = records[0]
    fields = record["fields"]
    assert (bucket, org) == ("devices", "lab")
    assert created[0].options == {
        "url": "http://influxdb.example:8086",
        "token": "<SYNTHETIC_TEST_TOKEN>",
        "org": "lab",
        "bucket": "devices",
    }
    assert record["measurement"] == "SAESSIPPower"
    assert record["tags"] == {
        "source": "SAES SIP POWER",
        "Serial number": "123456",
    }
    assert isinstance(fields, dict)
    assert fields["OutputCurrent[nA]"] == 20
    assert fields["InputVoltage[V]"] == 24.0
    assert fields["Enabled"] is True
    assert fields["Switch2Mode"] == "WINDOW"
    assert fields["IPAddress"] == "192.168.50.34"
    assert fields["Pressure[Torr]"] == 1e-9
    assert record["time"] == sample().observed_at
    assert source_client.close_count == 1
    assert write_api.close_count == 1
    assert created[0].close_count == 1


def test_direct_script_omits_unavailable_optional_pressure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Omit unavailable pressure from upload while logging it as ``None``."""

    settings_path = write_settings(tmp_path)
    write_auth(tmp_path)
    monkeypatch.chdir(tmp_path)
    write_api = FakeWriteAPI()
    use_fake_source(monkeypatch, FakeClient([sample(pressure_torr=None)]))

    def influx_factory(**options: str) -> FakeInfluxClient:
        """Create a fake client for the optional-pressure upload."""

        return FakeInfluxClient(write_api, options)

    monkeypatch.setattr(influxdb_client, "InfluxDBClient", influx_factory)

    exit_code, namespace = run_script(
        monkeypatch,
        ["--settings", str(settings_path), "--once"],
    )

    assert exit_code == 0
    fields = namespace["fields"]
    assert isinstance(fields, dict)
    assert "Pressure[Torr]" not in fields
    output = capsys.readouterr().out
    assert (
        "Iteration 1: Uploaded: Pressure[Torr]=None, "
        "OutputCurrent[nA]=20, OutputVoltage[V]=5000, and more."
        in output
    )
    assert "HasEthernet" not in output


def test_direct_script_loads_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Load the local settings directly and construct the source client."""

    settings_path = write_settings(tmp_path, interval_s=30)
    captured = use_fake_source(monkeypatch, FakeClient([sample()]))

    exit_code, namespace = run_script(
        monkeypatch,
        ["--settings", str(settings_path), "--once", "--dry-run"],
    )

    assert exit_code == 0
    assert captured == [SAESSIPPowerSettings("192.168.50.34", 2527, 3.0)]
    assert namespace["INTERVAL_s"] == 30
    assert namespace["MEASUREMENT"] == "SAESSIPPower"
    assert namespace["EX_THRESHOLD"] == 3


def test_dry_run_skips_auth_and_influx_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Read the source path without opening credentials or InfluxDB."""

    settings_path = write_settings(tmp_path)
    client = FakeClient([sample()])
    use_fake_source(monkeypatch, client)

    def fail_influx_client(**_options: str) -> object:
        """Fail if dry-run constructs an InfluxDB client."""

        raise AssertionError("dry-run constructed InfluxDB")

    monkeypatch.setattr(influxdb_client, "InfluxDBClient", fail_influx_client)

    exit_code, _namespace = run_script(
        monkeypatch,
        ["--settings", str(settings_path), "--once", "--dry-run"],
    )

    assert exit_code == 0
    assert "Dry-run record, not uploaded:" in capsys.readouterr().out
    assert client.connect_count == 1
    assert client.close_count == 1


def test_source_failure_reconnects_once_before_one_shot_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replace the socket and retry one failed source read locally."""

    settings_path = write_settings(tmp_path)
    client = FakeClient([TimeoutError("first"), sample()])
    use_fake_source(monkeypatch, client)

    exit_code, _namespace = run_script(
        monkeypatch,
        ["--settings", str(settings_path), "--once", "--dry-run"],
    )

    assert exit_code == 0
    assert client.connect_count == 1
    assert client.reconnect_count == 1
    assert client.close_count == 1


def test_one_shot_unresolved_failure_exits_nonzero_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail one-shot after its local retry and release the source."""

    settings_path = write_settings(tmp_path)
    client = FakeClient([TimeoutError("first"), TimeoutError("retry")])
    use_fake_source(monkeypatch, client)

    exit_code, _namespace = run_script(
        monkeypatch,
        ["--settings", str(settings_path), "--once", "--dry-run"],
    )

    assert exit_code == 1
    assert client.reconnect_count == 1
    assert client.close_count == 1


def test_lifetime_failure_count_does_not_reset_after_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Reach the cumulative threshold despite a successful middle cycle."""

    settings_path = write_settings(tmp_path, interval_s=1)
    client = FakeClient(
        [
            TimeoutError("cycle one"),
            TimeoutError("cycle one retry"),
            sample(),
            TimeoutError("cycle three"),
            RuntimeError("cycle three retry"),
            TimeoutError("cycle four"),
            RuntimeError("cycle four retry"),
        ]
    )
    stop_event = FakeStopEvent([0.0], stop_after_waits=99)
    use_fake_source(monkeypatch, client)
    monkeypatch.setattr(threading, "Event", lambda: stop_event)

    exit_code, _namespace = run_script(
        monkeypatch, ["--settings", str(settings_path), "--dry-run"]
    )

    assert exit_code == 1
    assert "(3/3 lifetime)" in capsys.readouterr().err
    assert client.reconnect_count == 3
    assert client.close_count == 1


def test_scheduler_uses_cycle_start_deadlines_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Subtract work time from waits, avoid overlap, and close the source."""

    settings_path = write_settings(tmp_path, interval_s=10)
    clock = [0.0]
    durations = [2.0, 3.0]

    def advance_work() -> None:
        """Advance the fake clock by the current read duration."""

        clock[0] += durations.pop(0)

    def monotonic() -> float:
        """Return the deterministic monotonic cycle clock."""

        return clock[0]

    client = FakeClient([sample(), sample()], on_read=advance_work)
    stop_event = FakeStopEvent(clock, stop_after_waits=2)
    use_fake_source(monkeypatch, client)
    monkeypatch.setattr(threading, "Event", lambda: stop_event)
    monkeypatch.setattr(time, "monotonic", monotonic)

    exit_code, _namespace = run_script(
        monkeypatch, ["--settings", str(settings_path), "--dry-run"]
    )

    assert exit_code == 0
    assert stop_event.waits == [8.0, 7.0]
    assert client.close_count == 1


def test_write_failure_exits_nonzero_and_closes_every_resource(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Release source, write API, and client after one write failure."""

    settings_path = write_settings(tmp_path)
    write_auth(tmp_path)
    monkeypatch.chdir(tmp_path)
    source_client = FakeClient([sample()])
    write_api = FakeWriteAPI(fail=True)
    created: list[FakeInfluxClient] = []
    use_fake_source(monkeypatch, source_client)

    def influx_factory(**options: str) -> FakeInfluxClient:
        """Create and retain one failing fake InfluxDB client."""

        client = FakeInfluxClient(write_api, options)
        created.append(client)
        return client

    monkeypatch.setattr(influxdb_client, "InfluxDBClient", influx_factory)

    exit_code, _namespace = run_script(
        monkeypatch, ["--settings", str(settings_path), "--once"]
    )

    assert exit_code == 1
    assert source_client.close_count == 1
    assert write_api.close_count == 1
    assert created[0].close_count == 1
