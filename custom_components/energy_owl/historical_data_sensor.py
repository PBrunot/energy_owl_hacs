"""Historical data status sensor for Energy OWL CM160 integration."""

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory

from .base_entity import OwlEntity
from .coordinator import OwlDataUpdateCoordinator


class OwlHistoricalDataSensor(OwlEntity, SensorEntity):
    """Sensor to track historical data collection progress."""

    _attr_name = "Historical Data Status"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: OwlDataUpdateCoordinator, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{self._device_unique_id}-historical-status"

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success or self.coordinator.connected

    @property
    def native_value(self) -> str | None:
        """Return a user-friendly status message."""
        if not self.available:
            return "Unavailable"

        if not self.coordinator.data:
            return "Disconnected"

        connected = self.coordinator.data.get("connected", False)
        if not connected:
            return "Disconnected"

        historical_complete = self.coordinator.data.get("historical_data_complete", False)
        count = self.coordinator.data.get("historical_data_count", 0)

        if historical_complete:
            return "Complete"
        elif count > 0:
            return f"Syncing ({count} records)"
        else:
            return "Starting sync"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return diagnostic attributes."""
        attrs = super().extra_state_attributes

        if self.coordinator.data:
            count = self.coordinator.data.get("historical_data_count", 0)
            complete = self.coordinator.data.get("historical_data_complete", False)

            # Add helpful context based on status
            if complete:
                attrs["message"] = f"Historical data sync completed with {count} records"
            elif count > 0:
                attrs["message"] = f"Syncing historical data... {count} records received"
            else:
                attrs["message"] = "Waiting for historical data from device"

        return attrs