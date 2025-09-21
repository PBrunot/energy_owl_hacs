"""Interfaces with the OWL sensors."""

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfElectricCurrent, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import COORDINATOR, DOMAIN
from .coordinator import OwlDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Sensors."""
    coordinator: OwlDataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id][COORDINATOR]

    sensors = [
        OwlCMSensor(coordinator, config_entry),
        OwlHistoricalDataSensor(coordinator, config_entry),
    ]

    async_add_entities(sensors)    


class OwlCMSensor(CoordinatorEntity, SensorEntity):
    """Representation of an OWL CM160 current sensor."""

    _attr_name = "CM160 - Current"
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_should_poll = False

    def __init__(self, coordinator: OwlDataUpdateCoordinator, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.config_entry = config_entry

        # Create unique ID based on port
        port = config_entry.data.get("port", "unknown")
        port_safe = str.replace(port, '/', '-').replace('\\', '-')
        self._attr_unique_id = f"CM160-{port_safe}-current"

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        port = self.config_entry.data.get("port", "unknown")
        return DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)},
            name=f"Energy OWL CM160 ({port})",
            manufacturer="Energy OWL",
            model="CM160",
            sw_version="1.0",
        )

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        # Entity is available if coordinator is connected and either has valid data or is still syncing
        return self.coordinator.connected and (
            self.coordinator.last_update_success or
            (self.coordinator.data and self.coordinator.data.get("connected", False))
        )

    @property
    def native_value(self) -> float | None:
        """Return the current measurement."""
        if not self.coordinator.data:
            return None

        current = self.coordinator.data.get("current")
        # Return None if still receiving historical data or no valid reading yet
        if current is None:
            return None

        return current

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return diagnostic attributes."""
        if not self.coordinator.data:
            return {}

        attrs = {
            "connected": self.coordinator.data.get("connected", False),
            "last_error": self.coordinator.data.get("last_error"),
            "error_count": self.coordinator.data.get("error_count", 0),
            "total_updates": self.coordinator.data.get("total_updates", 0),
            "historical_data_complete": self.coordinator.data.get("historical_data_complete", False),
            "historical_data_count": self.coordinator.data.get("historical_data_count", 0),
        }

        # Add status hint when current is None but device is connected
        current = self.coordinator.data.get("current")
        if current is None and self.coordinator.data.get("connected", False):
            if not self.coordinator.data.get("historical_data_complete", False):
                attrs["status"] = "Receiving historical data from device"
            else:
                attrs["status"] = "Waiting for real-time updates"

        return attrs


class OwlHistoricalDataSensor(CoordinatorEntity, SensorEntity):
    """Sensor to track historical data collection progress."""

    _attr_name = "CM160 - Historical Data Progress"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.TOTAL
    _attr_should_poll = False

    def __init__(self, coordinator: OwlDataUpdateCoordinator, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.config_entry = config_entry

        # Create unique ID based on port
        port = config_entry.data.get("port", "unknown")
        port_safe = str.replace(port, '/', '-').replace('\\', '-')
        self._attr_unique_id = f"CM160-{port_safe}-historical-progress"

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        port = self.config_entry.data.get("port", "unknown")
        port_safe = port.replace('/', '-').replace('\\', '-')
        return DeviceInfo(
            identifiers={(DOMAIN, f"CM160-{port_safe}-current")},
        )

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.connected

    @property
    def native_value(self) -> int | None:
        """Return the number of historical records collected."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("historical_data_count", 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return diagnostic attributes."""
        if not self.coordinator.data:
            return {}

        return {
            "historical_data_complete": self.coordinator.data.get("historical_data_complete", False),
            "status": "Complete" if self.coordinator.data.get("historical_data_complete", False) else "In Progress",
        }
