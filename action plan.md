# Energy OWL action plan: 0.9.2

## Current status

All eleven Priority 1 items and the Priority 2 improvements shipped in **v0.9.2** (`d1da682`). Priority 2 lifecycle and structure improvements are now implemented and validated below. Priority 3 packaging, documentation and local validation work is implemented; remaining external checks are recorded below. The original review and earlier checkpoints are preserved below for context; their OPEN statuses are historical.

| Priority 1 item | Completed solution |
| --- | --- |
| 1 Valid IDs | Valid slugged external statistics IDs; tested through the actual Recorder API |
| 2 Unsafe history writes | Historical state writer and third-party dependency deleted; only official statistics imports |
| 3 Import option | Entry-owned combined source exists only when historical import is enabled |
| 4 Device handshake | Importer registered before first refresh; saved snapshot and submission precede acknowledgement; empty history and acknowledgement retry covered |
| 5 Failed chunks | No state-writing chunks; normalize complete batch before import; conflicting duplicate minutes fail the batch |
| 6 Completion and lifecycle | Success means durably saved and queued; failure retries; tasks cancelled and awaited on unload; startup failures clean up |
| 7 Live gaps | Timestamped receipt of actual live packets, duplicate/stale checks, previous-power integration with a 90-second maximum gap; reconnect/restore/missing samples reset baseline |
| 8 Historical intervals | One-minute rectangular estimates; only observed minutes, deduplication, UTC splitting, local device timezone normalization, ambiguous/nonexistent DST minutes skipped with warning |
| 9 Continuity and overlap | One external combined history/live source; historical minutes replace overlapping live estimates; cumulative sums recomputed deterministically, preserved across restart |
| 10 Measurement assumptions | Fixed historical voltage frozen per accepted minute; valid converted live volts/fallback; unity power factor and missing-measurement limits explicitly documented |
| 11 Durability | Atomic HA Store ledger BEFORE device acknowledgement; replay independent of device availability, idempotent upserts, retained hourly baseline; 35 days of minute detail plus immutable archived hourly totals |

## Priority 2 completion (2026-11-15)

- Structure: setup/unload remain in `__init__.py`, serial acquisition and lifecycle in coordinator, statistics in `statistics.py`, integration in `energy.py`, actions moved to `services.py`.
- Lifecycle: setup cancellation and platform-forwarding failures close importers/connections; partial platforms are rolled back, with serial cleanup even if rollback fails. Entry-owned import tasks cancel and await shutdown (Priority 1).
- Serialization: a complete poll, manual reset/reconnect, automatic recovery and importer reads use the serial lifecycle lock. Old collectors close before replacement. Session resets also clear record count and visible cached measurements.
- Configuration: duplicate ports are rejected before serial validation. Reconfigure changes the connection port while retaining original device/entity/statistics identity and entry-owned ledger. Existing update listener reloads the entry once after the change.
- Availability: current, power and live energy require successful polling, a connection, a nonmissing measurement and an actual packet at most 90 seconds old. Sync/connection diagnostics stay separate.
- Actions: registered in `async_setup`, retained without loaded entries, runtime schemas, `SupportsResponse.OPTIONAL`, exactly one explicit device target, domain/loaded-entry checks, translated validation/runtime errors. CSV empty data and write failures raise action errors.
- Diagnostics: public typed coordinator snapshot, importer progress snapshot and installed owlsensor/serialx versions. Changing collector counters no longer appear on each measurement entity.
- Status: enum keys with translated labels; record counts exposed as attributes.
- Identity investigation: the pinned protocol/library does not provide a verified immutable hardware identifier. Reconfiguration explicitly applies to the same adapter and freezes its original port-based identity; no speculative hardware-ID migration is performed.
- Validation: **125 tests passed on HA 2026.5.2 and 125 on HA 2026.10.4**, Python 3.14.2 in WSL. New coverage includes real integration-loader setup/unload, action validation/errors, poll/reset serialization, setup cancellation/rollback failure, freshness and reconfiguration continuity. Runtime Ruff checks, focused lint on new test modules, component JSON parsing and `git diff --check` pass.
- No physical adapter or production database tested; no commit, push or release performed for Priority 2.

## Priority 3 checkpoint (unreleased, 2026-11-15)

User explicitly requested Priority 3 work without a release. Manifest version remains
0.9.2. User subsequently authorized commit/push and CI verification, but explicitly prohibited
a new release. No tag or release will be created for this work.

- Added docs/quality-scale.md: an explicit audit of all twenty Bronze rules, evidence,
  exceptions and gaps. No tier/certification claim. Brand registration and complete
  config-flow branch coverage are outstanding.
- Retained owlsensor 0.7.2 and the pinned minimum/baseline pytest stacks; added pinned
  Ruff and a current HA 2026.11.1 runtime-smoke stack. CI and the local test runner
  reinstall the declared dependencies; separate environments prevent stale stack reuse.
- Minimum HA remains 2026.5.2 in HACS/README. Removed invalid `homeassistant` and
  `diagnostics` manifest keys (diagnostics is discovered by module). Added local
  metadata consistency checks and config-entry-only CONFIG_SCHEMA.
- Actual hassfest validation found/fixed unsupported integration icon metadata,
  obsolete action target filters and response YAML. Device selection now uses an
  explicit required single-device field; action response support stays registered in
  Python. Existing target.device_id automations remain accepted by runtime schemas.
- Removed import-time manifest disk reads and integration-version-as-device-firmware
  metadata, clearing the legacy device firmware field on entity registration. The release
  version is now only in manifest.json.
- Renamed CLAUDE.md to AGENTS.md and rewrote it to reflect the four entities, coordinator, energy helpers, durable
  statistics ledger, serialx, async cleanup, identity and available local validation.
  Added development/removal docs and corrected the diagnostic status description.
- Added loader tests using the actual coordinator, importer and platform forwarding,
  replacing serial I/O only. Tests cover enabled/disabled history, entity/device
  registration, fresh current state, connection-refusal retry/cleanup and config-flow
  duplicate/refusal handling. Existing real Recorder tests remain enabled.
- Added CI jobs for pinned lint, metadata consistency, hassfest and HACS. HACS comments
  are disabled; only the brands check is explicitly deferred. Remote CI will be checked after the authorized push. No local Docker runtime was
  available for the full HACS action.
- Validation: **132 tests pass on HA 2026.5.2 and 132 on HA 2026.10.4**. Actual
  hassfest from HA Core 2026.10.4 reports zero invalid integrations and no warnings.
  Runtime Ruff, metadata/JSON checks, Bash syntax and git diff --check pass.
- Latest stable HA at review time is 2026.11.1. Its real runtime imports, collector /
  coordinator constructors and action registration pass script/check_runtime.py.
  Full pytest on that version is NOT claimed: the latest published fixture package
  (0.13.375, pinned to HA 2026.10.4) fails importing the removed private HA logger
  helper `_clear_logger_overwrites`. An explicit HA override reproduced the failure;
  it was removed, and no HA-internal compatibility shims were added.

## Release 0.9.2 follow-up

- User reviewed 0.9.1 on a live device: 39,534 historical records collected, import completion before acknowledgement and subsequent live readings observed. No Recorder error shown; database commit and restart replay cannot be established from that log alone.
- Fixed the observed false-success defect: both coordinator connection and config validation reject a false return from the pinned library's `connect()`.
- 128 tests pass on each supported HA stack (2026.5.2 and 2026.10.4); runtime lint and diff checks pass.
- 0.9.2 includes the Priority 2 work above. Physical validation of this new version remains outstanding.

## Validation

- Python 3.14.2 in WSL Ubuntu 24.04.
- HA **2026.5.2**: **101 tests passed** (pytest-homeassistant-custom-component 0.13.331).
- HA **2026.10.4**: **101 tests passed**.
- CI matrix runs both supported test stacks with real owlsensor 0.7.2 installed. Global library test doubles removed.
- Real Recorder integration test verifies both imported energy statistics and unrelated live state recording in a temporary SQLite database.
- Runtime smoke check imports the integration/config flow and constructs the actual OWL collector without opening a serial port. This found and fixed undeclared pyserial imports (now serialx).
- Focused Ruff checks and git diff --check pass; final release checks still required.
- Physical CM160 hardware and the reporter's existing database have not been tested or repaired.

## Important operational decisions

- Select **Energy OWL CM160 (<port>) Estimated Energy** as the single combined source. Do not also select the live Energy entity for the same consumption period.
- Existing live entity identities remain unchanged. Old historical processor registry entries may be removed manually.
- Data is an estimate: the manufacturer's manual specifies one record per minute, but does not supply historical voltage or true power factor. The explicit convention is the rectangle `[timestamp, timestamp + 60s)`; no missing intervals are invented.
- Protocol live packets have no device UTC timestamp. TimestampedCollector observes successful live packet receipt, including identical successive readings; polling the cached value does not create a fresh sample.
- Configure the device clock to match HA's timezone. Ambiguous/nonexistent local DST minutes cannot be recovered without an offset and are deliberately skipped.
- First accepted historical minute/voltage is immutable. Historical minutes take precedence over any live coverage in that minute; replay never adds them twice. Corrections outside 35 days are ignored, preserving archived cumulative baselines.
- Keep HA .storage files in backups. Deleting/resetting an entry's ledger resets its accounting baseline. A Recorder purge/rollback can be repopulated from the ledger on restart.
- Recorder API submission is queued, not a commit confirmation; durability comes from the replayable atomic ledger. No direct SQL or state-chain manipulation is used.
- Snapshot, reset, reconnect, disconnect and acknowledgement operations share a serial lifecycle lock. A generation change invalidates stale snapshots before reconnect/reset awaits.

## Release steps

1. Complete final checks on both HA stacks; inspect the staged diff.
2. Commit all requested work and release notes with the repository's established author identity.
3. Create annotated tag v0.9.2 on that commit; push main and the tag without force.
4. Publish GitHub release v0.9.2 using RELEASE_NOTES.md and verify the release/tag target.
5. Record final commit SHA and release URL here or in the final response.

## Publishing access

GitHub authentication was restored by the user and verified with GitHub CLI and a dry-run Git push. Publish only after final checks; use main and annotated tag v0.9.2 without force. Repository author identity is Pascal Brunot, matching existing commits.

## Sources added during completion

- Manufacturer minute-record specification: https://www.theowl.com/files/8514/0074/5366/CM160-001UK_UM_R7.pdf
- Pinned owlsensor 0.7.2 parser and constructor inspected from the installed package; naive history timestamps and cached get_current behavior verified.

---

# Original review and historical checkpoints (superseded by current status above)

## Resumption context

- User requested a full review against Home Assistant guidelines and open issues, then authorized: remove the historical-state-writing path and use HA statistics APIs exclusively.
- User explicitly requested this plan for resumption. Original reviewed commit: `40cd7de` (v0.9.0).
- The scoped statistics-only fix is implemented; see final validation below. Broader Priority 1 work remains open. Do not discard working-tree changes.
- No commit, push, release, deployment, or GitHub comment has been made.
- HA runs on another machine. Local selected Python is 3.10.11, Home Assistant is absent, and pytest previously failed during conftest import with ModuleNotFoundError. The integration uses Python 3.12+ type alias syntax. CI currently selects Python 3.13 with unpinned pytest-homeassistant-custom-component.

## Immediate restart checklist

1. Inspect `git status --short` and the full diff. Finish the in-progress implementation before declaring success.
2. Inspect `statistics.py`, setup/unload in `__init__.py`, and coordinator reset/completion paths. Confirm importers register BEFORE first refresh so the device buffer is not cleared prematurely.
3. Add `tests/test_statistics.py` covering real statistics ID/API validation, disabled imports, failed submission and retry, empty history completion, single task per sync, reset/reconnect generation, unload cancellation, and unrelated Recorder state writes.
4. Update existing setup tests to account for entry-owned importer lifecycle. Ensure sensor tests expect four entities and no historical processor. Old historical backfill tests were removed from the live energy sensor suite and must be replaced with importer tests.
5. Remove obsolete historical dependency test doubles/imports and processor translation keys. Verify these edits finished.
6. Validate JSON, parse changed Python with a compatible interpreter, run pytest on supported HA/Python, and run `git diff --check`. Do not claim tests passed if unavailable.
7. Check runtime code contains no historical state writer, HistoricalState, PollUpdateMixin, historical library dependency, or direct SQL/state-table access.
8. Update this file with final implementation and validation results.

## Open issue #5: two distinct errors

Issue: https://github.com/PBrunot/energy_owl_hacs/issues/5
Title: SQL failure makes all Home assistant statistics fail. Only open issue found, no comments at review time.

### Confirmed invalid statistic ID

`energy_sensor.py` previously generated `energy_owl:CM160--dev-ttyUSB0-v2_energy`. HA requires lowercase slug components with a colon separator; uppercase and hyphens are invalid. Fix only external statistic identity, preserving entity unique IDs.

HA validates the ID before enqueuing the import. The rejected call therefore does not itself explain the later Recorder states-table transaction failure.

### Probable Recorder conflict

`ha_historical_sensor.py` called a third-party historical state writer. Allowed v2 dependency versions manipulate Recorder state chains; this matches the reported StaleDataError category, but the reporter's exact HA/library versions and reproduction are still needed to confirm causation.

Upstream removed state writing in v3 because direct state-chain manipulation was fragile. Current upstream also no longer exports PollUpdateMixin. Raising the dependency minimum alone is insufficient. Chunk delays do not guarantee transaction safety.

Resolution: delete the historical processor and its dependency. Import historical statistics exclusively via `async_add_external_statistics`. Keep live measurements on ordinary HA sensor updates.

## Statistics-only implementation

- Deleted `ha_historical_sensor.py`; removed processor creation from `sensor.py` and historical dependency from manifest.
- Added entry-owned `statistics.py` importer using HA statistics API, mean_type NONE, unit_class energy, valid slug IDs, separate external historical energy source.
- Removed historical import scheduling and statistics writes from live `energy_sensor.py`; moved hourly aggregation helper to statistics module.
- Setup creates/registers importer before first refresh, starts subscription after platform setup, and closes importer on failure/unload.
- Coordinator tracks sync generation and resets completion/cursors on reconnect/reset; live-reading fallback no longer clears history before registered importers finish.
- Suppressed automatic recovery while an importer is unfinished, preventing recovery from discarding a failed import's buffer.
- Import failures log and retry on later updates. Completion means queued, not committed. Empty history can complete without submitting statistics.
- README, tests and translation cleanup completed; obsolete historical processor imports and dependency removed.

### Implementation decisions and limits

- External historical statistics remain separate from the live Energy sensor's recorder statistics; no automatic history merge.
- Existing live entity unique IDs are preserved. Old processor registry entries may remain orphaned and need user removal/documentation.
- Existing hourly average-current/full-hour estimation is retained for this scoped fix, pending protocol validation.
- No durable import checkpoint, snapshot, or cumulative offset exists yet. Submission is not a commit acknowledgement, and device acknowledgement after submission retains the existing data-loss window on crash.
- Repeated/overlapping device history across sessions still needs a durable baseline policy.
- Addressed: importer requests strict historical reads; collector failure is not treated as empty history.
- Addressed partly: nonfinite/negative currents are skipped. Invalid/mixed timestamps still require broader protocol validation.
- Addressed: is_processing_complete checks current generation, including before listener callbacks run.

## Full component review findings and follow-up work

### Priority 1: safety and correctness

1. Invalid external IDs: fix with stable slug, validate through actual HA API, preserve entity identity.
2. Remove direct historical state writes and dependency entirely.
3. Historical option previously disabled only processor creation, while energy sensor still imported. One entry-owned importer must honor the option for all imports.
4. Coordinator waited for pushers, but historical entity never called notify_pusher_complete. Ensure complete/empty/disabled paths release the device without relying on entity enablement.
5. Old batch errors were swallowed while later successful chunks advanced timestamps past failed records. Avoid partial chunk advancement and false completion.
6. Old backfill flag was set before fetch/validation/submission, preventing retries until reload. Track submission success accurately; retain/cancel tasks on unload.
7. Real-time energy integrates new current across missing-data gaps. Reset baseline on disconnect, no current, restore, and stale samples; use device timestamps and explicit maximum gap.
8. Historical helper treats every populated hour as a complete hour. Establish CM160 record semantics (interval averages vs instantaneous samples); integrate documented duration, split UTC hours, deduplicate, handle missing coverage and DST.
9. Separate historical/live statistic series need explicit Energy Dashboard documentation and an overlap/continuity policy. Do not merge series casually.
10. Current times voltage assumes unity power factor. Document estimated active power/energy and present-day voltage used for historical estimates.
11. Persist snapshots/checkpoints and cumulative offsets; define deterministic overlapping/replayed imports and restart recovery before claiming reliable long-term ingestion.

### Priority 2: HA lifecycle and structure

- Keep setup/unload in __init__, device acquisition/sync in coordinator, statistics import in statistics.py, timestamp integration in a future energy.py, action handling in services.py.
- Existing strengths: config/options flow, typed runtime_data, shared coordinator, first refresh, platform forwarding, translation keys, appropriate sensor units/classes, diagnostics, disabled diagnostic entity.
- Setup failure can leave collector/tasks alive; clean up partially initialized connections and platform forwarding failures.
- Old historical removal omitted superclass cleanup and cancelled without awaiting; new entry-owned tasks must have deterministic cancellation.
- Serialize collector polling, manual clear/reconnect, automatic recovery and importer snapshots. Close old collectors before replacement.
- Reset all sync/session state consistently on reconnect and clear, including collection cursor, completion timer, importer state and acknowledgement state.
- Duplicate config check currently follows serial validation. Check uniqueness first to avoid disturbing existing connections. Add reconfigure flow for changed ports.
- Availability uses last_update_success OR connected, masking failures. Use fresh successful measurements and separate connection/sync diagnostics.
- Register actions in async_setup, keep registered without loaded entries, validate target/domain/loaded state, add runtime schemas and translated ServiceValidationError/HomeAssistantError. Use SupportsResponse enum, not True.
- Deliberately support/reject multiple targets; do not silently use first device. Prefer target hierarchy matching operation; avoid implicit default target.
- CSV export currently logs failures while returning success; propagate useful action errors.
- Diagnostics should expose a public typed coordinator snapshot, include dependency versions and import progress, and avoid private-field coupling.
- Move changing debug counters off every measurement entity to diagnostics to reduce Recorder attribute churn.
- Convert textual status into enum keys with translated labels; counts belong in attributes.
- Port-based identity changes when ports change; investigate hardware identity and migration preserving existing entities.

### Priority 3: packaging, documentation and validation

- Do not claim Bronze quality-scale compliance yet. Audit applicable rules explicitly; custom HACS integration is not automatically certified.
- Pin tested library versions and a reproducible test stack. Unbounded dependencies can cross incompatible APIs.
- Align minimum HA: hacs.json advertises 2024.11.0 while manifest/README advertise 2026.5.2. Validate supported metadata with hassfest/HACS checks.
- CLAUDE.md describes obsolete single-sensor architecture and dependency versions; refresh it.
- Remove manifest/version disk-read coupling when appropriate; do not report integration version as hardware firmware.
- Existing tests mock statistics API and historical library, hiding reported failures. Correction to initial review: current HA entity metaclass rewrites _attr fields into __attr storage; double-underscore test assertions were not inherently invalid. Tests now inspect public instance properties instead, avoiding this internal representation.
- Add HA integration-loader setup tests rather than only directly invoking setup with platform forwarding mocked.
- Test minimum and current supported HA releases with compatible Python; add hassfest, HACS validation and lint checks.

## Verification required before release

- Real Recorder: import history while an unrelated sensor records live states, await Recorder queue processing and verify both statistics and states.
- Valid IDs for Linux, Windows and by-id ports, metadata unit_class/mean_type, exact UTC hour boundaries.
- Option disabled, zero history, malformed/nonfinite records, failed submission and retry, no false acknowledgement.
- Reconnect/reset during import, reload/unload cancellation, disabled entities, multiple entries, setup failures.
- Energy tests: gaps, partial hours, irregular intervals, duplicate timestamps, DST, overlapping history, cumulative continuity after restart.
- Obtain reporter's exact versions and before/after logs on HA host. Do not modify their database or claim existing corruption was repaired.

## Sources

- HA quality scale: https://contributors.home-assistant.io/core/quality-scale/rules/
- HA fetching data: https://contributors.home-assistant.io/core/integrations/fetching-data/
- HA sensors: https://contributors.home-assistant.io/core/entities/sensor/
- HA actions: https://developers.home-assistant.io/docs/dev_101_services/
- HA manifest: https://contributors.home-assistant.io/core/integrations/manifest/
- HA statistics implementation (development branch; verify supported release too): https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/recorder/statistics.py
- Historical library rationale: https://github.com/ldotlopez/ha-historical-sensor/issues/18
- Historical library current exports: https://raw.githubusercontent.com/ldotlopez/ha-historical-sensor/main/homeassistant_historical_sensor/__init__.py

## Latest checkpoint

- Added tests/test_statistics.py for valid Linux/Windows/by-id statistic IDs, queued submission and acknowledgement, submission failure/retry, read failure, empty history, generation changes, duplicate task prevention, and unload cancellation.
- Updated existing sensor/energy tests and removed historical dependency test doubles. Full Recorder integration coverage and setup lifecycle regression coverage remain outstanding.
- JSON validation passed for all component JSON files.
- Python 3.10 AST parsing passed for component/test files except integration __init__.py, which contains the existing Python 3.12 type alias syntax and needs validation on supported Python.
- pytest was retried and still cannot collect: Home Assistant is not installed. No runtime or test-pass claim is justified.
- Fixed trailing blank lines reported by diff check; rerun diff check at resumption.
- User's latest request was to save the plan for resumption; this checkpoint records work without a commit or release.

## Priority 1 status (implementation continuation)

| Item | Status |
| --- | --- |
| 1 Valid statistics IDs | Implemented and regression tested through the real Recorder API |
| 2 Remove historical state writer | Implemented; dependency and processor removed |
| 3 Honor import option | Implemented; entry-owned importer only created when enabled |
| 4 Device completion handshake | Implemented and tested; retries acknowledgement and handles empty history |
| 5 Failed chunk advancement | Removed by deleting chunk/state writer; importer submits one complete statistics batch |
| 6 Premature completion/task lifecycle | Implemented; marks submission after API accepts, retries failures, cancels/awaits unload |
| 7 Live energy gaps | OPEN; outside selected statistics-only fix |
| 8 Historical interval accuracy | OPEN; full-hour average retained, malformed records filtered |
| 9 Historical/live continuity | PARTIAL; separate external source documented, unified continuity not implemented |
| 10 Power/voltage estimation assumptions | Documented; physical measurement limitation remains |
| 11 Durable snapshots/checkpoints/offsets | OPEN; no crash-safe recovery or overlap baseline |

Tests are running in WSL using Python 3.14.2 and HA 2026.10.4. The first run reported 81 passing tests and 7 failures in test assertions that inspected HA metaclass internals. Those assertions have been replaced with public entity-property checks; final rerun pending.

## Validation and continuation result

- Statistics-only issue fix implemented. No direct historical state writer or historical-sensor package remains in runtime code/tests.
- Entry-owned importer is registered before first refresh, independent of enabled sensor entities, honors the historical option, validates external metadata/IDs, retries failures, and cancels/awaits its task on unload.
- Acknowledgement failure is retryable without resubmitting already queued statistics in the same sync generation. Reset/disconnect invalidates outstanding snapshots and old completion state.
- Real Recorder integration regression uses a temporary SQLite database, validates the actual API and reads back both imported statistics and an unrelated live sensor's latest recorded state.
- Python/HA validation environment: WSL Ubuntu 24.04, Python 3.14.2, Home Assistant 2026.10.4, pytest-homeassistant-custom-component 0.13.375. Test environment is /home/pascal/.cache/energy-owl-test-env (an earlier /tmp environment disappeared between WSL sessions).
- Test dependency pinned and CI Python updated to 3.14 to match the tested stack; run_tests.sh now reads requirements-test.txt.
- Minimum advertised HA 2026.5.2 and physical serial hardware are not validated by these tests. No production database repair, release or deployment performed.
- Priority 1 items 7, 8 and 11 remain OPEN; item 9 has documentation but no unified continuity; item 10 is documented rather than physically corrected. These require separate implementation work.

Final checks: **86 tests passed** in 5.37 seconds on the environment above. Focused Ruff checks passed for statistics.py and test_statistics.py. Component JSON parsed successfully; git diff --check passed (line-ending conversion warnings only).
