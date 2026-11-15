"""Device actions for Energy OWL."""

import csv
import logging
import re

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
from .coordinator import OwlDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register services for the integration."""

    def _get_coordinator_from_call(
        call: ServiceCall,
    ) -> tuple[OwlDataUpdateCoordinator, str | None]:
        """Get the coordinator and device_id for a service call."""
        target_device_ids = call.data["device_id"]
        if len(target_device_ids) != 1:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="single_target")
        target_device_id = target_device_ids[0]
        device = dr.async_get(hass).async_get(target_device_id)
        entries = [] if device is None else [
            entry for entry_id in device.config_entries
            if (entry := hass.config_entries.async_get_entry(entry_id)) is not None
            and entry.domain == DOMAIN
        ]
        if len(entries) != 1:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="invalid_target")
        entry = entries[0]
        if entry.state is not ConfigEntryState.LOADED or not getattr(entry, "runtime_data", None):
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="entry_not_loaded")
        return entry.runtime_data.coordinator, target_device_id

    async def get_historical_data(call: ServiceCall) -> dict:
        """Service to get historical data from the device."""
        coordinator, device_id = _get_coordinator_from_call(call)
        clear_existing = call.data.get("clear_existing", False)

        if clear_existing:
            await coordinator.async_reset_historical_data()

        historical_data = await coordinator.get_historical_data(strict=True)

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
        historical_data = await coordinator.get_historical_data(strict=True)

        if not historical_data:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_history")

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
            except OSError as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN, translation_key="export_failed",
                    translation_placeholders={"error": str(err)},
                ) from err

        await hass.async_add_executor_job(_write_csv_sync)

    async def force_reconnect(call: ServiceCall) -> None:
        """Service to force reconnection when device is stuck."""
        coordinator, device_id = _get_coordinator_from_call(call)

        _LOGGER.warning("Force reconnect requested for device %s", device_id)
        await coordinator.async_reconnect()
        _LOGGER.info("Force reconnection completed for device %s", device_id)

    def checked_handler(handler):
        async def handle(call):
            try:
                return await handler(call)
            except HomeAssistantError as err:
                if err.translation_domain == DOMAIN:
                    raise
                raise HomeAssistantError(
                    translation_domain=DOMAIN, translation_key="action_failed",
                    translation_placeholders={"error": str(err)},
                ) from err
            except Exception as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN, translation_key="action_failed",
                    translation_placeholders={"error": str(err)},
                ) from err
        return handle

    target_schema = {vol.Required("device_id"): vol.All(cv.ensure_list, [cv.string])}
    handlers = {
        "get_historical_data": (get_historical_data, {vol.Optional("clear_existing", default=False): cv.boolean}),
        "clear_historical_data": (clear_historical_data, {}),
        "export_historical_data_csv": (export_historical_data_csv, {vol.Optional("filename"): cv.string}),
        "force_reconnect": (force_reconnect, {}),
    }
    for name, (handler, fields) in handlers.items():
        if not hass.services.has_service(DOMAIN, name):
            hass.services.async_register(
                DOMAIN, name, checked_handler(handler), schema=vol.Schema({**target_schema, **fields}),
                supports_response=SupportsResponse.OPTIONAL if name == "get_historical_data" else SupportsResponse.NONE,
            )
