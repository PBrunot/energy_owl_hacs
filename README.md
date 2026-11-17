# Energy OWL CM160 — Home Assistant Integration

[![HACS Badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![Version](https://img.shields.io/github/v/release/PBrunot/energy_owl_hacs)](https://github.com/PBrunot/energy_owl_hacs/releases)
[![Tests](https://github.com/PBrunot/energy_owl_hacs/actions/workflows/tests.yml/badge.svg)](https://github.com/PBrunot/energy_owl_hacs/actions/workflows/tests.yml)
[![Validation](https://github.com/PBrunot/energy_owl_hacs/actions/workflows/validate.yml/badge.svg)](https://github.com/PBrunot/energy_owl_hacs/actions/workflows/validate.yml)
[![License](https://img.shields.io/github/license/PBrunot/energy_owl_hacs)](LICENSE)
[![Issues](https://img.shields.io/github/issues/PBrunot/energy_owl_hacs)](https://github.com/PBrunot/energy_owl_hacs/issues)

Home Assistant custom integration for the **OWL CM160** USB energy monitor. Provides real-time current, power and energy sensors, automatic historical data backfill, and full Energy Dashboard support — no helper entities needed.

![Energy OWL CM160 Device](https://github.com/user-attachments/assets/75d97f4f-463f-4380-8232-92ce58faa015)

## Requirements

| Requirement | Minimum version |
|-------------|-----------------|
| Home Assistant | 2026.5.2 |
| [owlsensor](https://github.com/PBrunot/owlsensor) | 0.7.2 (installed automatically) |
| Hardware | OWL CM160 connected via USB-to-serial adapter |

## Installation

### Via HACS (recommended)

1. Open HACS → Integrations.
2. Click the three-dot menu → **Custom repositories**.
3. Add `https://github.com/PBrunot/energy_owl_hacs` — category: **Integration**.
4. Search for **Energy OWL** and click **Install**.
5. Restart Home Assistant.

### Manual

1. Download the latest release from [GitHub Releases](https://github.com/PBrunot/energy_owl_hacs/releases).
2. Copy `custom_components/energy_owl/` into your HA config's `custom_components/` directory.
3. Restart Home Assistant.

## Removal

Remove the entry from **Settings > Devices & Services > Energy OWL > Delete**.
Then uninstall it through HACS (or remove `custom_components/energy_owl/` for a
manual installation) and restart Home Assistant. Remove the Energy Dashboard source
if you no longer need it. Existing Recorder history and the entry's `.storage`
energy ledger are not deleted by this integration. Back them up before any manual
cleanup; deleting the ledger resets its accounting baseline if restored later.

## Setup

### Hardware connection

1. Plug the CM160 into a USB port on the machine running Home Assistant.
2. Note the serial port path:
   - **Linux**: `/dev/ttyUSB0`, `/dev/ttyUSB1`, … — run `dmesg | grep tty` after plugging in to confirm.
   - **Windows / Windows host with VM**: `COM3`, `COM4`, … — ensure the USB device is forwarded to the VM.
   - **Linux permissions**: the HA process user must be in the `dialout` group (`sudo usermod -aG dialout <user>`).

### Adding the integration

1. Go to **Settings → Devices & Services → Add Integration**.
2. Search for **Energy OWL** and enter the serial port path (e.g. `/dev/ttyUSB0`).
3. HA validates the connection before saving. If it fails, check the port path and permissions.

### Options (post-setup)

Open the integration's **Configure** menu to adjust:

| Option | Default | Description |
|--------|---------|-------------|
| Import historical data | Enabled | Enables a durable combined history/live estimated energy statistics source through HA Recorder's API. Disable to reduce database load if past data is not needed. |
| Voltage entity | _(none)_ | HA sensor entity providing live grid voltage (e.g. from a smart meter). Takes priority over the fixed voltage below. |
| Default voltage | 230 V | Grid voltage used for power and energy calculations when no voltage entity is set. Typical: 230 V (Europe), 120 V (North America). |

## Entities

All entities belong to a single **Energy OWL CM160 (`<port>`)** device.

| Entity | Unit | Class | Notes |
|--------|------|-------|-------|
| Current | A | Measurement | Real-time current from the CM160; coordinator polls every 30 s |
| Power | W | Measurement | Current × configured voltage, updated in sync with current |
| Energy | kWh | Total increasing | Live cumulative estimate; restored across restarts, skips stale samples and gaps. See the combined statistics source below. |
| Historical Data Status | - | Diagnostic (disabled) | Translated `starting`, `syncing`, `complete`, `disconnected` states; record count in attributes |

> **Note**: Historical and live packets can arrive interleaved. Current and Power update as soon as fresh live packets arrive, independently of history import. History is imported in bounded two-minute batches silently. After initial processing, Historical Data Status stays `complete` during ordinary minute updates. `syncing` is reserved for a substantial recovery: at least 60 previously missing distinct historical minutes, each more than five minutes old. One notification is sent when that recovery settles. `complete` does not confirm a Recorder commit.

## Energy Dashboard

The **Energy** sensor remains a live-only cumulative estimate with its existing entity ID.
With **Import historical data** enabled, select **Energy OWL CM160 (<port>) Estimated Energy**
(the statistic ID begins `energy_owl:cm160_`) for a single continuous history/live
source. Do not select both sources for the same meter: their live periods overlap.
When the option is disabled, select the live **Energy** sensor instead; the combined
source stops receiving updates until the option is enabled again.

The combined source records each observed historical minute and bounded live sample
interval exactly once. Historical minutes replace overlapping live estimates; repeated
downloads retain the first accepted voltage estimate for a minute. Earlier imports
recompute subsequent cumulative sums, so the live continuation uses the same baseline.
A restart reloads and replays the durable ledger before attempting a new device import.

![Home Assistant Integration](https://github.com/user-attachments/assets/20e1dcac-2248-4dd1-9a46-9dbcfda59633)

## Services

All actions require exactly one Energy OWL device via `target: device_id`. Multiple targets and implicit defaults are rejected. Actions remain registered when entries are unloaded and report an error for an unloaded target. CSV export reports errors when no records are available or the file cannot be written.

Use **Reconfigure** on the integration entry to change the serial port for the same CM160 adapter. Entity IDs, device identity, the combined statistics source and the stored energy ledger are retained. The protocol does not expose a verified hardware serial number; do not use reconfiguration to substitute a different meter.

Current, power and live energy become unavailable when polling fails or the latest actual live packet is older than 90 seconds. Connection and history-sync progress remain available in diagnostics. The history status sensor uses translated `starting`, `syncing`, `complete` and `disconnected` states; record counts are attributes.

### `energy_owl.get_historical_data`

Returns stored historical records as a service response.

```yaml
service: energy_owl.get_historical_data
target:
  device_id: "your_device_id"
data:
  clear_existing: false   # set true to reset and re-collect before returning
```

Response fields: `historical_data_count`, `historical_data_complete`, `records` (list of `{timestamp, current}`).

### `energy_owl.clear_historical_data`

Discards the in-memory historical buffer and resets the sync state.

```yaml
service: energy_owl.clear_historical_data
target:
  device_id: "your_device_id"
```

### `energy_owl.export_historical_data_csv`

Exports historical records to a CSV file in the HA config directory.

```yaml
service: energy_owl.export_historical_data_csv
target:
  device_id: "your_device_id"
data:
  filename: "energy_owl_export.csv"   # optional; defaults to energy_owl_export_<device_id>.csv
```

The CSV contains two columns: `timestamp` (ISO 8601) and `current` (amperes).

### `energy_owl.force_reconnect`

Disconnects and reconnects to the CM160. Use when the device appears stuck or unresponsive.

```yaml
service: energy_owl.force_reconnect
target:
  device_id: "your_device_id"
```

## Events

### `energy_owl_historical_data_complete`

Fired once after a substantial recovery: at least 60 previously missing distinct
historical minutes, each more than five minutes old, have been persisted and queued.
Recovery completes after two minutes without older-history activity and no older
records remain pending in the local buffer, checked on each poll. Ordinary minute
updates, duplicates and smaller backfills are imported silently without firing this
event or changing the status back to `syncing`. Counts accumulate across contiguous
recovery batches and reset once that activity settles.
It does not confirm that Recorder has committed the import or that a device command
was sent. The event's `device_id` is a legacy port-derived identifier,
not the Home Assistant device-registry ID used by action targets.

```yaml
event_type: energy_owl_historical_data_complete
event_data:
  device_port: /dev/ttyUSB0
  device_id: CM160-<port_safe>
```

Example automation:

```yaml
automation:
  - alias: "Notify when CM160 historical sync completes"
    trigger:
      platform: event
      event_type: energy_owl_historical_data_complete
    action:
      service: notify.mobile_app
      data:
        message: "Energy OWL historical data sync completed."
```

## Automatic Recovery

If the USB serial connection closes, the coordinator retries the configured port on subsequent polls until it becomes available. It also reopens a serial connection that delivers no packets for five minutes, even while history is being collected.

If packets are still arriving but real-time readings do not resume within five minutes after history completes, the coordinator attempts automatic recovery up to three times. Progress and outcome are reported via HA persistent notifications. Use `force_reconnect` for manual recovery if these attempts are exhausted.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Integration fails to add | Wrong port or permission denied | Confirm port with `dmesg \| grep tty`; add user to `dialout` |
| No sensor values after setup | Historical sync in progress | Wait 5–10 minutes; watch Historical Data Status |
| Current/Power stuck at unavailable | Device disconnected or port changed | Check USB connection; use `force_reconnect` service |
| Energy Dashboard shows no history | Historical import disabled, or first sync not yet complete | Enable **Import historical data** in options; wait for sync |
| No data after sync completes | Realtime transition bug (fixed in owlsensor 0.7.2) | Ensure owlsensor ≥ 0.7.2 is installed |

### Debug logging

Add to `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.energy_owl: debug
    owlsensor: debug
```

## Version History

### v0.9.6

- Recover automatically after a USB disconnect by retrying the configured serial
  port until it returns. Reopen a silent port after five minutes without packets,
  even while historical data is being collected.

### v0.9.5
- Separate recovery status and notifications from internal import batches. Notify once for substantial newly recovered history; import routine minute updates silently.
- Retain a current, unfinished historical minute and its buffer suffix until it can be imported, including when no further packets arrive.
- Keep read/export actions from changing the importer's cleanup prefix while storage is in progress.

### v0.9.4
- Import bounded history batches during continuous streaming instead of waiting indefinitely for silence.
- Preserve save-before-cleanup ordering and retry failed persistence without discarding pending records.
- Add continuous-stream regression coverage for duplicate minutes, storage failure and disabled history import; clarify batch status and event semantics.

### v0.9.3
- Keep collecting history when the device interleaves historical and live packets; complete batches after two minutes without new history and reopen collection for late records.
- Preserve records arriving during persistence; discard only the imported local buffer prefix after durable storage and Recorder submission.
- Correct logs and documentation: local buffer cleanup sends no device acknowledgement and does not switch the device to live mode.
- Preserve live energy integration across history batches; add regression coverage using packets from a real CM160 log.
- Correct integration metadata and add pinned lint, metadata, hassfest, HACS and current-runtime CI checks.

### v0.9.2
- Reject failed serial connections instead of reporting false success, including during configuration.
- Serialize polling and serial lifecycle operations; clean up cancelled and partially failed setup.
- Add port reconfiguration while preserving device, entity, statistics and ledger identities.
- Require one explicit device target for actions, validate loaded entries and propagate export failures.
- Use fresh live measurements for availability; expose public diagnostics and translated sync status.

### v0.9.1
- Removed historical state-table writes; historical and live energy now share a durable external statistics source.
- Corrected history from full-hour extrapolation to observed one-minute intervals, including duplicate, overlap and DST handling.
- Added live packet receipt timestamps, stale-data/gap protection and safe restored baselines.
- Added atomic storage before local history cleanup and idempotent startup replay.
- Fixed serial exception imports for owlsensor's serialx dependency; aligned HACS minimum HA to 2026.5.2.

### v0.9.0
- Added `icons.json`: integration tile shows `mdi:meter-electric`; service icons added.
- README rewritten with accurate feature documentation.

### v0.8.9
- Require `owlsensor>=0.7.2` (fix: realtime data never arriving due to false EOF on inter-packet gaps).

### v0.8.8
- `VERSION` constant derived from `manifest.json` to keep firmware string in sync.

### v0.8.7
- Require `owlsensor>=0.7.1` (fix: `CONTINUE_REQUEST`/`START_REQUEST` type error with serialx 1.7.2+).

### v0.8.6
- Require `owlsensor>=0.7.0` (serialx migration, non-POSIX 250 000 baud support).
- Minimum HA version raised to 2026.5.2.

### v0.8.5
- Energy sensor now uses `RestoreSensor`: cumulative kWh counter survives HA restarts.

### v0.8.0
- Added **Power sensor** (W) derived from current × voltage.
- Added **Energy sensor** (kWh) with historical back-fill via HA recorder API.
- Added voltage configuration: fixed default or live HA entity.
- Added HA diagnostics support.
- Energy Dashboard integration is now native — no helper entities required.

### v0.6.x — v0.7.x
- Automatic recovery for stuck devices (up to 3 reconnect attempts with HA notifications).
- `export_historical_data_csv` and `force_reconnect` services added.
- Multiple serial communication reliability fixes tracking `owlsensor` 0.6.x releases.
- Historical data pusher framework for reliable long-term statistics ingestion.

### v0.5.0
- Historical data collection: CM160 internal memory back-filled on first connect.
- Historical Data Status diagnostic sensor.
- `get_historical_data` and `clear_historical_data` services.
- `energy_owl_historical_data_complete` event.

### v0.1.x
- Initial releases: real-time current sensor, HACS support.

## Contributing

1. Fork the repository.
2. Create a feature branch.
3. Add or update tests in `tests/` where applicable.
4. Submit a pull request.

## License

MIT — see [LICENSE](LICENSE).

## Acknowledgements

- [owlsensor](https://github.com/PBrunot/owlsensor) — Python library for CM160 serial communication.
- Home Assistant community for integration standards and the `homeassistant-historical-sensor` library.

---

**Need help?** [Open an issue](https://github.com/PBrunot/energy_owl_hacs/issues).

## Historical import safety and measurement assumptions

Since v0.9.1, the integration uses HA's statistics API exclusively. It removes the historical state
writer and its dependency. Old Historical Data Processor registry entries may be
removed manually. Live entity IDs remain unchanged; the combined statistics source
uses the valid `energy_owl:cm160_<port>_v2_energy` form.

The entry owns the importer, including when sensor entities are disabled. Validated
minute records and live intervals are saved atomically under HA's `.storage` before
statistics are queued or imported records are removed from the local collector
buffer. If storage fails, the local buffer is retained. Buffer cleanup sends no
command to the device and does not control its switch to live packets; the pinned
owlsensor parser handles protocol START/CONTINUE requests independently. Records
arriving during persistence are preserved for the next batch. If Recorder submission fails or the process exits before commit,
the durable ledger is replayed on the next update/startup. Submission is not itself a
commit acknowledgement. Do not delete the integration's storage files unless you
intend to reset its accounting baseline; include them in HA backups.

The [CM160 manual](https://www.theowl.com/files/8514/0074/5366/CM160-001UK_UM_R7.pdf)
specifies one stored record per minute. We estimate that minute's energy using a
rectangle over `[timestamp, timestamp + 60 seconds)`, rather than expanding a lone
sample to a full hour. Missing minutes contribute no invented consumption. Identical
duplicates collapse; conflicting duplicates fail the batch. Invalid/nonfinite records
are skipped with a warning. Live packet receipt timestamps (the protocol provides no
UTC timestamp for live packets) are used with a 90-second maximum sample gap. Polling
the same cached packet adds no energy; disconnects, stale data and restarts reset the
integration baseline. The first sample after any gap adds no energy.

Device history has local wall-clock timestamps without an offset. The device clock
must match HA's configured timezone. Ambiguous and nonexistent DST wall-clock minutes
are skipped rather than guessed; explicitly offset timestamps remain distinguishable.
UTC intervals are split across minute/hour boundaries before aggregation.

Current times voltage assumes unity power factor: these are **estimated active power
and energy**, not revenue-grade measurements of real power. Historical estimates use
the configured fixed voltage because historical voltage is unavailable. Live estimates
use a valid selected voltage sensor (converted to volts), otherwise the fixed voltage.
The ledger retains 35 days of minute detail for the device's 30-day replay window and
compacts older data into immutable hourly totals. Older replayed minutes cannot add
energy twice. Late corrections outside that window are deliberately ignored.

See [action plan.md](action%20plan.md) for implementation status and remaining
follow-up work and validation limits. Physical meter accuracy and gaps without measurements
cannot be reconstructed by the integration.

## Development and validation

The latest published release is **v0.9.2**. The default branch also contains
unreleased packaging, metadata, documentation and validation improvements.

Validation on this branch: **132 tests pass on HA 2026.5.2 and 2026.10.4**.
HA 2026.11.1 passes a runtime smoke check; its full pytest suite awaits a compatible
pytest-homeassistant-custom-component release. Local hassfest validation passes.
CI additionally runs HACS validation, with brand registration explicitly deferred.

See [development instructions](docs/development.md) for the pinned test stacks,
metadata checks and CI validation, and [AGENTS.md](AGENTS.md) for contributor guidance. This custom integration makes no Bronze or other
Home Assistant quality-scale certification claim; see the [rule audit](docs/quality-scale.md).
