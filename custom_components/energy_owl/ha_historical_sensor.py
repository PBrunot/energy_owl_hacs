"""Simple historical data processor sensor for Energy OWL CM160 integration."""

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


class OwlHAHistoricalSensor(PollUpdateMixin, HistoricalSensor, OwlEntity, SensorEntity):
    """Simple historical data processor that pushes to the main current sensor stream."""

    _attr_name = "Historical Current Data"
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_should_poll = False
    _attr_available = True

    def __init__(self, coordinator: OwlDataUpdateCoordinator, config_entry: ConfigEntry) -> None:
        """Initialize the historical processor sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{self._device_unique_id}-historical-processor"

        # Simple state tracking
        self._total_imported = 0
        self._total_available = 0
        self._import_complete = False
        self._last_imported_timestamp: datetime | None = None
        self._processing = False
        
        # Configurable processing parameters
        self._chunk_size = 25  # Small chunks to avoid database stress
        self._chunk_delay = 2.0  # Seconds between chunks
        self._batch_delay = 10.0  # Seconds between full data refreshes

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
        return self.coordinator.last_update_success or self.coordinator.connected


    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return diagnostic attributes."""
        attrs = super().extra_state_attributes

        if self.coordinator.data:
            self._total_available = self.coordinator.data.get("historical_data_count", 0)
            connected = self.coordinator.data.get("connected", False)

            # Simple status
            if not connected:
                status = "Disconnected"
            elif self._import_complete:
                status = f"Complete - {self._total_imported} records imported"
            elif self._processing:
                if self._total_available > 0:
                    progress = (self._total_imported / self._total_available) * 100
                    status = f"Importing - {progress:.0f}% complete"
                else:
                    status = f"Importing - {self._total_imported} records imported"
            else:
                status = "Waiting for historical data"

            attrs.update({
                "status": status,
                "historical_records_imported": self._total_imported,
                "total_historical_records": self._total_available,
                "import_complete": self._import_complete,
                "last_imported_timestamp": self._last_imported_timestamp.isoformat() if self._last_imported_timestamp else None,
            })

            # Progress percentage
            if self._processing and self._total_available > 0:
                progress = (self._total_imported / self._total_available) * 100
                attrs["import_progress_percentage"] = round(progress, 1)

        return attrs

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        super()._handle_coordinator_update()
        
        if (self.coordinator.data and 
            self.coordinator.data.get("connected", False) and 
            not self._import_complete and 
            not self._processing):
            # Start processing
            self.hass.async_create_task(self._import_historical_data())

    async def _import_historical_data(self) -> None:
        """Import historical data in simple batches."""
        if self._processing:
            return
            
        self._processing = True
        _LOGGER.info("Starting historical data import")
        
        try:
            while not self._import_complete:
                # Get historical data
                historical_data = await self.coordinator.get_historical_data()
                
                if not historical_data:
                    await asyncio.sleep(5)
                    continue
                
                self._total_available = len(historical_data)
                
                # Filter new records only
                new_records = []
                for record in historical_data:
                    if (self._last_imported_timestamp is None or 
                        record["timestamp"] > self._last_imported_timestamp):
                        new_records.append(record)
                
                if not new_records:
                    # No new records, we're done
                    self._import_complete = True
                    _LOGGER.info("Historical import complete - %d total records imported", self._total_imported)
                    break
                
                # Process in configurable chunks
                _LOGGER.info("Processing %d new records in chunks of %d", len(new_records), self._chunk_size)
                
                for i in range(0, len(new_records), self._chunk_size):
                    chunk = new_records[i:i + self._chunk_size]
                    chunk_num = (i // self._chunk_size) + 1
                    total_chunks = (len(new_records) + self._chunk_size - 1) // self._chunk_size
                    
                    _LOGGER.debug("Processing chunk %d/%d (%d records)", chunk_num, total_chunks, len(chunk))
                    
                    await self._process_chunk(chunk)
                    
                    # Configurable delay between chunks (except for last chunk)
                    if i + self._chunk_size < len(new_records):
                        _LOGGER.debug("Waiting %.1f seconds before next chunk", self._chunk_delay)
                        await asyncio.sleep(self._chunk_delay)
                
                # Check if coordinator says we're complete
                if self.coordinator.data.get("historical_data_complete", False):
                    self._import_complete = True
                    _LOGGER.info("Historical import complete - %d total records imported", self._total_imported)
                    break
                    
                # Configurable delay before checking for more data
                _LOGGER.debug("Waiting %.1f seconds before checking for more data", self._batch_delay)
                await asyncio.sleep(self._batch_delay)
                
        except Exception as err:
            _LOGGER.error("Error in historical import: %s", err)
        finally:
            self._processing = False
            self.async_write_ha_state()

    async def _process_chunk(self, chunk: list) -> None:
        """Process a chunk of historical records."""
        if not chunk:
            return
            
        # Convert to HistoricalState objects
        historical_states = []
        for record in chunk:
            timestamp = record["timestamp"]
            
            # Ensure timezone awareness
            if timestamp.tzinfo is None:
                timestamp = dt_util.as_local(timestamp)
            else:
                timestamp = dt_util.as_local(timestamp)
            
            try:
                current_value = float(record["current"])
                historical_state = HistoricalState(
                    state=current_value,
                    dt=timestamp
                )
                historical_states.append(historical_state)
            except (ValueError, TypeError):
                _LOGGER.warning("Skipping invalid record: %s", record)
                continue
        
        if not historical_states:
            return
            
        # Update the HistoricalSensor attribute
        self._attr_historical_states = historical_states
        
        try:
            # Push to Home Assistant
            await self.async_write_ha_historical_states()
            
            # Update counters
            self._total_imported += len(historical_states)
            self._last_imported_timestamp = max(record["timestamp"] for record in chunk)
            
            _LOGGER.debug("Imported chunk of %d records (total: %d)", 
                         len(historical_states), self._total_imported)
            
        except Exception as err:
            _LOGGER.error("Failed to import chunk: %s", err)
        
        # Update entity state
        self.async_write_ha_state()

    async def on_realtime_data(self, current: float, timestamp: datetime) -> None:
        """Handle real-time data events."""
        if not self._import_complete:
            # Still importing, just update display
            self.async_write_ha_state()
            return
        
        # Import is complete, add real-time data to database
        try:
            if timestamp.tzinfo is None:
                timestamp = dt_util.as_local(timestamp)
            else:
                timestamp = dt_util.as_local(timestamp)
            
            historical_state = HistoricalState(
                state=current,
                dt=timestamp
            )
            
            self._attr_historical_states = [historical_state]
            await self.async_write_ha_historical_states()
            
            _LOGGER.debug("Added real-time data: %s A at %s", current, timestamp)
            
        except Exception as err:
            _LOGGER.error("Error adding real-time data: %s", err)

    async def async_update_historical(self) -> None:
        """Update historical states - required by HistoricalSensor."""
        # Called by the HistoricalSensor framework when needed
        # Historical states are populated in _process_chunk and on_realtime_data methods
        if not self._attr_historical_states:
            self._attr_historical_states = []

    def is_processing_complete(self) -> bool:
        """Return True if processing is complete."""
        return self._import_complete

    async def async_will_remove_from_hass(self) -> None:
        """Clean up when entity is removed."""
        self.coordinator.unregister_historical_pusher(self)
        self.coordinator.unregister_realtime_listener(self)