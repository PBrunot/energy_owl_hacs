"""The Energy OWL CM160 energy meter integration."""

import logging

from owlsensor import get_async_datacollector
from serial import SerialException

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import (
    CONF_NOT_FIRST_RUN,
    DOMAIN,
    FIRST_RUN,
    OWL_OBJECT,
    UNDO_UPDATE_LISTENER,
    MODEL,
)

PLATFORMS = [Platform.SENSOR]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up OWL data collector from a config entry."""
    port = entry.data[CONF_PORT]

    try:
        owl_collector = await hass.async_add_executor_job(
            get_async_datacollector, port, MODEL, 15
        )
    except SerialException as err:
        _LOGGER.error("Error connecting to OWL controller at %s", port)
        raise ConfigEntryNotReady from err

    # double negative to handle absence of value
    first_run = not bool(entry.data.get(CONF_NOT_FIRST_RUN))

    if first_run:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_NOT_FIRST_RUN: True}
        )

    undo_listener = entry.add_update_listener(_update_listener)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        OWL_OBJECT: owl_collector,
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

    hass.data[DOMAIN][entry.entry_id][UNDO_UPDATE_LISTENER]()

    def _cleanup(owl_object) -> None:
        """Destroy the OWL object.

        Destroying the OWL closes the serial connection, do it in an executor so the garbage
        collection does not block.
        """
        del owl_object

    owl_object = hass.data[DOMAIN][entry.entry_id][OWL_OBJECT]
    hass.data[DOMAIN].pop(entry.entry_id)

    await hass.async_add_executor_job(_cleanup, owl_object)

    return True


async def _update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)
