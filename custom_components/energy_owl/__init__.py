"""The Energy OWL CM160 energy meter integration."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import (
    CONF_NOT_FIRST_RUN,
    COORDINATOR,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    FIRST_RUN,
    UNDO_UPDATE_LISTENER,
)
from .coordinator import OwlDataUpdateCoordinator

PLATFORMS = [Platform.SENSOR]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up OWL data collector from a config entry."""
    port = entry.data[CONF_PORT]

    # Create the coordinator
    coordinator = OwlDataUpdateCoordinator(
        hass,
        port,
        update_interval=DEFAULT_SCAN_INTERVAL,
    )

    # Connect to the device
    try:
        await coordinator._async_setup()
    except Exception as err:
        _LOGGER.error("Error setting up OWL coordinator for port %s: %s", port, err)
        raise ConfigEntryNotReady from err

    # Track first run for historical data handling
    first_run = not bool(entry.data.get(CONF_NOT_FIRST_RUN))

    if first_run:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_NOT_FIRST_RUN: True}
        )
        _LOGGER.info(
            "First run detected. Device will send historical data before real-time updates."
        )

    undo_listener = entry.add_update_listener(_update_listener)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        COORDINATOR: coordinator,
        UNDO_UPDATE_LISTENER: undo_listener,
        FIRST_RUN: first_run,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    # Remove update listener
    hass.data[DOMAIN][entry.entry_id][UNDO_UPDATE_LISTENER]()

    # Disconnect the coordinator
    coordinator: OwlDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR]
    await coordinator.async_disconnect()

    # Clean up data
    hass.data[DOMAIN].pop(entry.entry_id)

    return True


async def _update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)
