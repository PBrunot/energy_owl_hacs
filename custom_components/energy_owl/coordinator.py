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
        """Fetch data from the device."""
        if not self._connected or self._collector is None:
            await self._async_connect()

        for attempt in range(self.max_retries + 1):
            try:
                self._total_updates += 1

                # Get current reading
                current = await self.hass.async_add_executor_job(
                    self._collector.get_current
                )

                self._last_error = None
                self._connected = True

                _LOGGER.debug(
                    "Successfully retrieved current reading: %s A (attempt %d/%d)",
                    current,
                    attempt + 1,
                    self.max_retries + 1,
                )

                return {
                    "current": current,
                    "connected": self._connected,
                    "last_error": self._last_error,
                    "error_count": self._error_count,
                    "total_updates": self._total_updates,
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

        # This should never be reached, but just in case
        raise UpdateFailed("Unexpected error in data update")

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