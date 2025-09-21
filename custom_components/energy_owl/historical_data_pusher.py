"""Historical data pusher for Energy OWL CM160 integration."""

import asyncio
import logging
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import callback

from .base_entity import OwlEntity
from .const import DOMAIN
from .coordinator import OwlDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


class OwlHistoricalDataPusher(OwlEntity, SensorEntity):
    """Entity that automatically pushes historical data in chunks to Home Assistant."""

    _attr_name = "CM160 - Historical Data Pusher"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: OwlDataUpdateCoordinator, config_entry: ConfigEntry, historical_current_sensor=None) -> None:
        """Initialize the historical data pusher."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{self._device_unique_id}-historical-pusher"
        self._processed_count = 0
        self._chunks_pushed = 0
        self._last_push_time: datetime | None = None
        self._push_task: asyncio.Task | None = None
        self._chunk_size = 500
        self._current_status = "Waiting for connection"
        self._progress_percentage = 0
        self._acquisition_start_time: datetime | None = None
        self._acquisition_wait_time = 180  # Wait 3 minutes before starting to push
        self._historical_current_sensor = historical_current_sensor

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success or self.coordinator.connected

    @property
    def native_value(self) -> str | None:
        """Return the current processing status."""
        if not self.available:
            self._current_status = "Unavailable"
            return "Unavailable"

        if not self.coordinator.data:
            self._current_status = "Disconnected"
            return "Disconnected"

        connected = self.coordinator.data.get("connected", False)
        if not connected:
            self._current_status = "Disconnected"
            return "Disconnected"

        historical_complete = self.coordinator.data.get("historical_data_complete", False)
        total_historical = self.coordinator.data.get("historical_data_count", 0)

        if historical_complete:
            if self._chunks_pushed > 0:
                self._current_status = f"✅ Complete - {self._processed_count}/{total_historical} records pushed"
                self._progress_percentage = 100
                return f"✅ Complete ({self._chunks_pushed} chunks)"
            else:
                self._current_status = "Complete - No data to push"
                return "Complete - No data"
        elif self._chunks_pushed > 0:
            if total_historical > 0:
                self._progress_percentage = min(100, (self._processed_count / total_historical) * 100)
            self._current_status = f"🔄 Processing chunk {self._chunks_pushed} ({self._processed_count}/{total_historical} records)"
            return f"🔄 Processing ({self._progress_percentage:.0f}%)"
        else:
            # Check if we're in acquisition wait period
            if self._acquisition_start_time and total_historical > 0:
                elapsed = (datetime.now() - self._acquisition_start_time).total_seconds()
                remaining = max(0, self._acquisition_wait_time - elapsed)
                if remaining > 0:
                    self._current_status = f"⏳ Waiting for acquisition to complete ({remaining:.0f}s remaining)"
                    return f"⏳ Waiting ({remaining:.0f}s)"
                else:
                    self._current_status = "🔄 Ready to start processing"
                    return "🔄 Ready to process"
            else:
                self._current_status = "⏳ Waiting for historical data"
                return "⏳ Waiting for data"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return diagnostic attributes."""
        attrs = super().extra_state_attributes

        total_historical = self.coordinator.data.get("historical_data_count", 0) if self.coordinator.data else 0

        # Calculate acquisition wait info
        acquisition_elapsed = 0
        acquisition_remaining = 0
        if self._acquisition_start_time:
            acquisition_elapsed = (datetime.now() - self._acquisition_start_time).total_seconds()
            acquisition_remaining = max(0, self._acquisition_wait_time - acquisition_elapsed)

        attrs.update({
            "status_detail": self._current_status,
            "progress_percentage": self._progress_percentage,
            "chunk_size": self._chunk_size,
            "chunks_pushed": self._chunks_pushed,
            "processed_count": self._processed_count,
            "total_historical_count": total_historical,
            "remaining_records": max(0, total_historical - self._processed_count) if total_historical > 0 else 0,
            "last_push_time": self._last_push_time.isoformat() if self._last_push_time else None,
            "is_processing": self._push_task is not None and not self._push_task.done(),
            "acquisition_wait_time_seconds": self._acquisition_wait_time,
            "acquisition_elapsed_seconds": acquisition_elapsed,
            "acquisition_remaining_seconds": acquisition_remaining,
            "acquisition_start_time": self._acquisition_start_time.isoformat() if self._acquisition_start_time else None,
        })

        return attrs

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
                    if elapsed < self._acquisition_wait_time:
                        # Still in wait period, update status and continue waiting
                        remaining = self._acquisition_wait_time - elapsed
                        self._current_status = f"⏳ Waiting for acquisition to complete ({remaining:.0f}s remaining)"
                        self.async_write_ha_state()
                        await asyncio.sleep(5)
                        continue
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
                        self._current_status = f"✅ Complete - {self._processed_count} records pushed in {self._chunks_pushed} chunks"
                        self._progress_percentage = 100

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

                    # Update progress percentage
                    if len(historical_data) > 0:
                        self._progress_percentage = min(100, (self._processed_count / len(historical_data)) * 100)

                    # Update status with progress
                    self._current_status = f"🔄 Processing chunk {self._chunks_pushed} ({self._processed_count}/{len(historical_data)} records)"

                    # Update the entity state to reflect progress
                    self.async_write_ha_state()

                    _LOGGER.info(
                        "Pushed chunk %d with %d records (total processed: %d/%d - %.1f%%)",
                        self._chunks_pushed,
                        len(chunk),
                        self._processed_count,
                        len(historical_data),
                        self._progress_percentage
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

            # Update historical current sensor with each record for HA history
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

                # Update the historical current sensor for each record
                if self._historical_current_sensor:
                    self._historical_current_sensor.update_historical_record(
                        record["current"],
                        record["timestamp"].isoformat(),
                        chunk_number
                    )

                # Small delay between records to avoid overwhelming HA
                if i % 50 == 0:  # Every 50 records
                    await asyncio.sleep(0.1)

        except Exception as err:
            _LOGGER.error("Error pushing chunk %d to HA: %s", chunk_number, err)

    async def async_will_remove_from_hass(self) -> None:
        """Cancel the processing task when entity is removed."""
        if self._push_task and not self._push_task.done():
            self._push_task.cancel()
            try:
                await self._push_task
            except asyncio.CancelledError:
                pass