"""DataUpdateCoordinator for Energy OWL CM160 integration."""

import asyncio
import logging
import time
from datetime import timedelta
from typing import Any

from owlsensor import CMDataCollector, get_async_datacollector
from serial import SerialException

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_DELAY,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
    DOMAIN,
    MODEL,
)

_LOGGER = logging.getLogger(__name__)


class OwlDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the Energy OWL CM160."""

    def __init__(
        self,
        hass: HomeAssistant,
        port: str,
        update_interval: int = DEFAULT_SCAN_INTERVAL,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay: int = DEFAULT_RETRY_DELAY,
    ) -> None:
        """Initialize the coordinator."""
        self.port = port
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        self._collector: CMDataCollector | None = None
        self._connected = False
        self._last_error: str | None = None
        self._error_count = 0
        self._total_updates = 0
        self._historical_data_complete = False
        self._historical_data_count = 0
        self._last_historical_check = 0
        self._last_new_historical_record_time: float | None = None

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval),
        )

    async def _async_setup(self) -> None:
        """Set up the coordinator."""
        await self._async_connect()

    async def _async_connect(self) -> None:
        """Connect to the OWL device."""
        try:
            self._collector = await self.hass.async_add_executor_job(
                get_async_datacollector, self.port, MODEL, self.timeout
            )

            # Connect to the device - this will trigger historical data download
            _LOGGER.info(
                "Connecting to OWL device at %s. Initial connection may take several minutes "
                "while device sends historical data...",
                self.port
            )
            _LOGGER.debug("Calling collector.connect()")
            await self._collector.connect()
            _LOGGER.debug("Collector.connect() completed")

            self._connected = True
            self._last_error = None
            self._historical_data_complete = False
            self._historical_data_count = 0
            _LOGGER.info(
                "Successfully connected to OWL device at %s. "
                "Device will continue sending historical data before providing real-time updates.",
                self.port
            )
        except Exception as err:
            self._connected = False
            self._last_error = str(err)
            _LOGGER.error("Failed to connect to OWL device at %s: %s", self.port, err)
            raise UpdateFailed(f"Failed to connect to device: {err}") from err

    async def _async_update_data(self) -> dict[str, Any]:
        """Unified data fetch method - handles both historical and real-time data transparently."""
        _LOGGER.debug(
            "Starting update cycle. Connected: %s, Historical Complete: %s",
            self._connected,
            self._historical_data_complete,
        )
        if not self._connected or self._collector is None:
            _LOGGER.debug("Not connected, attempting to connect.")
            await self._async_connect()
            if not self._collector:
                raise UpdateFailed("Collector is not available after connection attempt.")

        for attempt in range(self.max_retries + 1):
            try:
                self._total_updates += 1
                current = None
                debug_info = {}
                new_historical_records = []

                # Phase 1: Process historical data until the sync is complete.
                # During this phase, `current` will be None.
                _LOGGER.debug("Checking historical data status. Complete: %s", self._historical_data_complete)
                if not self._historical_data_complete:
                    new_historical_records = await self._process_and_consume_historical_data()

                # Phase 2: Always attempt to get a real-time reading.
                # The library should return None if it's not available yet (i.e., during historical sync).
                _LOGGER.debug("Attempting to fetch current reading.")
                current = await self.hass.async_add_executor_job(
                    self._collector.get_current
                )
                _LOGGER.debug("Got current reading: %s", current)

                # If we received a real-time reading, historical sync is over.
                # This acts as a fallback if is_historical_data_complete() gets stuck.
                if current is not None and not self._historical_data_complete:
                    _LOGGER.info(
                        "Real-time reading received. Finalizing historical data sync."
                    )
                    await self._acknowledge_historical_sync_completion()
                    self._historical_data_complete = True

                # Always get latest debug info from the collector
                if self._collector and hasattr(self._collector, "get_debug_info"):
                    debug_info = await self.hass.async_add_executor_job(
                        self._collector.get_debug_info
                    )
                    _LOGGER.debug("Got debug info: %s", debug_info)

                self._last_error = None
                self._connected = True

                _LOGGER.debug(
                    "Successfully retrieved data. Current reading: %s (attempt %d/%d) [Historical: %s]",
                    f"{current} A" if current is not None else "N/A",
                    attempt + 1,
                    self.max_retries + 1,
                    "Complete" if self._historical_data_complete else "Syncing"
                )

                return {
                     "current": current,
                     "new_historical_records": new_historical_records,
                     "connected": self._connected,
                     "last_error": self._last_error,
                     "error_count": self._error_count,
                     "total_updates": self._total_updates,
                     "historical_data_complete": self._historical_data_complete,
                     "historical_data_count": self._historical_data_count,
                     "debug_info": debug_info,
                 }

            except Exception as err:
                self._error_count += 1
                self._last_error = str(err)
                _LOGGER.warning(
                    "Failed to get data from OWL device (attempt %d/%d): %s",
                    attempt + 1,
                    self.max_retries + 1,
                    err,
                    exc_info=True,
                )

                if attempt < self.max_retries:
                    # Exponential backoff
                    delay = self.retry_delay * (2 ** attempt)
                    _LOGGER.debug("Retrying in %d seconds...", delay)
                    await asyncio.sleep(delay)

                    # Try to reconnect on serial errors
                    if isinstance(err, SerialException):
                        _LOGGER.info("Serial error detected, attempting to reconnect to device...")
                        self._connected = False
                        try:
                            await self._async_connect()
                            _LOGGER.info("Reconnection successful")
                        except Exception as connect_err:
                            _LOGGER.warning("Reconnection failed: %s", connect_err)
                else:
                    # Final attempt failed
                    self._connected = False
                    _LOGGER.error(
                        "All %d attempts failed to get data from OWL device at %s. Device may be disconnected.",
                        self.max_retries + 1,
                        self.port,
                    )
                    raise UpdateFailed(f"Failed to get data after {self.max_retries + 1} attempts: {err}") from err

        # This should not be reached if the loop raises UpdateFailed, but as a fallback.
        raise UpdateFailed("Unexpected error in data update loop")

    async def _process_and_consume_historical_data(self) -> list:
        """Process historical data, determine if sync is complete, and return new records."""
        if not self._collector:
            return []

        new_records = []
        try:
            # 1. Get all available historical data and process any new records
            historical_data = await self.hass.async_add_executor_job(
                self._collector.get_historical_data
            )
            _LOGGER.debug("get_historical_data returned %d records", len(historical_data))

            new_count = len(historical_data)
            if new_count > self._last_historical_check:
                new_records = historical_data[self._last_historical_check:]
                _LOGGER.debug("Processing %d new historical records", len(new_records))
                await self._emit_historical_records(new_records)
                self._last_historical_check = new_count
                # Reset our own timeout timer since we just got fresh data
                if self._last_new_historical_record_time is None:
                    _LOGGER.debug("Started historical data timeout timer.")
                self._last_new_historical_record_time = time.monotonic()

            self._historical_data_count = new_count

            # 2. Check for completion using the library's method
            complete_from_library = await self.hass.async_add_executor_job(
                self._collector.is_historical_data_complete
            )
            if complete_from_library:
                _LOGGER.debug("Library reports historical data is complete.")

            # 3. Check for completion using our own coordinator-level timeout
            HISTORICAL_DATA_TIMEOUT = self.update_interval.total_seconds() * 2
            complete_from_timeout = False
            if self._last_new_historical_record_time is not None:
                elapsed = time.monotonic() - self._last_new_historical_record_time
                if elapsed > HISTORICAL_DATA_TIMEOUT:
                    _LOGGER.warning(
                        "No new historical data for over %s seconds. Forcing completion.",
                        HISTORICAL_DATA_TIMEOUT,
                    )
                    complete_from_timeout = True
            elif self._historical_data_count == 0 and self._total_updates > 1:
                self._last_new_historical_record_time = time.monotonic()

            if (complete_from_library or complete_from_timeout) and not self._historical_data_complete:
                _LOGGER.info(
                    "Historical data sync is considered complete. Acknowledging to transition to real-time."
                )
                await self._acknowledge_historical_sync_completion()
                self._historical_data_complete = True
                self._fire_completion_event()

            return new_records

        except Exception as err:
            _LOGGER.warning("Error processing historical data: %s", err, exc_info=True)
            return []

    async def _emit_historical_records(self, records: list) -> None:
        """Emit historical records as Home Assistant events."""
        for record in records:
            try:
                # Fire event for each historical record with proper domain prefix
                port_safe = self.port.replace("/", "-").replace("\\", "-")
                self.hass.bus.fire(
                    f"{DOMAIN}_historical_data",
                    {
                        "device_port": self.port,
                        "device_id": f"CM160-{port_safe}",
                        "timestamp": record["timestamp"].isoformat(),
                        "current": record["current"],
                    }
                )
            except Exception as err:
                _LOGGER.warning("Error emitting historical record event: %s", err)

    def _fire_completion_event(self) -> None:
        """Fire the historical data completion event."""
        port_safe = self.port.replace("/", "-").replace("\\", "-")
        self.hass.bus.fire(
            f"{DOMAIN}_historical_data_complete",
            {"device_port": self.port, "device_id": f"CM160-{port_safe}"},
        )
        _LOGGER.debug("Fired historical data completion event.")

    async def _acknowledge_historical_sync_completion(self) -> None:
        """Acknowledge historical data completion to the device to transition to real-time mode."""
        if not self._collector:
            return

        try:
            # This library call sends the necessary command to the device to
            # finalize the historical data sync and switch to real-time mode.
            _LOGGER.debug("Calling collector.clear_historical_data() to acknowledge sync completion.")
            await self.hass.async_add_executor_job(
                self._collector.clear_historical_data
            )
            _LOGGER.debug("Acknowledged historical data completion to device.")
        except Exception as err:
            _LOGGER.warning("Error acknowledging historical data completion: %s", err, exc_info=True)

    @property
    def connected(self) -> bool:
        """Return if the device is connected."""
        return self._connected

    @property
    def last_error(self) -> str | None:
        """Return the last error message."""
        return self._last_error

    @property
    def error_count(self) -> int:
        """Return the total error count."""
        return self._error_count

    @property
    def total_updates(self) -> int:
        """Return the total number of updates attempted."""
        return self._total_updates

    @property
    def historical_data_complete(self) -> bool:
        """Return if historical data collection is complete."""
        return self._historical_data_complete

    @property
    def historical_data_count(self) -> int:
        """Return the number of historical records collected."""
        return self._historical_data_count

    async def get_historical_data(self) -> list:
        """Return the historical data from the collector."""
        if not self._collector:
            return []

        try:
            return await self.hass.async_add_executor_job(
                self._collector.get_historical_data
            )
        except Exception as err:
            _LOGGER.warning("Error getting historical data: %s", err)
            return []

    async def async_disconnect(self) -> None:
        """Disconnect from the device."""
        if self._collector:
            def _cleanup(collector) -> None:
                """Clean up the collector object."""
                try:
                    # Properly close the collector if it has a close method
                    if hasattr(collector, 'close'):
                        collector.close()
                    elif hasattr(collector, 'disconnect'):
                        collector.disconnect()
                except Exception as err:
                    _LOGGER.debug("Error during collector cleanup: %s", err)
                finally:
                    del collector

            await self.hass.async_add_executor_job(_cleanup, self._collector)
            self._collector = None
            self._connected = False
            _LOGGER.debug("Disconnected from OWL device")