# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Home Assistant Custom Component (HACS) integration for the Energy OWL CM160 energy meter. It allows Home Assistant to connect to a CM160 device via serial port and retrieve electrical current measurements.

## Repository Structure

```
custom_components/energy_owl/
├── __init__.py          # Integration setup and lifecycle management
├── sensor.py            # Sensor entity implementation for current readings
├── config_flow.py       # Configuration flow for setting up the integration
├── const.py             # Constants and configuration keys
├── strings.json         # UI strings for configuration flow
└── manifest.json        # Integration metadata and dependencies
```

## Key Dependencies

- **owlsensor**: External Python library (v0.4.2) that handles CM160 serial communication
- **Home Assistant Core**: Minimum version 2024.11.0
- **Serial communication**: Uses Python's `serial` library for USB/COM port access

## Core Architecture

### Integration Lifecycle (`__init__.py`)
- **Setup**: Creates `CMDataCollector` from owlsensor library using configured serial port
- **Entry management**: Handles first-run state tracking via `CONF_NOT_FIRST_RUN` flag
- **Cleanup**: Properly closes serial connections on unload using executor jobs

### Sensor Implementation (`sensor.py`)
- **Single sensor**: `OwmCMSensor` entity for current measurement
- **Device class**: Uses `SensorDeviceClass.CURRENT` with ampere units
- **Update mechanism**: Polls `collector.get_current()` for real-time data
- **Test mode**: Supports mock data when port is "test"

### Configuration Flow (`config_flow.py`)
- **User input**: Single field for serial port path (e.g., `/dev/ttyUSB0`, `COM4`)
- **Validation**: Tests connection by instantiating `CMDataCollector`
- **Error handling**: Catches `SerialException` for connection failures

## Development Notes

### Serial Port Handling
- The CM160 device sends historical data first, then real-time data
- Real-time updates occur every 15 seconds once historical sync completes
- Serial connection cleanup must happen in executor to avoid blocking event loop

### Device Identification
- Unique ID format: `CM160-{sanitized_port}-1`
- Device identifiers use domain and unique_id tuple
- Manufacturer: "Energy OWL", Model: "CM160"

### Configuration State
- First run detection prevents repeated initialization steps
- Config entry updates are async and trigger reloads via update listener

### HACS Integration
- Uses `persistent_directory: "local"` for local development
- No ZIP releases - direct repository integration
- README rendering enabled for HACS store display