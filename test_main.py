"""Test configuration, schema mapping, recovery, scheduling, and cleanup offline."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from main import (
    AppSettings,
    DryRunWriter,
    SnapshotCollector,
    build_influx_record,
    load_influx_config,
    load_settings,
    main,
)
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


def app_settings(
    tmp_path: Path, *, threshold: int = 3, interval_s: float = 10.0
) -> AppSettings:
    """Build validated-equivalent collector settings for behavior tests."""

    return AppSettings(
        measurement="SAESSIPPower",
        interval_s=interval_s,
        reconnect_delay_s=2.0,
        exception_threshold=threshold,
        auth_path=tmp_path / "auth.toml",
        source=SAESSIPPowerSettings("192.168.50.34"),
    )


class FakeClient:
    """Provide ordered source outcomes and observable lifecycle operations.

    Each read returns a queued sample list or raises a queued exception. An
    optional callback simulates per-cycle work duration. Connect, reconnect, and
    close counts make the collector's ownership and recovery policy observable.
    The fake is synchronous and supports no concurrent access.
    """

    def __init__(
        self,
        outcomes: list[list[SourceSample] | Exception],
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

    def read_samples(self) -> list[SourceSample]:
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


class FakeWriter:
    """Capture complete record cycles and expose idempotent-style cleanup.

    The fake performs no network I/O. ``uploaded`` selects the write result used
    for collector logging, and all record sequences are retained for assertions.
    It is intended for synchronous, single-threaded tests.
    """

    def __init__(self, *, uploaded: bool = False) -> None:
        """Initialize captured cycles and cleanup count."""

        self.uploaded = uploaded
        self.cycles: list[list[Mapping[str, object]]] = []
        self.close_count = 0

    def write(self, records: Sequence[Mapping[str, object]]) -> bool:
        """Capture one record cycle and return the selected upload result."""

        self.cycles.append(list(records))
        return self.uploaded

    def close(self) -> None:
        """Record writer resource release."""

        self.close_count += 1


class FakeStopEvent:
    """Advance a fake monotonic clock and stop after a fixed number of waits."""

    def __init__(self, clock: list[float], *, stop_after_waits: int) -> None:
        """Store the shared clock and the number of scheduler waits to allow."""

        self.clock = clock
        self.stop_after_waits = stop_after_waits
        self.waits: list[float] = []

    def is_set(self) -> bool:
        """Report stop after the configured number of waits."""

        return len(self.waits) >= self.stop_after_waits

    def wait(self, timeout: float | None = None) -> bool:
        """Record the wait and advance the fake clock by its duration."""

        assert timeout is not None
        self.waits.append(timeout)
        self.clock[0] += timeout
        return self.is_set()


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

    settings_path = tmp_path / "settings.toml"
    settings_path.write_text(
        """
measurement = "SAESSIPPower"
interval_s = 30
reconnect_delay_s = 1
exception_threshold = 3
auth_path = "private/auth.toml"

[source]
host = "192.168.50.34"
port = 2527
timeout_s = 3
""".strip(),
        encoding="utf-8",
    )

    settings = load_settings(settings_path)

    assert settings.measurement == "SAESSIPPower"
    assert settings.auth_path == (tmp_path / "private" / "auth.toml").resolve()
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

    config = load_influx_config(auth_path)

    assert config.client_options["url"] == "http://influxdb.example:8086"
    assert "bucket" not in config.client_options
    assert (config.org, config.bucket) == ("lab", "devices")


def test_dry_run_does_not_open_missing_auth_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Construct dry-run execution successfully while credentials are absent."""

    settings_path = tmp_path / "settings.toml"
    settings_path.write_text(
        """
measurement = "test"
interval_s = 30
reconnect_delay_s = 0
exception_threshold = 3
auth_path = "missing-auth.toml"
[source]
host = "controller"
""".strip(),
        encoding="utf-8",
    )
    observed: list[bool] = []

    def fake_run(
        collector: SnapshotCollector, *, once: bool, stop_event: object
    ) -> None:
        """Observe writer selection without accessing the real source."""

        del stop_event
        observed.append(once and isinstance(collector.writer, DryRunWriter))
        collector.close()

    monkeypatch.setattr(SnapshotCollector, "run", fake_run)

    assert main(["--settings", str(settings_path), "--once", "--dry-run"]) == 0
    assert observed == [True]


def test_source_failure_reconnects_once_before_counting(tmp_path: Path) -> None:
    """Recover a first read failure locally without a lifetime failure."""

    client = FakeClient([TimeoutError("first"), [sample()]])
    writer = FakeWriter()
    delays: list[float] = []
    collector = SnapshotCollector(
        app_settings(tmp_path), client, writer, sleep=delays.append
    )

    assert collector.run_cycle(1) is True
    assert client.connect_count == 1
    assert client.reconnect_count == 1
    assert delays == [2.0]
    assert collector.lifetime_exception_count == 0
    assert len(writer.cycles) == 1


def test_lifetime_failure_count_does_not_reset_after_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Raise at the cumulative threshold even when a middle cycle succeeds."""

    collector = SnapshotCollector(
        app_settings(tmp_path, threshold=2), FakeClient([]), FakeWriter()
    )
    outcomes: list[Exception | None] = [RuntimeError("one"), None, RuntimeError("two")]

    def fake_poll(_iteration: int) -> list[dict[str, object]]:
        """Return or raise deterministic complete-cycle outcomes."""

        outcome = outcomes.pop(0)
        if outcome is not None:
            raise outcome
        return []

    monkeypatch.setattr(collector, "poll_once", fake_poll)

    assert collector.run_cycle(1) is False
    assert collector.run_cycle(2) is True
    with pytest.raises(RuntimeError, match="two"):
        collector.run_cycle(3)
    assert collector.lifetime_exception_count == 2


def test_scheduler_uses_cycle_start_deadlines_and_cleans_up(tmp_path: Path) -> None:
    """Subtract work time from waits, avoid overlap, and close both resources."""

    clock = [0.0]
    durations = [2.0, 3.0]

    def advance_work() -> None:
        """Advance the fake clock by the current cycle's work duration."""

        clock[0] += durations.pop(0)

    def monotonic() -> float:
        """Return the shared deterministic monotonic time."""

        return clock[0]

    client = FakeClient([[sample()], [sample()]], on_read=advance_work)
    writer = FakeWriter()
    stop_event = FakeStopEvent(clock, stop_after_waits=2)
    collector = SnapshotCollector(
        app_settings(tmp_path, interval_s=10),
        client,
        writer,
        monotonic=monotonic,
    )

    collector.run(once=False, stop_event=stop_event)

    assert stop_event.waits == [8.0, 7.0]
    assert len(writer.cycles) == 2
    assert client.close_count == 1
    assert writer.close_count == 1


def test_once_cleanup_runs_after_writer_failure(tmp_path: Path) -> None:
    """Release source and writer resources when one write raises fatally."""

    class FailingWriter(FakeWriter):
        """Provide one failing synchronous writer for cleanup verification.

        The writer accepts a complete cycle but deliberately raises before any
        external I/O. It inherits observable close state from ``FakeWriter`` and
        is used by one thread for one collector lifecycle.
        """

        def write(self, records: Sequence[Mapping[str, object]]) -> bool:
            """Reject the cycle to exercise collector finalization."""

            del records
            raise RuntimeError("write failed")

    client = FakeClient([[sample()]])
    writer = FailingWriter()
    collector = SnapshotCollector(app_settings(tmp_path), client, writer)

    with pytest.raises(RuntimeError, match="write failed"):
        collector.run(once=True, stop_event=threading.Event())
    assert client.close_count == 1
    assert writer.close_count == 1
