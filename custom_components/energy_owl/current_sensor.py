"""Current sensor for Energy OWL CM160 integration."""

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfElectricCurrent
from homeassistant.helpers.entity import DeviceInfo

from .base_entity import OwlEntity
from .const import DOMAIN
from .coordinator import OwlDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


class OwlCMSensor(OwlEntity, SensorEntity):
    """Representation of an OWL CM160 current sensor for real-time data only."""

    _attr_name = "Current"
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: OwlDataUpdateCoordinator, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{self._device_unique_id}-current"

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info, which is shared across all entities."""
        port = self.config_entry.data.get("port", "unknown")
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_unique_id)},
            name=f"Energy OWL CM160 ({port})",
            manufacturer="Energy OWL",
            model="CM160",
            sw_version="1.0",
        )

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success or self.coordinator.connected

    @property
    def native_value(self) -> float | None:
        """Return the current measurement (real-time data only)."""
        if not self.coordinator.data:
            return None

        return self.coordinator.data.get("current")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return diagnostic attributes."""
        attrs = super().extra_state_attributes

        # Add simple status hint when current is None but device is connected
        if self.coordinator.data:
            current = self.coordinator.data.get("current")
            historical_complete = self.coordinator.data.get("historical_data_complete", False)

            if current is None and self.coordinator.data.get("connected", False):
                if not historical_complete:
                    attrs["status"] = "Device receiving historical data"
                else:
                    attrs["status"] = "Waiting for real-time updates"

        return attrs
