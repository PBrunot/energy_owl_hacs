"""Instantaneous power sensor for Energy OWL CM160."""

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower

from .base_entity import OwlEntity
from .coordinator import OwlDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


class OwlPowerSensor(OwlEntity, SensorEntity):
    """Instantaneous power in Watts — derived from current × configured voltage."""

    _attr_translation_key = "power"
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: OwlDataUpdateCoordinator, config_entry: ConfigEntry) -> None:
        """Initialize the power sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{self._device_unique_id}-power"

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success or self.coordinator.connected

    @property
    def native_value(self) -> float | None:
        """Return instantaneous power in Watts."""
        if not self.coordinator.data:
            return None
        current = self.coordinator.data.get("current")
        if current is None:
            return None
        return round(current * self._get_voltage(), 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose which voltage source is active."""
        attrs = super().extra_state_attributes
        attrs["voltage_used_v"] = self._get_voltage()
        return attrs
