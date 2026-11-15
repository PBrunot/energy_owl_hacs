"""The Energy OWL CM160 energy meter integration."""

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_ENABLE_HISTORICAL,
    CONF_NOT_FIRST_RUN,
    DEFAULT_ENABLE_HISTORICAL,
    DOMAIN,
)
from .coordinator import OwlDataUpdateCoordinator
from .services import async_setup_services
from .statistics import OwlStatisticsImporter

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS = [Platform.SENSOR]

_LOGGER = logging.getLogger(__name__)


@dataclass
class EnergyOwlData:
    """Runtime data for Energy OWL integration."""

    coordinator: OwlDataUpdateCoordinator
    importer: OwlStatisticsImporter | None = None


type EnergyOwlConfigEntry = ConfigEntry[EnergyOwlData]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register actions independently of loaded entries."""
    await async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: EnergyOwlConfigEntry) -> bool:
    """Set up OWL data collector from a config entry."""
    port = entry.data[CONF_PORT]

    coordinator = OwlDataUpdateCoordinator(hass, port)
    importer = None
    if entry.options.get(CONF_ENABLE_HISTORICAL, DEFAULT_ENABLE_HISTORICAL):
        importer = OwlStatisticsImporter(hass, entry, coordinator)

    try:
        if importer:
            await importer.async_load()
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        if importer:
            await importer.async_close()
        await coordinator.async_disconnect()
        raise
    except BaseException as err:
        if importer:
            await importer.async_close()
        await coordinator.async_disconnect()
        _LOGGER.error("Error setting up OWL coordinator for port %s: %s", port, err)
        if not isinstance(err, Exception):
            raise
        raise ConfigEntryNotReady from err

    first_run = not bool(entry.data.get(CONF_NOT_FIRST_RUN))
    if first_run:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_NOT_FIRST_RUN: True}
        )
        _LOGGER.info(
            "First run detected. Device will send historical data before real-time updates."
        )

    entry.runtime_data = EnergyOwlData(coordinator=coordinator, importer=importer)
    entry.async_on_unload(entry.add_update_listener(_update_listener))

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        if importer:
            importer.start()
    except BaseException:
        try:
            await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        finally:
            if importer:
                await importer.async_close()
            await coordinator.async_disconnect()
        raise

    return True


async def async_unload_entry(hass: HomeAssistant, entry: EnergyOwlConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        if entry.runtime_data.importer:
            await entry.runtime_data.importer.async_close()
        await entry.runtime_data.coordinator.async_disconnect()
    return unload_ok


async def _update_listener(hass: HomeAssistant, entry: EnergyOwlConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)
