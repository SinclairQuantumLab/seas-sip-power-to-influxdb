"""Test the sequential relay configuration, schema, loop, and cleanup offline."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

import main as relay
from main import build_influx_record, load_influx_config, load_settings
from saes_sip_power_client import SAESSIPPowerSettings, SourceSample


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
    reconnect_delay_s: float = 2,
    exception_threshold: int = 3,
    auth_name: str = "auth.toml",
) -> Path:
    """Write one synthetic deployment settings file for a loop test."""

    settings_path = tmp_path / "settings.toml"
    settings_path.write_text(
        f"""
measurement = "SAESSIPPower"
interval_s = {interval_s}
reconnect_delay_s = {reconnect_delay_s}
exception_threshold = {exception_threshold}
auth_path = "{auth_name}"

[source]
host = "192.168.50.34"
port = 2527
timeout_s = 3
""".strip(),
        encoding="utf-8",
    )
    return settings_path


def write_auth(tmp_path: Path) -> Path:
    """Write nonsecret synthetic InfluxDB destination values for upload tests."""

    auth_path = tmp_path / "auth.toml"
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
    """Provide ordered source outcomes to the sequential main loop.

    Each read returns one queued normalized sample or raises one queued
    exception. Connect, reconnect, and close counters expose lifecycle behavior,
    while an optional callback can advance a deterministic clock. The fake owns
    no external resource and is used synchronously by one test thread.
    """

    def __init__(
        self,
        outcomes: list[SourceSample | Exception],
        *,
        on_read: Callable[[], None] | None = None,
    ) -> None:
        """Store read outcomes and initialize lifecycle counters."""

        self.outcomes = outcomes
        self.on_read = on_read
        self.connected = False
        self.connect_count = 0
        self.reconnect_count = 0
        self.close_count = 0

    @property
    def is_connected(self) -> bool:
        """Report the fake connection state."""

        return self.connected

    def connect(self) -> None:
        """Record initial connection acquisition."""

        self.connected = True
        self.connect_count += 1

    def reconnect(self) -> None:
        """Record stale connection replacement."""

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
    """Capture synchronous writes or raise one selected write failure."""

    def __init__(self, *, fail: bool = False) -> None:
        """Select success or failure and initialize captured writes."""

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
        """Capture one complete cycle or raise the configured failure."""

        if self.fail:
            raise RuntimeError("write failed")
        self.writes.append((bucket, org, record))

    def close(self) -> None:
        """Record write-API cleanup."""

        self.close_count += 1


class FakeInfluxClient:
    """Provide one owned fake write API to the sequential relay.

    The fake records constructor options, returns the supplied synchronous write
    API, and exposes close state without network access. It deliberately does not
    validate credentials or destinations. One main-loop invocation owns it and
    uses it from one thread.
    """

    def __init__(self, write_api: FakeWriteAPI, options: dict[str, str]) -> None:
        """Store the write API and captured client options."""

        self.api = write_api
        self.options = options
        self.close_count = 0

    def write_api(self, *, write_options: object) -> FakeWriteAPI:
        """Return the supplied synchronous write API."""

        assert write_options is relay.SYNCHRONOUS
        return self.api

    def close(self) -> None:
        """Record InfluxDB client cleanup."""

        self.close_count += 1


class FakeStopEvent:
    """Advance a fake monotonic clock and stop after a fixed number of waits."""

    def __init__(self, clock: list[float], *, stop_after_waits: int) -> None:
        """Store the shared clock and the number of waits to allow."""

        self.clock = clock
        self.stop_after_waits = stop_after_waits
        self.waits: list[float] = []
        self.requested = False

    def set(self) -> None:
        """Record an explicit signal-driven stop request."""

        self.requested = True

    def is_set(self) -> bool:
        """Report an explicit stop or the configured wait limit."""

        return self.requested or len(self.waits) >= self.stop_after_waits

    def wait(self, timeout: float | None = None) -> bool:
        """Record the wait and advance the fake clock by its duration."""

        assert timeout is not None
        self.waits.append(timeout)
        self.clock[0] += timeout
        return self.is_set()


def use_fake_source(monkeypatch: pytest.MonkeyPatch, client: FakeClient) -> None:
    """Replace production source construction with one supplied fake client."""

    monkeypatch.setattr(relay, "SAESSIPPowerClient", lambda _settings: client)


def test_build_influx_record_maps_complete_schema() -> None:
    """Map identity, every field group, and acquisition time without drift."""

    record = build_influx_record(sample(), measurement="SAESSIPPower")
    fields = record["fields"]

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


def test_build_influx_record_omits_unavailable_optional_pressure() -> None:
    """Omit rather than fabricate pressure when conversion is unavailable."""

    record = build_influx_record(sample(pressure_torr=None), measurement="test")

    assert "Pressure[Torr]" not in record["fields"]


def test_build_influx_record_rejects_naive_timestamp() -> None:
    """Reject timestamps that cannot unambiguously identify an instant."""

    naive = replace(sample(), observed_at=datetime(2026, 8, 28, 12, 0))

    with pytest.raises(ValueError, match="timezone-aware"):
        build_influx_record(naive, measurement="test")


def test_load_settings_validates_and_resolves_relative_paths(tmp_path: Path) -> None:
    """Load collector and source values without opening the credential file."""

    settings_path = write_settings(tmp_path, interval_s=30, reconnect_delay_s=1)

    settings = load_settings(settings_path)

    assert settings.measurement == "SAESSIPPower"
    assert settings.auth_path == (tmp_path / "auth.toml").resolve()
    assert settings.source == SAESSIPPowerSettings("192.168.50.34", 2527, 3.0)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("interval_s", "true"),
        ("reconnect_delay_s", "-1"),
        ("exception_threshold", "0"),
    ],
)
def test_load_settings_rejects_invalid_collector_numbers(
    tmp_path: Path, key: str, value: str
) -> None:
    """Reject booleans-as-numbers, negative delays, and nonpositive thresholds."""

    values = {
        "interval_s": "30",
        "reconnect_delay_s": "1",
        "exception_threshold": "3",
    }
    values[key] = value
    settings_path = tmp_path / "settings.toml"
    settings_path.write_text(
        f"""
measurement = "test"
interval_s = {values['interval_s']}
reconnect_delay_s = {values['reconnect_delay_s']}
exception_threshold = {values['exception_threshold']}
[source]
host = "controller"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises((TypeError, ValueError)):
        load_settings(settings_path)


def test_load_influx_config_requires_all_destination_values(tmp_path: Path) -> None:
    """Validate credentials and remove the bucket from client constructor options."""

    auth_path = write_auth(tmp_path)

    config = load_influx_config(auth_path)

    assert config.client_options["url"] == "http://influxdb.example:8086"
    assert "bucket" not in config.client_options
    assert (config.org, config.bucket) == ("lab", "devices")


def test_dry_run_skips_auth_and_influx_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Read the real source path without opening credentials or InfluxDB."""

    settings_path = write_settings(tmp_path, auth_name="missing-auth.toml")
    client = FakeClient([sample()])
    use_fake_source(monkeypatch, client)

    def fail_influx_client(**_options: str) -> object:
        """Fail if dry-run constructs an InfluxDB client."""

        raise AssertionError("dry-run constructed InfluxDB")

    monkeypatch.setattr(relay.influxdb_client, "InfluxDBClient", fail_influx_client)

    assert relay.main(["--settings", str(settings_path), "--once", "--dry-run"]) == 0
    assert "Dry-run record, not uploaded:" in capsys.readouterr().out
    assert client.connect_count == 1
    assert client.close_count == 1


def test_source_failure_reconnects_once_before_one_shot_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replace the socket and retry one failed source read locally."""

    settings_path = write_settings(tmp_path, reconnect_delay_s=2)
    client = FakeClient([TimeoutError("first"), sample()])
    delays: list[float] = []
    use_fake_source(monkeypatch, client)
    monkeypatch.setattr(relay.time, "sleep", delays.append)

    assert relay.main(["--settings", str(settings_path), "--once", "--dry-run"]) == 0
    assert client.connect_count == 1
    assert client.reconnect_count == 1
    assert delays == [2.0]
    assert client.close_count == 1


def test_one_shot_unresolved_failure_exits_nonzero_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail one-shot immediately after its local retry and release the source."""

    settings_path = write_settings(tmp_path, reconnect_delay_s=0)
    client = FakeClient([TimeoutError("first"), TimeoutError("retry")])
    use_fake_source(monkeypatch, client)

    assert relay.main(["--settings", str(settings_path), "--once", "--dry-run"]) == 1
    assert client.reconnect_count == 1
    assert client.close_count == 1


def test_lifetime_failure_count_does_not_reset_after_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Reach the cumulative threshold despite a successful middle cycle."""

    settings_path = write_settings(
        tmp_path, interval_s=1, reconnect_delay_s=0, exception_threshold=2
    )
    client = FakeClient(
        [
            TimeoutError("cycle one"),
            TimeoutError("cycle one retry"),
            sample(),
            TimeoutError("cycle three"),
            RuntimeError("cycle three retry"),
        ]
    )
    stop_event = FakeStopEvent([0.0], stop_after_waits=99)
    use_fake_source(monkeypatch, client)
    monkeypatch.setattr(relay.threading, "Event", lambda: stop_event)

    assert relay.main(["--settings", str(settings_path), "--dry-run"]) == 1
    assert "(2/2 lifetime)" in capsys.readouterr().err
    assert client.reconnect_count == 2
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
    monkeypatch.setattr(relay.threading, "Event", lambda: stop_event)
    monkeypatch.setattr(relay.time, "monotonic", monotonic)

    assert relay.main(["--settings", str(settings_path), "--dry-run"]) == 0
    assert stop_event.waits == [8.0, 7.0]
    assert client.close_count == 1


def test_authorized_path_writes_one_record_and_closes_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Write one complete mapped record and close source and Influx resources."""

    settings_path = write_settings(tmp_path)
    write_auth(tmp_path)
    source_client = FakeClient([sample()])
    write_api = FakeWriteAPI()
    created: list[FakeInfluxClient] = []
    use_fake_source(monkeypatch, source_client)

    def influx_factory(**options: str) -> FakeInfluxClient:
        """Create and retain one fake InfluxDB client."""

        client = FakeInfluxClient(write_api, options)
        created.append(client)
        return client

    monkeypatch.setattr(relay.influxdb_client, "InfluxDBClient", influx_factory)

    assert relay.main(["--settings", str(settings_path), "--once"]) == 0
    assert created[0].options["org"] == "lab"
    assert write_api.writes[0][0:2] == ("devices", "lab")
    assert write_api.writes[0][2][0]["measurement"] == "SAESSIPPower"
    assert source_client.close_count == 1
    assert write_api.close_count == 1
    assert created[0].close_count == 1


def test_write_failure_exits_nonzero_and_closes_every_resource(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Release source, write API, and client after one fatal write failure."""

    settings_path = write_settings(tmp_path)
    write_auth(tmp_path)
    source_client = FakeClient([sample()])
    write_api = FakeWriteAPI(fail=True)
    created: list[FakeInfluxClient] = []
    use_fake_source(monkeypatch, source_client)

    def influx_factory(**options: str) -> FakeInfluxClient:
        """Create and retain one failing fake InfluxDB client."""

        client = FakeInfluxClient(write_api, options)
        created.append(client)
        return client

    monkeypatch.setattr(relay.influxdb_client, "InfluxDBClient", influx_factory)

    assert relay.main(["--settings", str(settings_path), "--once"]) == 1
    assert source_client.close_count == 1
    assert write_api.close_count == 1
    assert created[0].close_count == 1
