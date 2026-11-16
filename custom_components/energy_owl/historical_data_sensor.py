"""Historical data status sensor for Energy OWL CM160 integration."""

from typing import Any, ClassVar

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory

from .base_entity import OwlEntity
from .coordinator import OwlDataUpdateCoordinator


class OwlHistoricalDataSensor(OwlEntity, SensorEntity):
    """Sensor to track historical data collection progress."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options: ClassVar[list[str]] = ["disconnected", "starting", "syncing", "complete"]
    _attr_translation_key = "historical_data_status"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: OwlDataUpdateCoordinator, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{self._device_unique_id}-historical-status"

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success

    @property
    def native_value(self) -> str | None:
        """Return a stable translated status key."""
        if not self.available:
            return "disconnected"

        if not self.coordinator.data:
            return "disconnected"

        connected = self.coordinator.data.get("connected", False)
        if not connected:
            return "disconnected"

        return self.coordinator.data.get("historical_sync_status", "starting")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return diagnostic attributes."""
        return {
            "records_collected": self.coordinator.historical_data_count,
            "connected": self.coordinator.connected,
        }
