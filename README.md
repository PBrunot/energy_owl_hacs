# 🦉 Energy OWL CM160 - Home Assistant Integration

[![HACS Badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![Version](https://img.shields.io/github/v/release/PBrunot/energy_owl_hacs)](https://github.com/PBrunot/energy_owl_hacs/releases)
[![License](https://img.shields.io/github/license/PBrunot/energy_owl_hacs)](LICENSE)
[![Issues](https://img.shields.io/github/issues/PBrunot/energy_owl_hacs)](https://github.com/PBrunot/energy_owl_hacs/issues)

A powerful Home Assistant custom integration for the **Energy OWL CM160** energy meter, providing real-time current monitoring and comprehensive historical data analysis.

![Energy OWL CM160 Device](https://github.com/user-attachments/assets/75d97f4f-463f-4380-8232-92ce58faa015)

## ✨ Features

### 🔄 Real-time Monitoring
- **Live Current Readings**: Get electrical current measurements every 15 seconds
- **Device Status Tracking**: Monitor connection status and error reporting
- **Automatic Reconnection**: Robust error handling with automatic reconnection

### 📊 Historical Data Support *(New in v0.5.0)*
- **Historical Data Collection**: Automatic collection of timestamped historical readings
- **Progress Monitoring**: Track historical data sync with dedicated diagnostic sensor
- **Event-Driven Integration**: Real-time events for Home Assistant automations
- **Data Services**: Programmatic access to historical data via services

### 🏠 Home Assistant Integration
- **Energy Dashboard Compatible**: Perfect for Home Assistant's Energy dashboard
- **Multiple Sensors**: Current sensor + diagnostic sensors for comprehensive monitoring
- **Device Registry**: Proper device identification and management
- **Configuration Flow**: Easy setup through Home Assistant UI

## 📋 Requirements

- **Home Assistant**: Version 2024.11.0 or later
- **Hardware**: Energy OWL CM160 device connected via USB/Serial
- **Dependencies**: Automatically managed through HACS

## 🚀 Installation

### Via HACS (Recommended)

1. **Install HACS** if not already installed
2. **Add Custom Repository**:
   - Go to HACS → Integrations
   - Click the three dots menu → Custom repositories
   - Add: `https://github.com/PBrunot/energy_owl_hacs`
   - Category: Integration
3. **Install Integration**:
   - Search for "Energy OWL" in HACS
   - Click Install
   - Restart Home Assistant

### Manual Installation

1. Download the latest release from [GitHub Releases](https://github.com/PBrunot/energy_owl_hacs/releases)
2. Extract to `custom_components/energy_owl/` in your Home Assistant config directory
3. Restart Home Assistant

## ⚙️ Setup

### Hardware Connection

1. **Connect the CM160** to your Home Assistant machine via USB
2. **Note the port path**:
   - **Linux**: Usually `/dev/ttyUSB0` or `/dev/ttyUSB1`
   - **Windows**: Usually `COM3`, `COM4`, etc.
   - **VM Users**: Ensure USB device is bridged to the VM

> **💡 Tip**: On Linux, run `dmesg | grep tty` after connecting to find the port

### Integration Configuration

1. **Add Integration**:
   - Go to Settings → Devices & Services
   - Click "Add Integration"
   - Search for "Energy OWL"
   - Enter your serial port path (e.g., `/dev/ttyUSB0`)

2. **Wait for Initial Sync**:
   - The device sends historical data first (may take several minutes)
   - Real-time data starts after historical sync completes
   - Monitor progress with the "Historical Data Status" sensor showing "Syncing (X records)" → "Complete"

![Home Assistant Integration](https://github.com/user-attachments/assets/20e1dcac-2248-4dd1-9a46-9dbcfda59633)

## 📈 Usage

### Available Entities

| Entity | Type | Description |
|--------|------|-------------|
| `CM160 - Current` | Sensor | Real-time current measurement (Amperes) |
| `CM160 - Historical Data Status` | Diagnostic | Historical data sync status with progress |

### Historical Data Events

The integration fires the following events for automation:

- **`energy_owl_historical_data`**: Fired for each historical record
- **`energy_owl_historical_data_complete`**: Fired when historical sync completes

#### Example Automation
```yaml
automation:
  - alias: "Historical Data Complete"
    trigger:
      platform: event
      event_type: energy_owl_historical_data_complete
    action:
      service: notify.mobile_app_phone
      data:
        message: "Energy OWL historical data sync completed!"
```

### Services

#### Get Historical Data
```yaml
service: energy_owl.get_historical_data
target:
  device_id: "your_device_id"
data:
  clear_existing: false
```

#### Clear Historical Data
```yaml
service: energy_owl.clear_historical_data
target:
  device_id: "your_device_id"
```

### Energy Dashboard Integration

1. **Create Power Helper**:
   - Go to Settings → Devices & Services → Helpers
   - Add "Template" sensor:
   ```yaml
   template:
     - sensor:
         name: "CM160 Power"
         unit_of_measurement: "W"
         device_class: power
         state: "{{ states('sensor.cm160_current') | float * 230 }}"
   ```

2. **Create Energy Helper**:
   - Add "Integration - Riemann sum integral" helper
   - Source: `sensor.cm160_power`
   - Method: Trapezoidal rule
   - Unit: kWh

3. **Add to Energy Dashboard**:
   - Go to Energy Dashboard
   - Add your energy helper as consumption

## 🛠️ Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| Port not found | Check device connection and port permissions |
| No data after setup | Wait for historical sync to complete (can take 5-10 minutes) |
| Connection errors | Verify port path and ensure no other software is using the device |
| Permission denied | Add Home Assistant user to `dialout` group on Linux |

### Debug Logging

Add to `configuration.yaml`:
```yaml
logger:
  logs:
    custom_components.energy_owl: debug
    owlsensor: debug
```

## 🔄 Version History

### v0.5.0 - Latest *(Current)*
- ✅ **Historical Data Support**: Complete historical data collection and exposure
- ✅ **Event System**: Real-time events for Home Assistant automations
- ✅ **Services**: Get and clear historical data programmatically
- ✅ **Enhanced Monitoring**: Progress tracking and status reporting
- ✅ **Best Practices**: Following Home Assistant development standards

### Previous Versions
- **v0.1.2**: Basic real-time current monitoring
- **v0.1.1**: Initial HACS release
- **v0.1.0**: Initial release

## 🤝 Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Energy OWL for creating the CM160 device
- [owlsensor](https://github.com/PBrunot/owlsensor) library for device communication
- Home Assistant community for integration standards

---

**Need help?** [Open an issue](https://github.com/PBrunot/energy_owl_hacs/issues) or check the [discussions](https://github.com/PBrunot/energy_owl_hacs/discussions).