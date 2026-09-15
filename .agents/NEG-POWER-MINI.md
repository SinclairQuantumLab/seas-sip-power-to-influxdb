# NEG POWER MINI feasibility review - 2026-09-15

Scope: compare the user-supplied NEG material with the SIP client. This is an
assessment, not authorization to implement multi-device acquisition or active
pump control. No device was contacted and no runtime code was changed.

## Sources

- User-supplied `saes-neg_power_mini-user_manual-rev_4.pdf`, M.HIST.0138.23
  Rev. 4, September 15, 2022, 27 pages, located under
  `C:/Users/Joon/Box/IMAQ Lab/Manuals/Saes Nextorr Z200/Saes NEG POWER MINI USB Manual stick/`.
  Relevant sections: 2.1-2.3 (pages 4-5), 4.2 (pages 12-13), 7 (page 20),
  and Appendix A (page 26). Protocol/settings pages were rendered and inspected.
- SIP POWER Rev. 4, section 9.2 (page 46), and current
  `saes_sip_power_client.py` at application state `02a3d48`.
- The adjacent NEXTorr Z 200 datasheet confirms that SIP POWER and NEG POWER
  MINI are separate controllers serving the ion and getter sections.

## Confirmed differences

| Surface | Existing SIP client | NEG POWER MINI manual |
| --- | --- | --- |
| Ethernet | Custom UDP | Modbus TCP |
| Port | 2527, fixed by SIP protocol | Configurable; default-settings screenshot shows 502 |
| Acquisition | Two-byte `01 05` Read All; 302-byte answer | Device-specific Modbus reads require a register map |
| Parsing | Fixed 300-byte payload offsets and status bits | Register addresses, types, scaling, and flags not supplied |
| Physical readings | Ion current, voltage, derived pressure | Heater voltage/current and pump temperature if equipped |
| Other interface | Current implementation uses only UDP | RS232 Modbus RTU; USB is flash-drive logging |

The two protocols are not wire-compatible. Changing a host or port in the SIP
client cannot make it read the NEG controller. SIP payload offsets, command
codes, status bits, serial encoding, and pressure conversion must not be
assumed to apply to NEG. The RTU screenshot's slave ID also does not by itself
establish the required TCP unit identifier.

## Missing evidence

The 27-page NEG user manual describes Modbus and network setup but contains
no device register map. Before implementing readings, obtain the supported
function codes, register addresses, value representations/scales, multiword
ordering, TCP unit-ID behavior, and unavailable-temperature/status encodings.
Whether one request can acquire all desired values atomically is unknown.

The provided folder contains the manual and `saes-negmini_manager_setup.exe`,
plus USB filesystem metadata. A read-only 7-Zip listing could not open the
installer as an archive; it was not executed. Web searches located vendor
product information but no usable device-specific register map in this review.
Possible next evidence sources are SAES's protocol document, installed manager
resources, or a capture of the manager's read-only polling traffic.

## Reuse and repository extension

The existing `connect/read_sample/reconnect/close` interface, normalized sample
approach, host acquisition timestamps, polling/retry policy, writer setup,
logging, startup wrappers, and offline-test approach are useful patterns.
The actual NEG transport and parser should be a separate
`saes_neg_power_mini_client.py`, using a Modbus implementation once the map is
known. A shared base class is not necessary merely to reuse lifecycle names.

Keeping both clients in this repository is technically reasonable for one
NEXTorr station. Keep `seas-sip-power` unchanged; a separate NEG measurement
such as `saes-neg-power-mini` would need a deliberate new schema. Supporting
both devices in one process additionally requires explicit configuration,
poll timing, and failure-isolation decisions so a missing NEG controller does
not prevent SIP uploads. A separate entrypoint/process in the same repository
is another simple option when independent operation is preferred.

Active Start/Stop, heater setpoint, or activation-cycle control is a separate
capability from the present read-only relay. It needs verified write-command
semantics and explicit requested scope. This review introduces none of it.
