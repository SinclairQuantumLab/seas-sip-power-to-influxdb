# SAES SIP POWER protocol ownership

Canonical device protocol documentation and the Rev.4 manual now live in the
independent py-seas-sip-power Git submodule:

- `py-seas-sip-power/.agents/PROTOCOL.md`
- `py-seas-sip-power/device-docs/saes-sip_power-user_manual-rev_4.pdf`

The relay uses only Read All through `seas_sip_client`. It never calls Start,
Stop, Reset or Clear Alarm. The measurement remains `seas-sip-power` and the
sample/schema mapping, timestamps, timing and recovery policies are unchanged.
See VALIDATION.md for application evidence; library evidence belongs to the
library's own .agents/VALIDATION.md.
