"""Historical current sensor for Energy OWL CM160 integration."""

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfElectricCurrent, EntityCategory
from homeassistant.core import callback

from .base_entity import OwlEntity
from .coordinator import OwlDataUpdateCoordinator


class OwlHistoricalCurrentSensor(OwlEntity, SensorEntity):
    """Sensor that displays individual historical current readings for recorder integration."""

    _attr_name = "CM160 - Historical Current"
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: OwlDataUpdateCoordinator, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{self._device_unique_id}-historical-current"
        self._current_historical_value: float | None = None
        self._current_historical_timestamp: str | None = None
        self._chunk_number: int | None = None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success or self.coordinator.connected

    @property
    def native_value(self) -> float | None:
        """Return the current historical measurement being processed."""
        return self._current_historical_value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return diagnostic attributes."""
        attrs = super().extra_state_attributes

        if self._current_historical_timestamp:
            attrs.update({
                "historical_timestamp": self._current_historical_timestamp,
                "chunk_number": self._chunk_number,
                "source": "historical_data",
            })

        return attrs

    def update_historical_record(self, current: float, timestamp: str, chunk_number: int) -> None:
        """Update with a new historical record."""
        self._current_historical_value = current
        self._current_historical_timestamp = timestamp
        self._chunk_number = chunk_number
        self.async_write_ha_state()