# Energy OWL CM160 — Home Assistant Integration

[![HACS Badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![Version](https://img.shields.io/github/v/release/PBrunot/energy_owl_hacs)](https://github.com/PBrunot/energy_owl_hacs/releases)
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
| Current | A | Measurement | Real-time current from the CM160 (~15 s interval) |
| Power | W | Measurement | Current × configured voltage, updated in sync with current |
| Energy | kWh | Total increasing | Live cumulative estimate; restored across restarts, skips stale samples and gaps. See the combined statistics source below. |
| Historical Data Status | — | Diagnostic (disabled) | Shows sync progress: `Starting sync` → `Syncing (N records)` → `Complete` |

> **Note**: During the initial historical data transmission (which can take 5–10 minutes), the Current and Power sensors show no value. The Historical Data Status sensor reflects progress. Real-time updates begin after the sync completes.

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

Fired once when the CM160 finishes transmitting its historical memory and transitions to real-time mode.

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

If the device transitions to historical-data-complete state but real-time readings do not arrive within 5 minutes, the coordinator automatically disconnects and reconnects (up to 3 attempts). Progress and outcome are reported via HA persistent notifications. Use `force_reconnect` for manual recovery if automatic recovery is exhausted.

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
- Added atomic storage before acknowledgement and idempotent startup replay.
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

Version 0.9.1 uses HA's statistics API exclusively. It removes the historical state
writer and its dependency. Old Historical Data Processor registry entries may be
removed manually. Live entity IDs remain unchanged; the combined statistics source
uses the valid `energy_owl:cm160_<port>_v2_energy` form.

The entry owns the importer, including when sensor entities are disabled. Validated
minute records and live intervals are saved atomically under HA's `.storage` before
statistics are queued or device history is acknowledged. If storage fails, the device
buffer is retained. If Recorder submission fails or the process exits before commit,
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
Priority 2/3 improvements. Physical meter accuracy and gaps without measurements
cannot be reconstructed by the integration.
