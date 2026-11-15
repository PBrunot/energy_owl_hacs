# Energy OWL 0.9.2

Fixes false connection success when the OWL library returns `False` from `connect()`,
and completes the Priority 2 lifecycle and structure improvements.

- Failed serial connections now leave the coordinator disconnected and raise a setup/update failure. Configuration validation rejects the same failure and closes its test collector.
- Complete polls, history snapshots, resets and reconnects share the serial lifecycle lock. Cancelled setup and partial platform failures clean up connections and import tasks.
- Added port reconfiguration for the same CM160 adapter, preserving existing device/entity IDs, the combined statistics source and the durable energy ledger.
- Actions register independently of loaded entries, require exactly one explicit Energy OWL device target, validate entry readiness and return translated errors. Empty CSV exports and file-write failures no longer report success.
- Current, power and live energy availability requires successful polling and an actual live packet no older than 90 seconds.
- Diagnostics expose connection, sync, recovery, import progress and dependency versions. Measurement entities no longer repeat changing debug counters; history status uses translated enum states.

## Upgrade

Automations calling Energy OWL actions must explicitly target one device with
`target: device_id`. Multiple devices and implicit defaults are rejected.
The optional history status sensor now uses `starting`, `syncing`, `complete` and
`disconnected` states, with record counts in attributes; update automations that
match its previous English text.

Use Reconfigure only when changing the port of the same CM160 adapter. The protocol
does not provide a verified immutable hardware ID. Existing energy source selection
and stored ledger remain unchanged. Keep the CM160 clock aligned with HA's timezone;
this release does not correct device clock settings or rewrite historical timestamps.

## Validation

128 tests pass on each of Home Assistant 2026.5.2 and 2026.10.4 with Python 3.14,
including real Recorder imports, integration-loader setup/unload, connection refusal,
serial lifecycle locking, port identity continuity and action error handling.
Runtime Ruff, component JSON parsing and whitespace checks pass.

A user-supplied 0.9.1 hardware log confirms history collection, import completion,
acknowledgement and subsequent live packets. It exposed the connection-refusal bug
fixed here; 0.9.2 itself has not yet been tested on physical hardware.
