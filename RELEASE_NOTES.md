# Energy OWL 0.9.1

Fixes the historical import paths associated with issue #5. Historical records use
Home Assistant's statistics API exclusively; direct historical state writing and
the homeassistant-historical-sensor dependency have been removed.

- A durable, entry-owned energy ledger combines minute history and live intervals in one external statistics source.
- History uses observed one-minute records, with duplicate/overlap handling and UTC/DST normalization. It no longer extrapolates one sample to a whole hour.
- Live energy uses packet receipt timestamps and a 90-second maximum gap. Cached readings, stale packets, disconnects and restarts cannot create catch-up energy.
- The ledger is saved atomically before acknowledgement; failed or interrupted Recorder submissions are replayed idempotently after restart.
- Import enable/disable, empty history, acknowledgement retries, and unload cleanup are handled independently of enabled sensor entities.
- Corrected invalid statistics IDs and serial exception imports; pinned owlsensor to 0.7.2 and aligned HACS minimum HA to 2026.5.2.

## Upgrade

For combined historical/live consumption, select **Energy OWL CM160 (<port>) Estimated Energy**
(`energy_owl:cm160_<port>_v2_energy`) in the Energy Dashboard. Do not also select the
live Energy sensor for the same meter. Existing live entity IDs are preserved.
Old Historical Data Processor registry entries can be removed manually.

The device clock must match HA's timezone. Ambiguous local DST minutes are skipped.
Power and energy remain estimates assuming unity power factor; historical voltage
uses the fixed configured setting. Missing measurements are not reconstructed.
Include HA .storage files in backups to preserve the cumulative ledger.

This release prevents the unsafe write path; it does not repair an already damaged
Recorder database. Hardware validation on the user's HA host remains necessary.

## Validation

101 tests pass on both Home Assistant 2026.5.2 and 2026.10.4 with Python 3.14,
including the real Recorder/database regression, minute/UTC/DST accounting,
restore/reconnect gaps, overlap/replay, storage failure and serial packet freshness.
Runtime imports and the real pinned OWL collector constructor are also checked.
