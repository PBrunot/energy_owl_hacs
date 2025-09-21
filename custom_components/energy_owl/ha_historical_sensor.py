"""Historical data processor sensor for Energy OWL CM160 integration."""

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
from homeassistant.const import UnitOfElectricCurrent, EntityCategory
from homeassistant.core import callback
from homeassistant.helpers.entity import DeviceInfo

from .base_entity import OwlEntity
from .const import DOMAIN
from .coordinator import OwlDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


class OwlHAHistoricalSensor(PollUpdateMixin, HistoricalSensor, OwlEntity, SensorEntity):
    """Historical data processor that pushes to the main current sensor stream."""

    _attr_name = "Historical Current Data"
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: OwlDataUpdateCoordinator, config_entry: ConfigEntry) -> None:
        """Initialize the historical processor sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{self._device_unique_id}-historical-processor"

        # Historical data processing attributes
        self._processed_count = 0
        self._chunks_pushed = 0
        self._last_push_time: datetime | None = None
        self._push_task: asyncio.Task | None = None
        self._chunk_size = 250  # Larger chunk size to reduce database writes
        self._processing_complete = False
        self._acquisition_start_time: datetime | None = None
        self._acquisition_wait_time = 60  # Reduced wait time for faster processing
        self._pending_historical_states: list[HistoricalState] = []
        self._completion_notification_sent = False
        # Use smaller memory footprint for tracking - limit to recent timestamps only
        self._pushed_timestamps: set[datetime] = set()  # Will be cleared periodically
        self._last_processed_timestamp: datetime | None = None
        self._max_timestamps_cache = 1000  # Limit memory usage
        
        # Database stress monitoring
        self._consecutive_db_errors = 0
        self._last_db_error_time: datetime | None = None
        self._adaptive_delay_multiplier = 1.0
        self._import_suspended = False
        self._max_consecutive_errors = 10  # Suspend import after 10 consecutive database errors

        # Register with coordinator
        self.coordinator.register_historical_pusher(self)
        self.coordinator.register_realtime_listener(self)

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
        """Return the current measurement from the complete data stream."""
        if not self.available:
            return None

        if not self.coordinator.data:
            return None

        # Return the current value from coordinator (real-time data)
        return self.coordinator.data.get("current")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return diagnostic attributes."""
        attrs = super().extra_state_attributes

        if self.coordinator.data:
            total_historical = self.coordinator.data.get("historical_data_count", 0)
            historical_complete = self.coordinator.data.get("historical_data_complete", False)
            connected = self.coordinator.data.get("connected", False)

            # Add simplified status for historical current data sensor
            if not connected:
                status = "Disconnected"
            elif self._import_suspended:
                status = f"Import suspended - {self._processed_count} records imported before database errors"
            elif self._processing_complete:
                status = f"Active - {self._processed_count} historical records imported"
            elif self._processed_count > 0:
                progress = (self._processed_count / total_historical * 100) if total_historical > 0 else 0
                current_value = self.coordinator.data.get("current")
                real_time_info = f" (showing real-time: {current_value:.1f}A)" if current_value is not None else ""
                status = f"Importing historical data - {progress:.0f}% complete{real_time_info}"
            elif historical_complete:
                status = "Ready to import historical data"
            elif total_historical > 0:
                status = f"Waiting to import {total_historical} historical records"
            else:
                status = "Waiting for historical data"

            # Keep only essential attributes
            attrs.update({
                "status": status,
                "historical_records_imported": self._processed_count,
                "total_historical_records": total_historical,
                "import_complete": self._processing_complete,
                "import_suspended": self._import_suspended,
                "last_import_time": self._last_push_time.isoformat() if self._last_push_time else None,
            })

            # Only show detailed progress during active processing
            if not self._processing_complete and self._processed_count > 0:
                progress = (self._processed_count / total_historical * 100) if total_historical > 0 else 0
                attrs["import_progress_percentage"] = round(progress, 1)

        return attrs

    def is_processing_complete(self) -> bool:
        """Return True if processing is complete."""
        return self._processing_complete

    async def async_update_historical(self) -> None:
        """Update historical states - required by HistoricalSensor."""
        # This is called by the HistoricalSensor framework
        # We populate _attr_historical_states with pending data (limit to save memory)
        if self._pending_historical_states:
            # Only copy what we need to avoid memory bloat
            limited_states = self._pending_historical_states[:self._chunk_size]
            self._attr_historical_states = limited_states
            _LOGGER.debug("Updated historical states with %d pending states (limited for memory)", len(limited_states))
        else:
            self._attr_historical_states = []

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        super()._handle_coordinator_update()
        
        # Always update state immediately when coordinator data changes
        # This ensures real-time values are shown even during historical import
        if self.coordinator.data and self.coordinator.data.get("current") is not None:
            _LOGGER.debug("Historical Current Data sensor updating with coordinator data: %s A", 
                         self.coordinator.data.get("current"))

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
                        estimated_batches = (len(historical_data) + 25 - 1) // 25  # Assuming 25 states per batch
                        estimated_time_hours = (estimated_batches * 4) / 3600  # 3s + 1s = 4s per batch
                        
                        self.hass.async_create_task(
                            self.hass.services.async_call(
                                "persistent_notification",
                                "create",
                                {
                                    "title": "Energy OWL Historical Data Import Started",
                                    "message": f"Starting import of {len(historical_data)} historical records. Estimated time: {estimated_time_hours:.1f} hours ({estimated_batches} batches of ~25 records each). Import will slow down automatically if database errors occur.",
                                    "notification_id": f"energy_owl_historical_import_started_{self._device_unique_id}",
                                },
                            )
                        )

                # Sort by timestamp (newest first to prioritize recent data)
                historical_data.sort(key=lambda x: x["timestamp"], reverse=True)

                # Filter out data we've already processed to avoid duplicates
                if self._last_processed_timestamp:
                    historical_data = [
                        record for record in historical_data
                        if record["timestamp"] > self._last_processed_timestamp
                    ]
                    _LOGGER.debug("Filtered %d new records after timestamp %s", len(historical_data), self._last_processed_timestamp)

                # Process data from beginning (most recent first)
                start_idx = 0
                end_idx = min(self._chunk_size, len(historical_data))

                # Check if we have new data to process
                if len(historical_data) == 0:
                    # No new data to process
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
                                        "message": f"Successfully imported {self._processed_count} historical records to CM160 Current sensor in {self._chunks_pushed} chunks.",
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

                        # Send notification that real-time data will now be written to database
                        self.hass.async_create_task(
                            self.hass.services.async_call(
                                "persistent_notification",
                                "create",
                                {
                                    "title": "Energy OWL Real-time Mode Enabled",
                                    "message": "Historical data processing complete. Real-time current readings are now being written to the database and will appear in historical graphs.",
                                    "notification_id": f"energy_owl_realtime_enabled_{self._device_unique_id}",
                                },
                            )
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
                    await self._add_chunk_to_pending_states(chunk, self._chunks_pushed + 1)
                    self._processed_count += len(chunk)
                    self._chunks_pushed += 1
                    self._last_push_time = datetime.now()

                    # Update the last processed timestamp to the oldest in this chunk
                    # (since we're processing newest first, the last item is the oldest)
                    self._last_processed_timestamp = chunk[-1]["timestamp"]

                    # Push states immediately after each chunk
                    await self._push_pending_states()

                    # Faster delay for large dataset imports - prioritize speed while maintaining safety
                    # Will scale up automatically if database errors occur
                    base_delay = 3  # 3 second base delay between chunks
                    adaptive_delay = int(base_delay * self._adaptive_delay_multiplier)
                    
                    if self._adaptive_delay_multiplier > 1.0:
                        _LOGGER.info(
                            "Using adaptive delay of %d seconds (%.1fx multiplier) due to database stress",
                            adaptive_delay,
                            self._adaptive_delay_multiplier
                        )
                    
                    await asyncio.sleep(adaptive_delay)

                    # Force garbage collection less frequently to reduce system stress
                    if self._chunks_pushed % 20 == 0:
                        import gc
                        gc.collect()
                        _LOGGER.debug("Performed garbage collection after %d chunks", self._chunks_pushed)

                    # Update the entity state to reflect progress
                    self.async_write_ha_state()

                    _LOGGER.info(
                        "Processed chunk %d with %d records (total processed: %d)",
                        self._chunks_pushed,
                        len(chunk),
                        self._processed_count
                    )
                else:
                    # No chunk to process, wait shorter and do memory cleanup
                    import gc
                    gc.collect()
                    await asyncio.sleep(10)

        except Exception as err:
            _LOGGER.error("Error in historical data processing task: %s", err, exc_info=True)

    async def _add_chunk_to_pending_states(self, chunk: list, chunk_number: int) -> None:
        """Add a chunk of historical data to pending states."""
        try:
            _LOGGER.debug("Processing chunk %d with %d records", chunk_number, len(chunk))
            for i, record in enumerate(chunk):
                # Ensure timestamp has timezone info
                timestamp = record["timestamp"]

                # Skip if we've already processed this timestamp
                if timestamp in self._pushed_timestamps:
                    continue

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

                # Track this timestamp as processed (with memory limit)
                self._pushed_timestamps.add(timestamp)

                # Periodically clear old timestamps to prevent memory bloat
                if len(self._pushed_timestamps) > self._max_timestamps_cache:
                    # Keep only the most recent timestamps
                    recent_timestamps = sorted(list(self._pushed_timestamps))[-self._max_timestamps_cache//2:]
                    self._pushed_timestamps = set(recent_timestamps)
                    _LOGGER.debug("Cleared old timestamps cache, keeping %d recent entries", len(self._pushed_timestamps))

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
        
        # Check if import has been suspended due to database errors
        if self._import_suspended:
            _LOGGER.debug("Historical import suspended - skipping database write")
            return

        # Limit the number of states we try to push at once to reduce database load
        # Use moderate batch size - balance between speed and database safety for large imports
        # Start with smaller batches, increase if no errors occur
        base_batch_size = 25 if self._consecutive_db_errors == 0 else max(5, 25 - (self._consecutive_db_errors * 3))
        batch_size = min(self._chunk_size, base_batch_size)
        states_to_push = self._pending_historical_states[:batch_size]
        if len(self._pending_historical_states) > batch_size:
            _LOGGER.debug("Limiting push to %d states (out of %d pending) to reduce database load",
                         len(states_to_push), len(self._pending_historical_states))

        try:
            # Update the historical states attribute with limited states
            self._attr_historical_states = states_to_push.copy()

            # Call the HistoricalSensor method to write states to HA
            # Add retry logic for database concurrency issues
            max_retries = 5
            for attempt in range(max_retries):
                try:
                    await self.async_write_ha_historical_states()
                    # Reset error counters on successful write
                    self._consecutive_db_errors = 0
                    # Gradually reduce adaptive delay multiplier on success
                    if self._adaptive_delay_multiplier > 1.0:
                        self._adaptive_delay_multiplier = max(1.0, self._adaptive_delay_multiplier * 0.9)
                    break
                except Exception as write_err:
                    error_str = str(write_err)
                    
                    # Handle SQLAlchemy StaleDataError specifically
                    if "StaleDataError" in error_str or "expected to update" in error_str:
                        self._consecutive_db_errors += 1
                        self._last_db_error_time = datetime.now()
                        
                        # Increase adaptive delay multiplier based on consecutive errors
                        if self._consecutive_db_errors > 3:
                            self._adaptive_delay_multiplier = min(5.0, self._adaptive_delay_multiplier * 1.5)
                            _LOGGER.warning(
                                "Database appears stressed (%d consecutive errors). Increasing delays by %.1fx",
                                self._consecutive_db_errors,
                                self._adaptive_delay_multiplier
                            )
                        
                        # Suspend import if too many consecutive errors
                        if self._consecutive_db_errors >= self._max_consecutive_errors and not self._import_suspended:
                            self._import_suspended = True
                            _LOGGER.error(
                                "Too many consecutive database errors (%d). Suspending historical data import to protect Home Assistant database.",
                                self._consecutive_db_errors
                            )
                            
                            # Send notification about suspension
                            self.hass.async_create_task(
                                self.hass.services.async_call(
                                    "persistent_notification",
                                    "create",
                                    {
                                        "title": "Energy OWL Import Suspended",
                                        "message": f"Historical data import has been suspended due to repeated database errors ({self._consecutive_db_errors} consecutive failures). The device will continue showing real-time data. Restart the integration to retry import.",
                                        "notification_id": f"energy_owl_import_suspended_{self._device_unique_id}",
                                    },
                                )
                            )
                        
                        if attempt < max_retries - 1:
                            # Exponential backoff with adaptive multiplier for database concurrency issues
                            base_delay = 5 * (2 ** attempt)  # 5, 10, 20, 40 seconds
                            delay = int(base_delay * self._adaptive_delay_multiplier)
                            _LOGGER.warning(
                                "Database concurrency error (attempt %d/%d): %s. Retrying in %d seconds (adaptive delay: %.1fx)...",
                                attempt + 1,
                                max_retries,
                                write_err,
                                delay,
                                self._adaptive_delay_multiplier
                            )
                            await asyncio.sleep(delay)
                        else:
                            _LOGGER.error(
                                "Failed to write historical states after %d attempts due to database concurrency issues. Skipping batch to prevent blocking.",
                                max_retries
                            )
                            # Don't raise the error - skip this batch to prevent blocking
                            break
                    else:
                        # Other errors - shorter retry with exponential backoff
                        if attempt < max_retries - 1:
                            delay = 3 * (2 ** attempt)  # 3, 6, 12, 24 seconds
                            _LOGGER.warning(
                                "Failed to write historical states (attempt %d/%d): %s. Retrying in %d seconds...",
                                attempt + 1,
                                max_retries,
                                write_err,
                                delay
                            )
                            await asyncio.sleep(delay)
                        else:
                            raise write_err

            _LOGGER.info(
                "Successfully pushed %d historical states to Historical Current Data sensor",
                len(states_to_push)
            )

            # Remove only the pushed states to save memory
            self._pending_historical_states = self._pending_historical_states[len(states_to_push):]

            # Minimal delay after successful writes - prioritize import speed
            # Still give recorder a moment to process but keep things moving
            await asyncio.sleep(1)  # 1 second delay after each batch write

        except Exception as err:
            _LOGGER.error("Error pushing %d pending states to HA: %s", len(states_to_push), err)
            # Don't clear pending states on error so we can retry later

    async def on_realtime_data(self, current: float, timestamp: datetime) -> None:
        """Handle real-time data events from the coordinator."""
        if not self._processing_complete:
            # Still processing historical data, don't add real-time data to database yet
            # but immediately update the entity state to show current readings
            _LOGGER.debug("Historical Current Data sensor updated with real-time value: %s A (import in progress)", current)
            self.async_write_ha_state()
            return

        try:
            # Skip if we've already processed this timestamp
            if timestamp in self._pushed_timestamps:
                _LOGGER.debug("Skipping duplicate real-time timestamp: %s", timestamp)
                return

            # Ensure timestamp has timezone info (same logic as historical processing)
            if timestamp.tzinfo is None:
                # If naive datetime, assume it's in the local timezone
                timestamp = dt_util.as_local(timestamp)
            else:
                # If already timezone-aware, convert to Home Assistant's timezone
                timestamp = dt_util.as_local(timestamp)

            # Double-check that we have timezone info
            if timestamp.tzinfo is None:
                _LOGGER.error("Failed to add timezone info to real-time timestamp: %s", timestamp)
                # Fallback: use current timezone
                timestamp = timestamp.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)

            # Track this timestamp as processed (with memory limit)
            self._pushed_timestamps.add(timestamp)

            # Periodically clear old timestamps to prevent memory bloat
            if len(self._pushed_timestamps) > self._max_timestamps_cache:
                # Keep only the most recent timestamps
                recent_timestamps = sorted(list(self._pushed_timestamps))[-self._max_timestamps_cache//2:]
                self._pushed_timestamps = set(recent_timestamps)
                _LOGGER.debug("Cleared old timestamps cache, keeping %d recent entries", len(self._pushed_timestamps))

            # Create a HistoricalState for the real-time data
            historical_state = HistoricalState(
                state=current,
                dt=timestamp
            )

            # Add to pending states for immediate processing
            self._pending_historical_states.append(historical_state)

            # Push the real-time data immediately to maintain continuous stream
            await self._push_pending_states()

            _LOGGER.debug("Added real-time data: current=%s, timestamp=%s", current, timestamp)

        except Exception as err:
            _LOGGER.error("Error handling real-time data: %s", err)

    async def async_will_remove_from_hass(self) -> None:
        """Cancel the processing task when entity is removed."""
        # Unregister from coordinator
        self.coordinator.unregister_historical_pusher(self)
        self.coordinator.unregister_realtime_listener(self)

        if self._push_task and not self._push_task.done():
            self._push_task.cancel()
            try:
                await self._push_task
            except asyncio.CancelledError:
                pass