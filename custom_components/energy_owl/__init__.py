"""The Energy OWL CM160 energy meter integration."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PORT, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr

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

    # Register services
    await _register_services(hass)

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


async def _register_services(hass: HomeAssistant) -> None:
    """Register services for the integration."""

    async def get_historical_data(call: ServiceCall) -> dict:
        """Service to get historical data from the device."""
        device_id = call.data.get("device_id")
        clear_existing = call.data.get("clear_existing", False)

        if not device_id:
            raise ValueError("device_id is required")

        # Find the coordinator for this device
        coordinator = None
        for entry_data in hass.data[DOMAIN].values():
            if isinstance(entry_data, dict) and COORDINATOR in entry_data:
                coord = entry_data[COORDINATOR]
                port_safe = coord.port.replace('/', '-').replace('\\', '-')
                coord_device_id = f"CM160-{port_safe}"
                if coord_device_id == device_id:
                    coordinator = coord
                    break

        if not coordinator:
            raise ValueError(f"Device {device_id} not found")

        # Clear existing data if requested (reset tracking only, don't reset device)
        if clear_existing:
            coordinator._historical_data_complete = False
            coordinator._historical_data_count = 0
            coordinator._last_historical_check = 0
            _LOGGER.info("Reset historical data tracking for device %s", device_id)

        # Get current historical data
        historical_data = await coordinator.get_historical_data()

        return {
            "device_id": device_id,
            "historical_data_count": len(historical_data),
            "historical_data_complete": coordinator.historical_data_complete,
            "records": [
                {
                    "timestamp": record["timestamp"].isoformat(),
                    "current": record["current"]
                }
                for record in historical_data
            ] if len(historical_data) <= 100 else [],  # Limit to 100 records in response
        }

    async def clear_historical_data(call: ServiceCall) -> None:
        """Service to clear historical data from the device."""
        device_id = call.data.get("device_id")

        if not device_id:
            raise ValueError("device_id is required")

        # Find the coordinator for this device
        coordinator = None
        for entry_data in hass.data[DOMAIN].values():
            if isinstance(entry_data, dict) and COORDINATOR in entry_data:
                coord = entry_data[COORDINATOR]
                port_safe = coord.port.replace('/', '-').replace('\\', '-')
                coord_device_id = f"CM160-{port_safe}"
                if coord_device_id == device_id:
                    coordinator = coord
                    break

        if not coordinator:
            raise ValueError(f"Device {device_id} not found")

        # Reset historical data tracking (don't reset device state)
        coordinator._historical_data_complete = False
        coordinator._historical_data_count = 0
        coordinator._last_historical_check = 0

        _LOGGER.info("Historical data cleared for device %s", device_id)

    # Register services only once
    if not hass.services.has_service(DOMAIN, "get_historical_data"):
        hass.services.async_register(
            DOMAIN,
            "get_historical_data",
            get_historical_data,
            supports_response=True,
        )

    if not hass.services.has_service(DOMAIN, "clear_historical_data"):
        hass.services.async_register(
            DOMAIN,
            "clear_historical_data",
            clear_historical_data,
        )
