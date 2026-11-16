# Repository guidance

## Project

Energy OWL CM160 is a HACS custom integration for a USB serial energy monitor.
Minimum Home Assistant is 2026.5.2, declared in hacs.json and README.md.
This repository does not claim Home Assistant quality-scale certification.
See docs/quality-scale.md for the rule audit and outstanding gaps.

## Architecture

- `__init__.py`: config-entry setup/unload, typed runtime_data, action registration.
- `coordinator.py`: serial connection, polling, history batches and local buffer cleanup,
  manual reset/reconnect, recovery, public typed diagnostics snapshot.
- `collector.py`: subclass of the pinned owlsensor parser; records UTC receipt
  timestamps for actual live packets, including identical consecutive values.
- `energy.py`: finite measurements, voltage conversion, one-minute historical
  intervals, device-local timezone/DST normalization, bounded live integration.
- `statistics.py`: entry-owned importer and durable EnergyLedger in atomic HA Store;
  combined history/live external statistics via async_add_external_statistics.
- `services.py`: explicit single-device actions, schemas, translated action errors.
- `sensor.py`: creates current, power, cumulative live energy and disabled diagnostic
  sync-status entities. Per-entity implementations live in their own modules.
- `config_flow.py`: port validation, duplicate prevention, options, reconfiguration.
- `diagnostics.py`: dependency versions and public coordinator/importer snapshots.

## Invariants

Never write historical states or modify Recorder tables directly. Save the ledger
before discarding imported records from the local collector buffer. This cleanup
sends no device acknowledgement; owlsensor handles protocol flow control.
Recorder submission is queued, not a commit confirmation; replay provides recovery. History replaces overlapping live estimates;
first accepted historical voltage is retained. Do not invent missing intervals.

Live integration uses receipt timestamps and a 90-second maximum gap. Restore,
disconnect and session changes reset its baseline. Historical timestamps use HA's
configured timezone; ambiguous/nonexistent local DST minutes are skipped.
Power/energy estimates assume unity power factor and documented voltage settings.

Serialize collector access with the lifecycle lock. Use unlocked helpers only while
holding it. Close old collectors before replacement. `connect()` returns a boolean:
a false return is a connection failure, even if no exception was raised.
Collector disconnect is async and must be awaited; synchronous collector reads run
in the executor. Cancel and await importer tasks on teardown.

Device/entity identity uses `CM160-{sanitized_original_port}-v2`. Reconfigure changes
the connection port for the same adapter and freezes `identity_port`, preserving
statistics and ledger continuity. Do not invent a hardware serial number or report
the integration release as hardware firmware. Release version lives only in manifest.

## Validation

Use Python 3.14. See docs/development.md for commands and pinned test stacks.
Real owlsensor 0.7.2 and serialx are installed; patch serial I/O per test, never replace
packages globally. HA entity tests assert public properties and registry/state data.
Real Recorder tests use a temporary database; loader tests exercise actual platform
forwarding and coordinator setup. HA production runs on another machine; local tests
are available in WSL and do not need access to production.

CI runs minimum/baseline full tests, a current HA runtime smoke check, pinned Ruff, local metadata
checks, hassfest and HACS validation. HACS brand registration is explicitly deferred.
Run relevant tests and git diff --check before committing. Do not release or publish
unless the user explicitly requests it.
