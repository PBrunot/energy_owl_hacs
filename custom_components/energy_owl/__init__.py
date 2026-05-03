"""The Energy OWL CM160 energy meter integration."""

import csv
import logging
import re
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PORT, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr

from .const import (
    CONF_NOT_FIRST_RUN,
    DOMAIN,
)
from .coordinator import OwlDataUpdateCoordinator

PLATFORMS = [Platform.SENSOR]

_LOGGER = logging.getLogger(__name__)


@dataclass
class EnergyOwlData:
    """Runtime data for Energy OWL integration."""

    coordinator: OwlDataUpdateCoordinator


type EnergyOwlConfigEntry = ConfigEntry[EnergyOwlData]


async def async_setup_entry(hass: HomeAssistant, entry: EnergyOwlConfigEntry) -> bool:
    """Set up OWL data collector from a config entry."""
    port = entry.data[CONF_PORT]

    coordinator = OwlDataUpdateCoordinator(hass, port)

    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        raise
    except Exception as err:
        _LOGGER.error("Error setting up OWL coordinator for port %s: %s", port, err)
        raise ConfigEntryNotReady from err

    first_run = not bool(entry.data.get(CONF_NOT_FIRST_RUN))
    if first_run:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_NOT_FIRST_RUN: True}
        )
        _LOGGER.info(
            "First run detected. Device will send historical data before real-time updates."
        )

    entry.runtime_data = EnergyOwlData(coordinator=coordinator)
    entry.async_on_unload(entry.add_update_listener(_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await _register_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: EnergyOwlConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.coordinator.async_disconnect()
    return unload_ok


async def _update_listener(hass: HomeAssistant, entry: EnergyOwlConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def _register_services(hass: HomeAssistant) -> None:
    """Register services for the integration."""

    def _get_coordinator_from_call(
        call: ServiceCall,
    ) -> tuple[OwlDataUpdateCoordinator, str | None]:
        """Get the coordinator and device_id for a service call."""
        target_device_ids = call.data.get("device_id", [])
        config_entry_id = None
        target_device_id = None

        device_reg = dr.async_get(hass)

        if target_device_ids:
            target_device_id = next(iter(target_device_ids))
            device = device_reg.async_get(target_device_id)
            if not device:
                raise ValueError(f"Device {target_device_id} not found in device registry")
            config_entry_id = next(iter(device.config_entries), None)
        else:
            entries = hass.config_entries.async_entries(DOMAIN)
            if len(entries) == 1:
                _LOGGER.debug(
                    "Service call with no device_id, defaulting to the only available device."
                )
                config_entry_id = entries[0].entry_id
                devices = dr.async_entries_for_config_entry(device_reg, config_entry_id)
                if devices:
                    target_device_id = devices[0].id
            elif len(entries) > 1:
                raise ValueError(
                    "Multiple devices found. Please target a specific device for this service call."
                )

        if not config_entry_id:
            raise ValueError(
                "Could not determine target device. Please select a device for the service call."
            )

        entry = hass.config_entries.async_get_entry(config_entry_id)
        if entry is None or not hasattr(entry, "runtime_data"):
            raise ValueError(
                f"Integration for config entry {config_entry_id} not ready or not found"
            )

        coordinator: OwlDataUpdateCoordinator = entry.runtime_data.coordinator
        return coordinator, target_device_id

    async def get_historical_data(call: ServiceCall) -> dict:
        """Service to get historical data from the device."""
        coordinator, device_id = _get_coordinator_from_call(call)
        clear_existing = call.data.get("clear_existing", False)

        if clear_existing:
            await coordinator.async_reset_historical_data()

        historical_data = await coordinator.get_historical_data()

        return {
            "device_id": device_id,
            "historical_data_count": len(historical_data),
            "historical_data_complete": coordinator.historical_data_complete,
            "records": [
                {
                    "timestamp": record["timestamp"].isoformat(),
                    "current": record["current"],
                }
                for record in historical_data
            ],
        }

    async def clear_historical_data(call: ServiceCall) -> None:
        """Service to clear historical data from the device."""
        coordinator, device_id = _get_coordinator_from_call(call)

        await coordinator.async_reset_historical_data()
        _LOGGER.info("Historical data cleared for device %s", device_id)

    async def export_historical_data_csv(call: ServiceCall) -> None:
        """Service to export historical data to a CSV file."""
        coordinator, device_id = _get_coordinator_from_call(call)

        default_filename = f"energy_owl_export_{device_id}.csv"
        filename = call.data.get("filename", default_filename)
        filename = re.sub(r'[\\/:"*?<>|]', "_", filename)
        if not filename.lower().endswith(".csv"):
            filename += ".csv"

        file_path = hass.config.path(filename)
        historical_data = await coordinator.get_historical_data()

        if not historical_data:
            _LOGGER.warning("No historical data found to export for device %s.", device_id)
            return

        def _write_csv_sync():
            try:
                with open(file_path, "w", newline="", encoding="utf-8") as csv_file:
                    writer = csv.writer(csv_file)
                    writer.writerow(["timestamp", "current"])
                    for record in historical_data:
                        writer.writerow(
                            [record["timestamp"].isoformat(), record["current"]]
                        )
                _LOGGER.info(
                    "Successfully exported %d historical records for device %s to %s",
                    len(historical_data),
                    device_id,
                    file_path,
                )
            except IOError as err:
                _LOGGER.error("Error writing to file %s: %s", file_path, err)

        await hass.async_add_executor_job(_write_csv_sync)

    async def force_reconnect(call: ServiceCall) -> None:
        """Service to force reconnection when device is stuck."""
        coordinator, device_id = _get_coordinator_from_call(call)

        _LOGGER.warning("Force reconnect requested for device %s", device_id)
        await coordinator.async_reconnect()
        _LOGGER.info("Force reconnection completed for device %s", device_id)

    if not hass.services.has_service(DOMAIN, "get_historical_data"):
        hass.services.async_register(
            DOMAIN,
            "get_historical_data",
            get_historical_data,
            supports_response=True,
        )

    if not hass.services.has_service(DOMAIN, "clear_historical_data"):
        hass.services.async_register(DOMAIN, "clear_historical_data", clear_historical_data)

    if not hass.services.has_service(DOMAIN, "export_historical_data_csv"):
        hass.services.async_register(
            DOMAIN, "export_historical_data_csv", export_historical_data_csv
        )

    if not hass.services.has_service(DOMAIN, "force_reconnect"):
        hass.services.async_register(DOMAIN, "force_reconnect", force_reconnect)
