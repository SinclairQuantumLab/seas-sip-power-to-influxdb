"""Exercise the real device API and relay with synthetic UDP and InfluxDB I/O."""

from __future__ import annotations

import socket
import struct
from datetime import UTC, datetime
from pathlib import Path

import influxdb_client
import pytest
import seas_sip_client as sip
from test_main import (
    EXPECTED_FIELDS,
    FakeInfluxClient,
    FakeWriteAPI,
    run_script,
    write_auth,
    write_settings,
)


def read_all_response(conversion_rate: int) -> bytes:
    """Encode a known Rev. 4 response independently of library parsing helpers."""
    payload = bytearray(300)
    for offset, value in (
        (0, 3), (2, 0x0102), (4, 0x0304), (14, 5000), (16, 240),
        (20, 300), (22, 2), (32, 1), (100, 5000), (131, conversion_rate),
    ):
        struct.pack_into(">H", payload, offset, value)
    for offset, value in (
        (6, 123456), (10, 20), (24, 100), (28, 200), (102, 1000),
        (107, 1), (111, 2), (115, 3), (119, 4), (123, 5),
    ):
        struct.pack_into(">I", payload, offset, value)
    payload[34] = 5
    payload[106] = 9
    payload[133] = 11
    payload[200:204] = bytes((192, 168, 50, 34))
    payload[204:208] = bytes((255, 255, 255, 0))
    payload[208:214] = bytes.fromhex("001122aabbcc")
    return b"\x01\x80" + payload


class FakeUDPSocket:
    """Supply one response or timeout and record all datagrams without networking."""

    def __init__(self, outcome: bytes | OSError) -> None:
        """Store the one-shot receive outcome and transport observations."""
        self.outcome = outcome
        self.sent: list[bytes] = []
        self.peer: tuple[str, int] | None = None
        self.timeout: float | None = None
        self.closed = False
        self.receives = 0

    def settimeout(self, value: float | None) -> None:
        """Record the configured response deadline."""
        self.timeout = value

    def connect(self, address: tuple[str, int]) -> None:
        """Record the selected unicast endpoint."""
        self.peer = address

    def send(self, data: bytes) -> int:
        """Capture the exact outgoing request and report its length."""
        self.sent.append(data)
        return len(data)

    def recv(self, bufsize: int) -> bytes:
        """Deliver one response or fail the first socket's acquisition."""
        self.receives += 1
        assert self.receives == 1
        assert bufsize >= 302
        if isinstance(self.outcome, OSError):
            raise self.outcome
        return self.outcome

    def close(self) -> None:
        """Record transport release without issuing a command."""
        self.closed = True


@pytest.mark.parametrize("retry", [False, True])
@pytest.mark.parametrize("conversion_rate", [20, 0])
def test_real_udp_api_preserves_record_and_read_only_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    conversion_rate: int,
    retry: bool,
) -> None:
    """Preserve all record types, one retry and read-only mode through real parsing."""
    settings_path = write_settings(tmp_path)
    write_auth(tmp_path)
    monkeypatch.chdir(tmp_path)
    outcomes: list[bytes | OSError] = [read_all_response(conversion_rate)]
    if retry:
        outcomes.insert(0, TimeoutError("synthetic first-read timeout"))
    sockets: list[FakeUDPSocket] = []

    def socket_factory(family: int, kind: int) -> FakeUDPSocket:
        """Intercept real socket creation and require the UDP transport."""
        assert (family, kind) == (socket.AF_INET, socket.SOCK_DGRAM)
        fake = FakeUDPSocket(outcomes.pop(0))
        sockets.append(fake)
        return fake

    write_api = FakeWriteAPI()

    def influx_factory(**options: str) -> FakeInfluxClient:
        """Keep the upload path offline while capturing the completed record."""
        return FakeInfluxClient(write_api, options)

    monkeypatch.setattr(socket, "socket", socket_factory)
    monkeypatch.setattr(influxdb_client, "InfluxDBClient", influx_factory)
    before = datetime.now(UTC)
    exit_code, namespace = run_script(
        monkeypatch, ["--settings", str(settings_path), "--once"]
    )
    after = datetime.now(UTC)

    assert exit_code == 0
    assert len(write_api.writes) == 1
    record = write_api.writes[0][2][0]
    expected = dict(EXPECTED_FIELDS)
    expected["ConversionRate[A/Torr]"] = conversion_rate
    if conversion_rate == 0:
        expected["Pressure[Torr]"] = None
    assert record["fields"] == expected
    assert all(type(record["fields"][key]) is type(value) for key, value in expected.items())
    assert record["measurement"] == "seas-sip-power"
    assert record["tags"] == {"source": "SAES SIP POWER", "Serial number": "123456"}
    assert before <= record["time"] <= after
    assert record["time"].tzinfo is UTC
    assert type(namespace["sample"]) is sip.DeviceStatus
    assert namespace["sample"].is_single_response is True
    line_protocol = influxdb_client.Point.from_dict(record).to_line_protocol()
    assert ("Pressure[Torr]=" in line_protocol) is (conversion_rate != 0)
    assert "is_single_response" not in line_protocol

    device = namespace["SIP_POWER_CLIENT"]
    assert isinstance(device, sip.SAESSIPPower)
    assert device.access_mode is sip.AccessModeEnum.READ_ONLY
    assert device.settings.connection_type is sip.ConnectionTypeEnum.UDP
    assert device.settings.address_mode is sip.AddressModeEnum.UNICAST
    assert not device.is_connected
    with pytest.raises(sip.SAESSIPPowerPermissionError):
        device.start()
    assert len(sockets) == 1 + int(retry)
    assert not outcomes
    for transport in sockets:
        assert transport.sent == [b"\x01\x05"]
        assert transport.peer == ("192.168.50.34", 2527)
        assert transport.timeout == 3
        assert transport.closed
    assert write_api.close_count == 1
