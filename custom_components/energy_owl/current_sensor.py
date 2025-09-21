"""Current sensor for Energy OWL CM160 integration."""

import asyncio
import logging
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfElectricCurrent
from homeassistant.core import callback
from homeassistant.helpers.entity import DeviceInfo

from .base_entity import OwlEntity
from .const import DOMAIN
from .coordinator import OwlDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


class OwlCMSensor(OwlEntity, SensorEntity):
    """Representation of an OWL CM160 current sensor that handles both real-time and historical data."""

    _attr_name = "CM160 - Current"
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: OwlDataUpdateCoordinator, config_entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{self._device_unique_id}-current"

        # Historical data processing attributes
        self._processed_count = 0
        self._chunks_pushed = 0
        self._last_push_time: datetime | None = None
        self._push_task: asyncio.Task | None = None
        self._chunk_size = 500
        self._processing_complete = False
        self._acquisition_start_time: datetime | None = None
        self._acquisition_wait_time = 60  # Wait 1 minute before starting to push
        self._temp_historical_value: float | None = None
        self._temp_historical_timestamp: datetime | None = None

        # Register with coordinator
        self.coordinator.register_historical_pusher(self)

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info, which is shared across all entities."""
        port = self.config_entry.data.get("port", "unknown")
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_unique_id)},
            name=f"Energy OWL CM160 ({port})",
            manufacturer="Energy OWL",
            model="CM160",
            sw_version="1.0",
        )

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        # Entity is available if coordinator is connected and either has valid data or is still syncing
        return self.coordinator.connected and (
            self.coordinator.last_update_success or
            (self.coordinator.data and self.coordinator.data.get("connected", False))
        )

    @property
    def native_value(self) -> float | None:
        """Return the current measurement (real-time or historical during processing)."""
        # If we're currently processing historical data, return the temporary historical value
        if self._temp_historical_value is not None:
            return self._temp_historical_value

        if not self.coordinator.data:
            return None

        current = self.coordinator.data.get("current")
        # Return None if still receiving historical data or no valid reading yet
        if current is None:
            return None

        return current

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return diagnostic attributes."""
        attrs = super().extra_state_attributes

        # Add status hint when current is None but device is connected
        if self.coordinator.data:
            current = self.coordinator.data.get("current")
            total_historical = self.coordinator.data.get("historical_data_count", 0)
            historical_complete = self.coordinator.data.get("historical_data_complete", False)

            if current is None and self.coordinator.data.get("connected", False):
                if not historical_complete:
                    attrs["status"] = "Receiving historical data from device"
                else:
                    attrs["status"] = "Waiting for real-time updates"

            # Add historical processing information
            if total_historical > 0:
                progress_percentage = min(100, (self._processed_count / total_historical) * 100) if total_historical > 0 else 0

                # Calculate acquisition wait info
                acquisition_elapsed = 0
                acquisition_remaining = 0
                if self._acquisition_start_time:
                    acquisition_elapsed = (datetime.now() - self._acquisition_start_time).total_seconds()
                    acquisition_remaining = max(0, self._acquisition_wait_time - acquisition_elapsed)

                attrs.update({
                    "historical_progress_percentage": progress_percentage,
                    "historical_chunks_pushed": self._chunks_pushed,
                    "historical_processed_count": self._processed_count,
                    "historical_total_count": total_historical,
                    "historical_remaining_records": max(0, total_historical - self._processed_count),
                    "historical_last_push_time": self._last_push_time.isoformat() if self._last_push_time else None,
                    "historical_processing_complete": self._processing_complete,
                    "historical_is_processing": self._push_task is not None and not self._push_task.done(),
                    "acquisition_elapsed_seconds": acquisition_elapsed,
                    "acquisition_remaining_seconds": acquisition_remaining,
                })

        return attrs

    def is_processing_complete(self) -> bool:
        """Return True if processing is complete."""
        return self._processing_complete

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        super()._handle_coordinator_update()

        if self.coordinator.data and self.coordinator.data.get("connected", False):
            # Start processing task if not already running
            if self._push_task is None or self._push_task.done():
                self._push_task = self.hass.async_create_task(self._process_historical_data())

    async def _process_historical_data(self) -> None:
        """Process historical data in chunks and push to HA."""
        try:
            first_run = True
            while True:
                # Get all historical data
                historical_data = await self.coordinator.get_historical_data()

                if not historical_data:
                    await asyncio.sleep(5)  # Wait 5 seconds before retrying
                    continue

                # Start acquisition timer on first data availability
                if first_run and len(historical_data) > 0:
                    first_run = False
                    self._acquisition_start_time = datetime.now()
                    _LOGGER.info(
                        "Historical data acquisition started. Found %d records. Waiting %d seconds before processing to allow complete acquisition.",
                        len(historical_data),
                        self._acquisition_wait_time
                    )

                # Check if we should wait for acquisition to complete
                if self._acquisition_start_time:
                    elapsed = (datetime.now() - self._acquisition_start_time).total_seconds()
                    historical_complete = self.coordinator.data.get("historical_data_complete", False)

                    # Skip wait if historical data collection is already complete
                    if not historical_complete and elapsed < self._acquisition_wait_time:
                        # Still in wait period, update status and continue waiting
                        self.async_write_ha_state()
                        await asyncio.sleep(5)
                        continue
                    elif historical_complete and self._chunks_pushed == 0:
                        # Historical data complete - start processing immediately
                        _LOGGER.info("Historical data collection completed. Starting processing immediately.")
                        self.async_write_ha_state()
                    elif self._chunks_pushed == 0:  # First time past wait period
                        # Send notification now that we're ready to start processing
                        estimated_chunks = (len(historical_data) + self._chunk_size - 1) // self._chunk_size
                        self.hass.async_create_task(
                            self.hass.services.async_call(
                                "persistent_notification",
                                "create",
                                {
                                    "title": "Energy OWL Historical Data Import Started",
                                    "message": f"Starting import of {len(historical_data)} historical records from CM160 device. Estimated {estimated_chunks} chunks to process.",
                                    "notification_id": f"energy_owl_import_started_{self._device_unique_id}",
                                },
                            )
                        )

                # Sort by timestamp (most recent first as requested)
                historical_data.sort(key=lambda x: x["timestamp"], reverse=True)

                # Calculate which chunk to process next
                start_idx = self._processed_count
                end_idx = min(start_idx + self._chunk_size, len(historical_data))

                # Check if we have new data to process
                if start_idx >= len(historical_data):
                    # No more data to process
                    if self.coordinator.data.get("historical_data_complete", False):
                        # Create a persistent notification for completion
                        self.hass.async_create_task(
                            self.hass.services.async_call(
                                "persistent_notification",
                                "create",
                                {
                                    "title": "Energy OWL Historical Data Import Complete",
                                    "message": f"Successfully imported {self._processed_count} historical records from CM160 device in {self._chunks_pushed} chunks.",
                                    "notification_id": f"energy_owl_import_complete_{self._device_unique_id}",
                                },
                            )
                        )

                        _LOGGER.info(
                            "Historical data processing complete. Pushed %d chunks (%d records total)",
                            self._chunks_pushed,
                            self._processed_count
                        )

                        # Mark processing as complete and notify coordinator
                        self._processing_complete = True
                        await self.coordinator.notify_pusher_complete(self)

                        # Final state update
                        self.async_write_ha_state()
                        break
                    else:
                        # Wait for more data
                        await asyncio.sleep(5)
                        continue

                # Get the current chunk
                chunk = historical_data[start_idx:end_idx]

                if chunk:
                    await self._push_chunk_to_ha(chunk, self._chunks_pushed + 1)
                    self._processed_count = end_idx
                    self._chunks_pushed += 1
                    self._last_push_time = datetime.now()

                    # Update the entity state to reflect progress
                    self.async_write_ha_state()

                    _LOGGER.info(
                        "Pushed chunk %d with %d records (total processed: %d/%d)",
                        self._chunks_pushed,
                        len(chunk),
                        self._processed_count,
                        len(historical_data)
                    )

                # Small delay between chunks to avoid overwhelming HA
                await asyncio.sleep(1)

        except Exception as err:
            _LOGGER.error("Error in historical data processing task: %s", err, exc_info=True)

    async def _push_chunk_to_ha(self, chunk: list, chunk_number: int) -> None:
        """Push a chunk of historical data to Home Assistant."""
        try:
            # Fire an event for the entire chunk
            port_safe = self.coordinator.port.replace("/", "-").replace("\\", "-")
            self.hass.bus.fire(
                f"{DOMAIN}_historical_chunk",
                {
                    "device_port": self.coordinator.port,
                    "device_id": f"CM160-{port_safe}",
                    "chunk_number": chunk_number,
                    "chunk_size": len(chunk),
                    "records": [
                        {
                            "timestamp": record["timestamp"].isoformat(),
                            "current": record["current"],
                        }
                        for record in chunk
                    ],
                }
            )

            # Update sensor state with each record for HA history
            for i, record in enumerate(chunk):
                # Fire individual events that can be captured by statistics/recorder
                self.hass.bus.fire(
                    f"{DOMAIN}_historical_data_point",
                    {
                        "device_port": self.coordinator.port,
                        "device_id": f"CM160-{port_safe}",
                        "timestamp": record["timestamp"].isoformat(),
                        "current": record["current"],
                        "chunk_number": chunk_number,
                    }
                )

                # Temporarily update sensor value with historical data for recording
                # This allows the recorder to capture historical values with correct timestamps
                self._temp_historical_value = record["current"]
                self._temp_historical_timestamp = record["timestamp"]
                self.async_write_ha_state()

                # Small delay between records to avoid overwhelming HA
                if i % 50 == 0:  # Every 50 records
                    await asyncio.sleep(0.1)

            # Reset temporary values after chunk processing
            self._temp_historical_value = None
            self._temp_historical_timestamp = None

        except Exception as err:
            _LOGGER.error("Error pushing chunk %d to HA: %s", chunk_number, err)

    async def async_will_remove_from_hass(self) -> None:
        """Cancel the processing task when entity is removed."""
        # Unregister from coordinator
        self.coordinator.unregister_historical_pusher(self)

        if self._push_task and not self._push_task.done():
            self._push_task.cancel()
            try:
                await self._push_task
            except asyncio.CancelledError:
                pass