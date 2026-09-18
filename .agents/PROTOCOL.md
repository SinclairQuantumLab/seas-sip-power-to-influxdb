# SAES SIP POWER protocol

## Status

The protocol implementation and historical device evidence below remain stable.
The operational measurement is `seas-sip-power`, confirmed by the user on
2026-09-15. Aligning its tests and documentation does not change UDP framing
or parsing; see `VALIDATION.md` for current evidence boundaries.

## Sources and acquisition choice

- Primary source: `device-docs/saes-sip_power-user_manual-rev_4.pdf`, document
  M.HIST.0109.23 Rev. 4, dated September 15, 2022.
- Relevant manual sections: 9 (remote communication), 9.2 (Ethernet UDP), and
  9.2.3 (Read All Answer), pages 30 and 46-51.
- Current implementation is single-device, synchronous snapshot polling over
  IPv4 UDP. The controller has no observation timestamp, so a successful parse
  is stamped with the host's aware UTC acquisition time.

## Verified UDP framing

- The controller listens on hard-coded UDP port 2527.
- Request and response payload values use network byte order (big-endian).
- A packet begins with one version byte and one command byte.
- Read All request is exactly `version=0x01, command=0x05` with no payload.
- Read All Answer is exactly 302 bytes: `version=0x01, command=0x80`, followed
  by the 300-byte payload described in the manual.
- The client uses a connected UDP socket, which restricts accepted responses to
  the configured controller endpoint.
- The client now exposes Start (`01 01`) and Stop (`01 02`), per Rev. 4
  section 9.2, page 46. Both control HV output, with no payload or ACK. Callers
  use Read All afterward to observe enabled state, voltage, and alarms.
  Commands are sent once; there is no automatic control retry or confirmation.
- The InfluxDB relay still sends only Read All. Reset, Clear Alarm, Set Working
  Parameters, and Set IP Address are not implemented.
- Keepalive is unchanged. After remote Start, poll through the same client
  within the configured interval or HV stops with a communication alarm
  (sections 9.2.1 and 9.2.3). Closing the socket does not issue Stop.

## Read All payload boundaries

Payload byte offsets below exclude the two-byte packet header.

| Bytes | Values |
| --- | --- |
| 0-9 | Card flags, hardware revision, software version, serial number |
| 10-19 | Output current [nA], output voltage [V], input voltage [dV], reserved |
| 20-34 | Temperature [K], arcs, hours, uptime [s], status, switch status |
| 35-99 | Reserved |
| 100-133 | Set point, ramp, switch modes/thresholds, keepalive, conversion, Modbus ID |
| 134-199 | Reserved |
| 200-213 | IPv4 address, netmask, MAC address |
| 214-299 | Reserved |

The text below the page-48 table says "Bit 48:55 - Card type," but the table
and every subsequent field boundary place Card Type at payload bits 0:15. The
parser follows the table; treating 48:55 as Card Type would overlap the serial
number and make the remainder inconsistent.

The manual states that the conversion rate in A/Torr is useful for calculating
pressure from output current. The normalized optional pressure is therefore
`output_current_na * 1e-9 / conversion_rate_a_per_torr` when the reported rate
is nonzero. A zero conversion rate yields `pressure_torr=None`; the application
keeps that normalized value in its local record dictionary, and the pinned
InfluxDB client omits it when serializing line protocol.

## Current live evidence

On 2026-08-28 (America/Chicago), the configured controller at
`192.168.50.34:2527` answered both the initial transport probe and the completed
app's read-only dry-run. Both responses had the documented 302-byte framing.
The app parsed serial 25040035, hardware 2.2, software 2.0, reported IP
192.168.50.34, and input 24.0 V. Only normalized values were printed; no raw
frame was logged or committed, no control command was sent, and no InfluxDB
write occurred.
