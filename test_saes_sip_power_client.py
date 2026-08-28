"""Test SAES SIP POWER UDP framing, parsing, validation, and cleanup offline."""

from __future__ import annotations

import struct
from datetime import UTC, datetime

import pytest

from saes_sip_power_client import (
    READ_ALL_REQUEST,
    SAESSIPPowerClient,
    SAESSIPPowerCommunicationError,
    SAESSIPPowerProtocolError,
    SAESSIPPowerSettings,
    parse_read_all_response,
)


def read_all_response(*, conversion_rate: int = 20) -> bytes:
    """Build a representative documented 300-byte payload and response header."""

    payload = bytearray(300)
    struct.pack_into(">H", payload, 0, 0b11)
    struct.pack_into(">H", payload, 2, 0x0102)
    struct.pack_into(">H", payload, 4, 0x0304)
    struct.pack_into(">I", payload, 6, 123456)
    struct.pack_into(">I", payload, 10, 1000)
    struct.pack_into(">H", payload, 14, 5000)
    struct.pack_into(">H", payload, 16, 240)
    struct.pack_into(">H", payload, 20, 300)
    struct.pack_into(">H", payload, 22, 7)
    struct.pack_into(">I", payload, 24, 100)
    struct.pack_into(">I", payload, 28, 200)
    status = 1 | 2 | (2 << 2) | sum(1 << bit for bit in range(4, 13))
    struct.pack_into(">H", payload, 32, status)
    payload[34] = 0b101
    struct.pack_into(">H", payload, 100, 5000)
    struct.pack_into(">I", payload, 102, 2000)
    payload[106] = 1 | (2 << 2)
    for offset, value in zip((107, 111, 115, 119, 123), range(11, 16), strict=True):
        struct.pack_into(">I", payload, offset, value)
    struct.pack_into(">I", payload, 127, 30000)
    struct.pack_into(">H", payload, 131, conversion_rate)
    payload[133] = 11
    payload[200:204] = bytes((192, 168, 50, 34))
    payload[204:208] = bytes((255, 255, 255, 0))
    payload[208:214] = bytes.fromhex("001122AABBCC")
    return bytes((0x01, 0x80)) + payload


class FakeSocket:
    """Provide deterministic connected-UDP behavior without network access.

    The fake records timeout, peer, request, and close operations. One queued
    response is returned per receive; queued ``OSError`` instances are raised to
    exercise the client's communication error translation. It is single-threaded
    and owns no real operating-system resource.
    """

    def __init__(self, responses: list[bytes | OSError]) -> None:
        """Store queued datagrams or errors and initialize observations."""

        self.responses = responses
        self.timeout: float | None = None
        self.peer: tuple[str, int] | None = None
        self.sent: list[bytes] = []
        self.closed = False

    def settimeout(self, value: float | None) -> None:
        """Record the configured operation timeout."""

        self.timeout = value

    def connect(self, address: tuple[str, int]) -> None:
        """Record the selected UDP peer."""

        self.peer = address

    def send(self, data: bytes) -> int:
        """Record a complete datagram and report its length."""

        self.sent.append(data)
        return len(data)

    def recv(self, bufsize: int) -> bytes:
        """Return or raise the next queued receive outcome."""

        assert bufsize >= 302
        result = self.responses.pop(0)
        if isinstance(result, OSError):
            raise result
        return result

    def close(self) -> None:
        """Record idempotent resource release."""

        self.closed = True


def test_parse_read_all_response_decodes_every_field_group() -> None:
    """Decode identity, readings, status, settings, and network values."""

    observed_at = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    sample = parse_read_all_response(read_all_response(), observed_at=observed_at)

    assert sample.observed_at == observed_at
    assert sample.device_id == "123456"
    assert (sample.has_ethernet, sample.has_display) == (True, True)
    assert (sample.hardware_revision, sample.software_version) == ("1.2", "3.4")
    assert sample.output_current_na == 1000
    assert sample.output_voltage_v == 5000
    assert sample.input_voltage_v == 24.0
    assert sample.internal_temperature_k == 300
    assert (sample.arcing_events, sample.total_working_time_h, sample.uptime_s) == (
        7,
        100,
        200,
    )
    assert sample.enabled is True
    assert sample.need_restart is True
    assert sample.output_current_gradient == "DOWN"
    assert all(
        (
            sample.global_alarm,
            sample.safe_alarm,
            sample.interlock_alarm,
            sample.over_temperature_alarm,
            sample.input_voltage_alarm,
            sample.output_over_voltage_alarm,
            sample.output_over_current_alarm,
            sample.arcing_alarm,
            sample.communication_alarm,
        )
    )
    assert (sample.switch_1_on, sample.switch_2_on, sample.switch_3_on) == (
        True,
        False,
        True,
    )
    assert sample.output_voltage_setpoint_v == 5000
    assert sample.output_voltage_ramp_interval_ms == 2000
    assert (sample.switch_1_mode, sample.switch_2_mode, sample.switch_3_mode) == (
        "SIMPLE",
        "WINDOW",
        "OFF",
    )
    assert (
        sample.switch_1_threshold_na,
        sample.switch_2_min_threshold_na,
        sample.switch_2_max_threshold_na,
        sample.switch_3_min_threshold_na,
        sample.switch_3_max_threshold_na,
    ) == (11, 12, 13, 14, 15)
    assert sample.keepalive_interval_ms == 30000
    assert sample.conversion_rate_a_per_torr == 20
    assert sample.modbus_id == 11
    assert sample.ip_address == "192.168.50.34"
    assert sample.ip_netmask == "255.255.255.0"
    assert sample.mac_address == "00:11:22:AA:BB:CC"
    assert sample.output_power_w == pytest.approx(0.005)
    assert sample.pressure_torr == pytest.approx(5e-8)


def test_parse_read_all_response_omits_pressure_when_conversion_is_zero() -> None:
    """Represent undefined pressure as absent when the conversion rate is zero."""

    sample = parse_read_all_response(read_all_response(conversion_rate=0))

    assert sample.pressure_torr is None


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (read_all_response()[:-1], "exactly 302 bytes"),
        (bytes((2,)) + read_all_response()[1:], "protocol version"),
        (bytes((1, 5)) + read_all_response()[2:], "response command"),
    ],
)
def test_parse_read_all_response_rejects_malformed_frames(
    response: bytes, message: str
) -> None:
    """Reject missing bytes and unexpected header values before field parsing."""

    with pytest.raises(SAESSIPPowerProtocolError, match=message):
        parse_read_all_response(response)


def test_parse_read_all_response_rejects_naive_timestamp() -> None:
    """Require timezone-aware acquisition timestamps at the source boundary."""

    with pytest.raises(SAESSIPPowerProtocolError, match="timezone-aware"):
        parse_read_all_response(
            read_all_response(), observed_at=datetime(2026, 8, 28)
        )


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"host": ""},
        {"host": "device", "port": True},
        {"host": "device", "port": 0},
        {"host": "device", "timeout_s": False},
        {"host": "device", "timeout_s": float("inf")},
    ],
)
def test_source_settings_reject_invalid_values(values: dict[str, object]) -> None:
    """Reject missing identity, booleans-as-numbers, and invalid ranges."""

    with pytest.raises((TypeError, ValueError)):
        SAESSIPPowerSettings.from_mapping(values)


def test_client_reads_documented_request_and_closes_idempotently() -> None:
    """Use the configured endpoint, parse one sample, and release the socket."""

    fake_socket = FakeSocket([read_all_response()])
    settings = SAESSIPPowerSettings("192.168.50.34", timeout_s=1.5)
    client = SAESSIPPowerClient(settings, socket_factory=lambda: fake_socket)

    client.connect()
    sample = client.read_sample()
    client.close()
    client.close()

    assert fake_socket.timeout == 1.5
    assert fake_socket.peer == ("192.168.50.34", 2527)
    assert fake_socket.sent == [READ_ALL_REQUEST]
    assert sample.serial_number == 123456
    assert fake_socket.closed is True
    assert client.is_connected is False


def test_client_translates_receive_timeout_without_raw_frame_logging() -> None:
    """Expose a receive timeout as the source communication error contract."""

    fake_socket = FakeSocket([TimeoutError("timed out")])
    client = SAESSIPPowerClient(
        SAESSIPPowerSettings("controller"), socket_factory=lambda: fake_socket
    )
    client.connect()

    with pytest.raises(SAESSIPPowerCommunicationError, match="Read All failed"):
        client.read_sample()
