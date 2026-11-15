"""Base entity for Energy OWL integration."""

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    VERSION,
)
from .coordinator import OwlDataUpdateCoordinator
from .energy import resolve_voltage


class OwlEntity(CoordinatorEntity):
    """Base class for Energy OWL entities."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self, coordinator: OwlDataUpdateCoordinator, config_entry: ConfigEntry
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.config_entry = config_entry
        port = config_entry.data.get("identity_port", config_entry.data.get("port", "unknown"))
        port_safe = str.replace(port, "/", "-").replace("\\", "-")
        self._device_unique_id = f"CM160-{port_safe}-v2"

    def _get_voltage(self) -> float:
        """Return grid voltage from a HA entity state or the configured default."""
        return resolve_voltage(self.hass, self.config_entry.options)

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
        """Keep changing diagnostic counters off measurement entities."""
        return {}
