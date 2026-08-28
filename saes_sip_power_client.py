"""Read and normalize SAES SIP POWER snapshots over its read-only UDP command."""

from __future__ import annotations

import math
import socket
import struct
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from ipaddress import IPv4Address
from typing import Protocol

DEFAULT_PORT = 2527
READ_ALL_REQUEST = bytes((0x01, 0x05))
READ_ALL_RESPONSE_COMMAND = 0x80
PROTOCOL_VERSION = 0x01
READ_ALL_PAYLOAD_LENGTH = 300
READ_ALL_RESPONSE_LENGTH = 2 + READ_ALL_PAYLOAD_LENGTH


class SAESSIPPowerError(RuntimeError):
    """Identify failures produced at the SIP POWER source boundary.

    The exception contains sanitized context but never a raw frame. Callers use
    this common type when communication and malformed-response failures require
    the same collector-level reconnect policy.
    """


class SAESSIPPowerCommunicationError(SAESSIPPowerError):
    """Report a timeout or operating-system failure during a controller read.

    The client raises this after one socket operation fails and performs no
    retry itself. The owning collector may replace the socket and retry once;
    no controller output or setting is changed by that recovery.
    """


class SAESSIPPowerProtocolError(SAESSIPPowerError):
    """Report a response that violates documented SIP POWER UDP framing.

    Invalid length, header values, or timestamp semantics fail the whole sample
    before normalization. The exception exposes no raw datagram, and the
    collector may reconnect and retry it like a source communication failure.
    """


class DatagramSocket(Protocol):
    """Describe connected UDP operations owned by the source client.

    Implementations select one peer, perform synchronous whole-datagram sends
    and receives under a configured timeout, and release their handle on close.
    The source client owns the instance and does not access it concurrently.
    """

    def settimeout(self, value: float | None) -> None:
        """Set the maximum blocking time for one socket operation."""

        ...

    def connect(self, address: tuple[str, int]) -> None:
        """Select the only peer from which datagrams will be accepted."""

        ...

    def send(self, data: bytes) -> int:
        """Send one datagram to the selected peer."""

        ...

    def recv(self, bufsize: int) -> bytes:
        """Receive one datagram from the selected peer."""

        ...

    def close(self) -> None:
        """Release the socket handle."""

        ...


SocketFactory = Callable[[], DatagramSocket]


@dataclass(frozen=True)
class SAESSIPPowerSettings:
    """Hold validated network settings for one SIP POWER controller.

    ``host`` may be an IPv4 address or DNS name. ``port`` is normally the
    controller's hard-coded UDP port 2527, while ``timeout_s`` bounds each read.
    Instances contain no credentials and opening a client does not alter the
    controller.
    """

    host: str
    port: int = DEFAULT_PORT
    timeout_s: float = 3.0

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> SAESSIPPowerSettings:
        """Validate a TOML source table and return stable typed settings."""

        host = values.get("host")
        if not isinstance(host, str) or not host.strip():
            raise ValueError("settings.source.host must be a nonempty string")
        port = values.get("port", DEFAULT_PORT)
        if isinstance(port, bool) or not isinstance(port, int):
            raise TypeError("settings.source.port must be an integer")
        if not 1 <= port <= 65535:
            raise ValueError("settings.source.port must be between 1 and 65535")
        timeout = values.get("timeout_s", 3.0)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise TypeError("settings.source.timeout_s must be a number")
        timeout_s = float(timeout)
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("settings.source.timeout_s must be finite and positive")
        return cls(host=host.strip(), port=port, timeout_s=timeout_s)


@dataclass(frozen=True)
class SourceSample:
    """Represent one complete current-state response from a SIP POWER.

    The sample exposes stable snake_case values decoded from the documented
    Read All response. ``observed_at`` is the host acquisition time in UTC
    because the controller supplies no observation timestamp. Electrical and
    timing units are explicit in attribute names. Alarm fields are latched
    controller states, not transient host-side errors.
    """

    observed_at: datetime
    serial_number: int
    has_ethernet: bool
    has_display: bool
    hardware_revision: str
    software_version: str
    output_current_na: int
    output_voltage_v: int
    input_voltage_v: float
    internal_temperature_k: int
    arcing_events: int
    total_working_time_h: int
    uptime_s: int
    enabled: bool
    need_restart: bool
    output_current_gradient: str
    global_alarm: bool
    safe_alarm: bool
    interlock_alarm: bool
    over_temperature_alarm: bool
    input_voltage_alarm: bool
    output_over_voltage_alarm: bool
    output_over_current_alarm: bool
    arcing_alarm: bool
    communication_alarm: bool
    switch_1_on: bool
    switch_2_on: bool
    switch_3_on: bool
    output_voltage_setpoint_v: int
    output_voltage_ramp_interval_ms: int
    switch_1_mode: str
    switch_2_mode: str
    switch_3_mode: str
    switch_1_threshold_na: int
    switch_2_min_threshold_na: int
    switch_2_max_threshold_na: int
    switch_3_min_threshold_na: int
    switch_3_max_threshold_na: int
    keepalive_interval_ms: int
    conversion_rate_a_per_torr: int
    modbus_id: int
    ip_address: str
    ip_netmask: str
    mac_address: str
    output_power_w: float
    pressure_torr: float | None

    @property
    def device_id(self) -> str:
        """Return the controller serial number as its stable record identity."""

        return str(self.serial_number)


def _udp_socket() -> DatagramSocket:
    """Create the IPv4 UDP socket used by production clients."""

    return socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


def _u16(payload: bytes, offset: int) -> int:
    """Decode one network-order unsigned 16-bit integer from a payload."""

    return struct.unpack_from(">H", payload, offset)[0]


def _u32(payload: bytes, offset: int) -> int:
    """Decode one network-order unsigned 32-bit integer from a payload."""

    return struct.unpack_from(">I", payload, offset)[0]


def _revision(value: int) -> str:
    """Format the manual's major-byte/minor-byte revision representation."""

    return f"{value >> 8}.{value & 0xFF}"


def _switch_mode(value: int) -> str:
    """Return a stable name for a two-bit switch operating mode."""

    return {0: "OFF", 1: "SIMPLE", 2: "WINDOW"}.get(value, "RESERVED")


def parse_read_all_response(
    response: bytes, *, observed_at: datetime | None = None
) -> SourceSample:
    """Decode one documented 302-byte Read All Answer datagram.

    Args:
        response: Complete UDP datagram including version and command bytes.
        observed_at: Optional acquisition timestamp for deterministic tests. When
            omitted, the parser stamps successful acquisition with current UTC.

    Returns:
        A complete normalized controller snapshot.

    Raises:
        SAESSIPPowerProtocolError: If length, version, command, or timestamp is
            invalid. Reserved payload bytes are intentionally ignored.
    """

    if len(response) != READ_ALL_RESPONSE_LENGTH:
        raise SAESSIPPowerProtocolError(
            "Read All response must be exactly "
            f"{READ_ALL_RESPONSE_LENGTH} bytes; received {len(response)}"
        )
    if response[0] != PROTOCOL_VERSION:
        raise SAESSIPPowerProtocolError(
            f"unexpected protocol version 0x{response[0]:02x}"
        )
    if response[1] != READ_ALL_RESPONSE_COMMAND:
        raise SAESSIPPowerProtocolError(
            f"unexpected response command 0x{response[1]:02x}"
        )
    timestamp = observed_at or datetime.now(UTC)
    if timestamp.utcoffset() is None:
        raise SAESSIPPowerProtocolError("observation timestamp must be timezone-aware")

    payload = response[2:]
    card_type = _u16(payload, 0)
    hardware_code = _u16(payload, 2)
    software_version = _u16(payload, 4)
    output_current_na = _u32(payload, 10)
    output_voltage_v = _u16(payload, 14)
    status = _u16(payload, 32)
    switch_status = payload[34]
    switch_modes = payload[106]
    conversion_rate = _u16(payload, 131)
    output_power_w = output_current_na * 1e-9 * output_voltage_v
    pressure_torr = (
        output_current_na * 1e-9 / conversion_rate if conversion_rate else None
    )
    gradient_value = (status >> 2) & 0b11
    gradient = {0: "HOLD", 1: "UP", 2: "DOWN"}.get(
        gradient_value, "RESERVED"
    )

    return SourceSample(
        observed_at=timestamp.astimezone(UTC),
        serial_number=_u32(payload, 6),
        has_ethernet=bool(card_type & (1 << 1)),
        has_display=bool(card_type & 1),
        hardware_revision=_revision(hardware_code),
        software_version=_revision(software_version),
        output_current_na=output_current_na,
        output_voltage_v=output_voltage_v,
        input_voltage_v=_u16(payload, 16) / 10.0,
        internal_temperature_k=_u16(payload, 20),
        arcing_events=_u16(payload, 22),
        total_working_time_h=_u32(payload, 24),
        uptime_s=_u32(payload, 28),
        enabled=bool(status & (1 << 0)),
        need_restart=bool(status & (1 << 1)),
        output_current_gradient=gradient,
        global_alarm=bool(status & (1 << 4)),
        safe_alarm=bool(status & (1 << 5)),
        interlock_alarm=bool(status & (1 << 6)),
        over_temperature_alarm=bool(status & (1 << 7)),
        input_voltage_alarm=bool(status & (1 << 8)),
        output_over_voltage_alarm=bool(status & (1 << 9)),
        output_over_current_alarm=bool(status & (1 << 10)),
        arcing_alarm=bool(status & (1 << 11)),
        communication_alarm=bool(status & (1 << 12)),
        switch_1_on=bool(switch_status & (1 << 0)),
        switch_2_on=bool(switch_status & (1 << 1)),
        switch_3_on=bool(switch_status & (1 << 2)),
        output_voltage_setpoint_v=_u16(payload, 100),
        output_voltage_ramp_interval_ms=_u32(payload, 102),
        switch_1_mode=_switch_mode(switch_modes & 0b11),
        switch_2_mode=_switch_mode((switch_modes >> 2) & 0b11),
        switch_3_mode=_switch_mode((switch_modes >> 4) & 0b11),
        switch_1_threshold_na=_u32(payload, 107),
        switch_2_min_threshold_na=_u32(payload, 111),
        switch_2_max_threshold_na=_u32(payload, 115),
        switch_3_min_threshold_na=_u32(payload, 119),
        switch_3_max_threshold_na=_u32(payload, 123),
        keepalive_interval_ms=_u32(payload, 127),
        conversion_rate_a_per_torr=conversion_rate,
        modbus_id=payload[133],
        ip_address=str(IPv4Address(payload[200:204])),
        ip_netmask=str(IPv4Address(payload[204:208])),
        mac_address=":".join(f"{byte:02X}" for byte in payload[208:214]),
        output_power_w=output_power_w,
        pressure_torr=pressure_torr,
    )


class SAESSIPPowerClient:
    """Own one synchronous, read-only SAES SIP POWER UDP endpoint.

    The client implements only the vendor's ``Read All`` command (0x05); it
    cannot start, stop, reset, clear alarms, or change controller settings.
    ``connect`` creates a connected UDP socket so replies are accepted only from
    the configured controller, and ``read_sample`` returns one fully normalized
    :class:`SourceSample`. The controller supplies no time, so successful reads
    receive an aware UTC host-acquisition timestamp.

    A socket timeout, send error, or receive error is exposed as
    :class:`SAESSIPPowerCommunicationError`; malformed replies are exposed as
    :class:`SAESSIPPowerProtocolError`. This class performs no internal retry:
    the collector owns the one reconnect-and-retry policy. ``close`` is
    idempotent, and the instance can reconnect after close. Calls are blocking,
    one instance supports one device, and concurrent use is unsupported.

    Args:
        settings: Validated controller host, UDP port, and timeout.
        socket_factory: Injectable factory used by offline tests.
    """

    def __init__(
        self,
        settings: SAESSIPPowerSettings,
        *,
        socket_factory: SocketFactory = _udp_socket,
    ) -> None:
        """Store settings and factory without opening a socket."""

        self.settings = settings
        self._socket_factory = socket_factory
        self._socket: DatagramSocket | None = None

    @property
    def is_connected(self) -> bool:
        """Report whether this instance currently owns a UDP socket."""

        return self._socket is not None

    def connect(self) -> None:
        """Create the socket and select the configured controller as its peer."""

        if self._socket is not None:
            return
        udp_socket = self._socket_factory()
        try:
            udp_socket.settimeout(self.settings.timeout_s)
            udp_socket.connect((self.settings.host, self.settings.port))
        except OSError as error:
            udp_socket.close()
            raise SAESSIPPowerCommunicationError(
                f"could not prepare UDP endpoint {self.settings.host}:"
                f"{self.settings.port}: {error}"
            ) from error
        self._socket = udp_socket

    def reconnect(self) -> None:
        """Replace any existing socket with a fresh endpoint."""

        self.close()
        self.connect()

    def read_sample(self) -> SourceSample:
        """Request and decode one current snapshot from the controller."""

        udp_socket = self._socket
        if udp_socket is None:
            raise SAESSIPPowerCommunicationError("client is not connected")
        try:
            sent = udp_socket.send(READ_ALL_REQUEST)
            if sent != len(READ_ALL_REQUEST):
                raise SAESSIPPowerCommunicationError(
                    f"incomplete UDP request: sent {sent} of {len(READ_ALL_REQUEST)} bytes"
                )
            response = udp_socket.recv(4096)
        except SAESSIPPowerCommunicationError:
            raise
        except OSError as error:
            raise SAESSIPPowerCommunicationError(
                f"Read All failed for {self.settings.host}:{self.settings.port}: {error}"
            ) from error
        return parse_read_all_response(response)

    def read_samples(self) -> list[SourceSample]:
        """Return the one configured controller sample as a cycle list."""

        return [self.read_sample()]

    def close(self) -> None:
        """Release the owned socket idempotently."""

        udp_socket, self._socket = self._socket, None
        if udp_socket is not None:
            udp_socket.close()
