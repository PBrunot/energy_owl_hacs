# Energy OWL 0.9.4

Fix history imports that remain stuck in `syncing` when the CM160 continuously
sends historical records alongside live readings.

- Close each history batch after two minutes of age, checked on each coordinator
  poll, even when more history keeps arriving. The existing two-minute silence
  timeout also remains available.
- Persist the energy ledger and queue statistics before removing the imported
  local buffer prefix. Records received during persistence remain available for
  the next import, and failed storage is retried without discarding history.
- Repeated historical minutes do not double count energy. When history import is
  disabled, bounded batches also prevent indefinite local buffer growth.
- Clarify that live readings and history arrive interleaved. History status may
  alternate between `syncing` and `complete` as batches arrive. Completion events
  describe closed batches, not the end of device streaming or a Recorder commit.
- Synchronize the real Recorder regression test before requesting a commit, so
  fast CI runners cannot read an earlier state while writes are still pending.

## Upgrade

Update through HACS and restart Home Assistant. Existing identities, energy ledger
and Energy Dashboard source are preserved. No device reset or ledger deletion is
needed. Previously persisted live estimates remain available; historical records
still supplied by the device can replace overlapping estimates after import.

The fix is based on a user-supplied 0.9.3 hardware log. Version 0.9.4 has not yet
been tested on physical hardware.

## Validation

139 tests pass on each of Home Assistant 2026.5.2 and 2026.10.4 with Python 3.14.
The HA 2026.11.1 runtime smoke check, pinned Ruff, local metadata validation and
`git diff --check` also pass.

Regression coverage replays real CM160 packets continuously across multiple batch
windows, including duplicate minutes, a failed ledger save and disabled history
import. Existing tests cover history arriving during persistence and concurrent
polling, durable replay, real Recorder imports and integration loading.
