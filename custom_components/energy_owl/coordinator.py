"""DataUpdateCoordinator for Energy OWL CM160 integration."""

import asyncio
import logging
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
            await self._collector.connect()

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
        if not self._connected or self._collector is None:
            await self._async_connect()

        for attempt in range(self.max_retries + 1):
            try:
                self._total_updates += 1
                current = None
                debug_info = {}

                # Phase 1: Process historical data until the sync is complete.
                # During this phase, `current` will be None.
                if not self._historical_data_complete:
                    await self._process_and_consume_historical_data()

                # Phase 2: Once historical sync is complete, get real-time current readings.
                if self._historical_data_complete:
                    current = await self.hass.async_add_executor_job(
                        self._collector.get_current
                    )

                # Always get latest debug info from the collector
                if self._collector and hasattr(self._collector, "get_debug_info"):
                    debug_info = await self.hass.async_add_executor_job(
                        self._collector.get_debug_info
                    )

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

    async def _process_and_consume_historical_data(self) -> None:
        """Process and consume historical data transparently, transitioning to real-time when complete."""
        if not self._collector:
            return
        try:
            # Get available historical data
            historical_data = await self.hass.async_add_executor_job(
                self._collector.get_historical_data
            )

            new_count = len(historical_data)
            if new_count > self._last_historical_check:
                new_records = historical_data[self._last_historical_check:]
                _LOGGER.debug("Processing %d new historical records", len(new_records))
                await self._emit_historical_records(new_records)
                self._last_historical_check = new_count

            # Update total count for the status sensor
            self._historical_data_count = new_count

            # Now, check if the device has finished sending all historical data
            complete = await self.hass.async_add_executor_job(
                self._collector.is_historical_data_complete
            )

            if complete and not self._historical_data_complete:
                _LOGGER.info(
                    "Historical data collection completed for device at %s. Acknowledging to transition to real-time.",
                    self.port
                )
                # This call tells the device we have received all historical data
                # and it can now switch to real-time mode.
                await self._acknowledge_historical_sync_completion()

                self._historical_data_complete = True

                # Fire completion event
                port_safe = self.port.replace('/', '-').replace('\\', '-')
                self.hass.bus.fire(
                    f"{DOMAIN}_historical_data_complete",
                    {
                        "device_port": self.port,
                        "device_id": f"CM160-{port_safe}"
                    }
                )

        except Exception as err:
            _LOGGER.warning("Error processing historical data: %s", err)

    async def _emit_historical_records(self, records: list) -> None:
        """Emit historical records as Home Assistant events."""
        for record in records:
            try:
                # Fire event for each historical record with proper domain prefix
                port_safe = self.port.replace('/', '-').replace('\\', '-')
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

    async def _acknowledge_historical_sync_completion(self) -> None:
        """Acknowledge historical data completion to the device to transition to real-time mode."""
        if not self._collector:
            return

        try:
            # This library call sends the necessary command to the device to
            # finalize the historical data sync and switch to real-time mode.
            await self.hass.async_add_executor_job(
                self._collector.clear_historical_data
            )
            _LOGGER.debug("Acknowledged historical data completion to device.")
        except Exception as err:
            _LOGGER.warning("Error acknowledging historical data completion: %s", err)

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