"""Base entity for Energy OWL integration."""

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_VOLTAGE,
    CONF_VOLTAGE_ENTITY,
    DEFAULT_VOLTAGE,
    DOMAIN,
    VERSION,
)
from .coordinator import OwlDataUpdateCoordinator


class OwlEntity(CoordinatorEntity):
    """Base class for Energy OWL entities."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, coordinator: OwlDataUpdateCoordinator, config_entry: ConfigEntry) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.config_entry = config_entry
        port = config_entry.data.get("port", "unknown")
        port_safe = str.replace(port, '/', '-').replace('\\', '-')
        self._device_unique_id = f"CM160-{port_safe}-v2"

    def _get_voltage(self) -> float:
        """Return grid voltage from a HA entity state or the configured default."""
        entity_id = self.config_entry.options.get(CONF_VOLTAGE_ENTITY)
        if entity_id:
            state = self.hass.states.get(entity_id)
            if state and state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                try:
                    return float(state.state)
                except (ValueError, TypeError):
                    pass
        return float(self.config_entry.options.get(CONF_VOLTAGE, DEFAULT_VOLTAGE))

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info, linking all entities to a single device."""
        port = self.config_entry.data.get("port", "unknown")
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_unique_id)},
            name=f"Energy OWL CM160 ({port})",
            manufacturer="Energy OWL",
            model="CM160",
            sw_version=VERSION,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return common diagnostic attributes for all OWL entities."""
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

        debug_info = self.coordinator.data.get("debug_info")
        if debug_info and isinstance(debug_info, dict):
            for key, value in debug_info.items():
                attrs[f"collector_{key}"] = value

        return attrs
