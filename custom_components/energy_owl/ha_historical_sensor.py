"""Historical sensor using ha-historical-sensor library for Energy OWL CM160 integration."""

import asyncio
import logging
from datetime import datetime
from typing import Any

from homeassistant.util import dt as dt_util

from homeassistant_historical_sensor import (
    HistoricalSensor,
    HistoricalState,
    PollUpdateMixin,
)
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


class OwlHistoricalCurrentSensor(PollUpdateMixin, HistoricalSensor, OwlEntity, SensorEntity):
    """Historical current sensor that pushes historical data to Home Assistant using ha-historical-sensor."""

    _attr_name = "CM160 - Historical Current"
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: OwlDataUpdateCoordinator, config_entry: ConfigEntry) -> None:
        """Initialize the historical sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{self._device_unique_id}-historical-current"

        # Historical data processing attributes
        self._processed_count = 0
        self._chunks_pushed = 0
        self._last_push_time: datetime | None = None
        self._push_task: asyncio.Task | None = None
        self._chunk_size = 500
        self._processing_complete = False
        self._acquisition_start_time: datetime | None = None
        self._acquisition_wait_time = 60  # Wait 1 minute before starting to push
        self._pending_historical_states: list[HistoricalState] = []
        self._completion_notification_sent = False

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
        return self.coordinator.connected and (
            self.coordinator.last_update_success or
            (self.coordinator.data and self.coordinator.data.get("connected", False))
        )

    @property
    def native_value(self) -> float | None:
        """Return None for historical sensor - data is pushed via historical states."""
        # Historical sensors should not have a current state value
        # All data is pushed through the historical mechanism
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return diagnostic attributes."""
        attrs = super().extra_state_attributes

        if self.coordinator.data:
            total_historical = self.coordinator.data.get("historical_data_count", 0)
            historical_complete = self.coordinator.data.get("historical_data_complete", False)

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
                    "pending_states_count": len(self._pending_historical_states),
                })

        return attrs

    def is_processing_complete(self) -> bool:
        """Return True if processing is complete."""
        return self._processing_complete

    async def async_update_historical(self) -> None:
        """Update historical states - required by HistoricalSensor."""
        # This is called by the HistoricalSensor framework
        # We populate _attr_historical_states with pending data
        if self._pending_historical_states:
            self._attr_historical_states = self._pending_historical_states.copy()
            _LOGGER.debug("Updated historical states with %d pending states", len(self._pending_historical_states))
        else:
            self._attr_historical_states = []

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        super()._handle_coordinator_update()

        if self.coordinator.data and self.coordinator.data.get("connected", False):
            # Start processing task if not already running and not already complete
            if not self._processing_complete and (self._push_task is None or self._push_task.done()):
                self._push_task = self.hass.async_create_task(self._process_historical_data())

    async def _process_historical_data(self) -> None:
        """Process historical data in chunks and push to HA using HistoricalSensor."""
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
                                    "message": f"Starting import of {len(historical_data)} historical records from CM160 device using HistoricalSensor. Estimated {estimated_chunks} chunks to process.",
                                    "notification_id": f"energy_owl_historical_import_started_{self._device_unique_id}",
                                },
                            )
                        )

                # Sort by timestamp (oldest first for proper historical order)
                historical_data.sort(key=lambda x: x["timestamp"])

                # Calculate which chunk to process next
                start_idx = self._processed_count
                end_idx = min(start_idx + self._chunk_size, len(historical_data))

                # Check if we have new data to process
                if start_idx >= len(historical_data):
                    # No more data to process
                    if self.coordinator.data.get("historical_data_complete", False):
                        # Push any remaining states
                        if self._pending_historical_states:
                            await self._push_pending_states()

                        # Create a persistent notification for completion (only once)
                        if not self._completion_notification_sent:
                            self._completion_notification_sent = True
                            self.hass.async_create_task(
                                self.hass.services.async_call(
                                    "persistent_notification",
                                    "create",
                                    {
                                        "title": "Energy OWL Historical Data Import Complete",
                                        "message": f"Successfully imported {self._processed_count} historical records from CM160 device using HistoricalSensor in {self._chunks_pushed} chunks.",
                                        "notification_id": f"energy_owl_historical_import_complete_{self._device_unique_id}",
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
                    await self._add_chunk_to_pending_states(chunk, self._chunks_pushed + 1)
                    self._processed_count = end_idx
                    self._chunks_pushed += 1
                    self._last_push_time = datetime.now()

                    # Push states if we have enough or this is the last chunk
                    if len(self._pending_historical_states) >= self._chunk_size or end_idx >= len(historical_data):
                        await self._push_pending_states()

                    # Update the entity state to reflect progress
                    self.async_write_ha_state()

                    _LOGGER.info(
                        "Processed chunk %d with %d records (total processed: %d/%d)",
                        self._chunks_pushed,
                        len(chunk),
                        self._processed_count,
                        len(historical_data)
                    )

                # Small delay between chunks to avoid overwhelming HA
                await asyncio.sleep(1)

        except Exception as err:
            _LOGGER.error("Error in historical data processing task: %s", err, exc_info=True)

    async def _add_chunk_to_pending_states(self, chunk: list, chunk_number: int) -> None:
        """Add a chunk of historical data to pending states."""
        try:
            _LOGGER.debug("Processing chunk %d with %d records", chunk_number, len(chunk))
            for i, record in enumerate(chunk):
                # Ensure timestamp has timezone info
                timestamp = record["timestamp"]

                # Convert to timezone-aware datetime in Home Assistant's timezone
                if timestamp.tzinfo is None:
                    # If naive datetime, assume it's in the local timezone
                    timestamp = dt_util.as_local(timestamp)
                else:
                    # If already timezone-aware, convert to Home Assistant's timezone
                    timestamp = dt_util.as_local(timestamp)

                # Double-check that we have timezone info
                if timestamp.tzinfo is None:
                    _LOGGER.error("Failed to add timezone info to timestamp: %s", timestamp)
                    # Fallback: use current timezone
                    timestamp = timestamp.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)

                # Create HistoricalState objects for each record
                historical_state = HistoricalState(
                    state=record["current"],
                    dt=timestamp
                )
                self._pending_historical_states.append(historical_state)

                # Log first and last record of each chunk for debugging
                if i == 0 or i == len(chunk) - 1:
                    _LOGGER.debug("Record %d: current=%s, timestamp=%s (tzinfo=%s)", i, record["current"], timestamp, timestamp.tzinfo)

            _LOGGER.debug(
                "Added chunk %d with %d records to pending states (total pending: %d)",
                chunk_number,
                len(chunk),
                len(self._pending_historical_states)
            )

        except Exception as err:
            _LOGGER.error("Error adding chunk %d to pending states: %s", chunk_number, err)

    async def _push_pending_states(self) -> None:
        """Push pending historical states to Home Assistant."""
        if not self._pending_historical_states:
            return

        try:
            # Update the historical states attribute
            await self.async_update_historical()

            # Call the HistoricalSensor method to write states to HA
            await self.async_write_ha_historical_states()

            _LOGGER.info(
                "Successfully pushed %d historical states to Home Assistant",
                len(self._pending_historical_states)
            )

            # Clear pending states after successful push
            self._pending_historical_states.clear()

        except Exception as err:
            _LOGGER.error("Error pushing %d pending states to HA: %s", len(self._pending_historical_states), err)

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