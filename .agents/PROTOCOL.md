# SAES SIP POWER protocol ownership

Canonical device protocol documentation and the Rev.4 manual now live in the
independent py-seas-sip-power Git submodule:

- `py-seas-sip-power/.agents/PROTOCOL.md`
- `py-seas-sip-power/device-docs/saes-sip_power-user_manual-rev_4.pdf`

The NEXTorr Z manual and specifications also live in that library's
`device-docs/` directory. There is no relay-level manual directory.

The relay uses `SAESSIPPower(ConnectionSettings(...))` through `seas_sip_client`,
with explicit `ConnectionTypeEnum.UDP` and `AccessModeEnum.READ_ONLY`. Each
`read_sample()` returns one `DeviceStatus` from the same UDP Read All parser.
Reconnect preserves that access mode and never issues a controller write.
The relay never calls Start,
Stop, Reset or Clear Alarm. The measurement remains `seas-sip-power` and the
sample/schema mapping, timestamps, timing and recovery policies are unchanged.
See VALIDATION.md for application evidence; library evidence belongs to the
library's own .agents/VALIDATION.md.
