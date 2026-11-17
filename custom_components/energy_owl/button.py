"""Device controls for Energy OWL."""

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import UpdateFailed

from . import EnergyOwlConfigEntry
from .base_entity import OwlEntity
from .const import DOMAIN

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: EnergyOwlConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the reconnect control to the CM160 device."""
    async_add_entities([OwlReconnectButton(config_entry.runtime_data.coordinator, config_entry)])


class OwlReconnectButton(OwlEntity, ButtonEntity):
    """Close and reopen the configured serial port."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "reconnect"

    @property
    def unique_id(self) -> str:
        return f"{self._device_unique_id}-reconnect"

    @property
    def available(self) -> bool:
        """Keep recovery accessible when serial polling fails."""
        return True

    async def async_press(self) -> None:
        """Reconnect using the coordinator's serial lifecycle lock."""
        try:
            await self.coordinator.async_reconnect()
        except UpdateFailed as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="action_failed",
                translation_placeholders={"error": str(err)},
            ) from err
