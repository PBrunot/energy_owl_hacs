# Energy OWL 0.9.6

Energy OWL now recovers automatically after a USB disconnect. It closes the failed
serial connection and retries the configured port on subsequent polls until the
adapter returns, so normal recovery needs no Home Assistant reboot. If the driver
keeps the serial stream open while no packets arrive, Energy OWL reopens it after
five minutes of silence, including during history collection.

To reopen the port immediately, run `energy_owl.force_reconnect` in Home Assistant
under **Developer Tools → Actions** and select your CM160 as the device target.

Regression tests simulated a USB disconnect, repeated open failures, and resumed
live readings after reconnect. Both Home Assistant test suites passed with 148
tests each. Physical USB testing is pending.

## Energy OWL 0.9.5

Import routine historical minute updates silently and reserve recovery status and
notifications for substantial backfills of previously missing history.

- After initial processing, history status stays `complete` during routine minute
  updates. Internal two-minute batches continue importing without notifications.
- Enter `syncing` only after recovering at least 60 previously missing distinct
  minutes, each more than five minutes old. Counts span contiguous recovery batches
  and exclude duplicates and already imported minutes.
- Send one notification and `energy_owl_historical_data_complete` event when that
  recovery settles: no older-history activity for two minutes and no older records
  pending in the local buffer. Smaller, separate backfills remain silent.
- Retain an unfinished current historical minute and its buffer suffix until the
  minute ends. Retry retained records even when no further packet arrives.
- Prevent read/export actions from changing the imported prefix length while the
  ledger is being saved. Save-before-cleanup ordering remains intact.

## Upgrade

Update through HACS and restart Home Assistant. Existing identities, energy ledger
and Energy Dashboard source are preserved. No device reset or ledger deletion is
needed. An existing completion notification can be dismissed once.

Automations using `energy_owl_historical_data_complete` now run only for substantial
recoveries, rather than every internal import batch. `complete` does not confirm a
Recorder database commit. Records discarded by earlier versions can be recovered
only if the device supplies them again.

The fixes are based on the supplied 0.9.4 hardware capture. Version 0.9.5 has not yet
been tested on physical hardware. See docs/log-review-0.9.4.md for the findings.

## Validation

146 tests pass on each of Home Assistant 2026.5.2 and 2026.10.4 with Python 3.14.
The HA 2026.11.1 runtime smoke check, pinned Ruff, local metadata validation and
`git diff --check` also pass.

New regression coverage includes real packets from the 0.9.4 capture, silent routine
batches, substantial recoveries across batches, duplicate replays, threshold edges,
failed storage, separate small backfills, unfinished-minute retention and concurrent
read/export actions. Existing coverage includes real Recorder imports and loading.
