"""DataUpdateCoordinator for Energy OWL CM160 integration."""

import asyncio
import logging
import time
from datetime import timedelta
from typing import Any, TypedDict

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from owlsensor import CMDataCollector
from serialx import SerialException

from .collector import TimestampedCollector, get_async_datacollector
from .const import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_DELAY,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
    DOMAIN,
    MODEL,
)

_LOGGER = logging.getLogger(__name__)


class CoordinatorDiagnostics(TypedDict):
    """Public, serializable lifecycle diagnostics."""

    connected: bool
    last_error: str | None
    last_update_success: bool
    total_updates: int
    error_count: int
    historical_complete: bool
    historical_records: int
    generation: int
    batch_revision: int
    acknowledged: bool
    pushers_registered: int
    all_pushers_complete: bool
    auto_recovery_enabled: bool
    recovery_attempts: int
    max_recovery_attempts: int
    collector: dict[str, Any]


class OwlDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the Energy OWL CM160."""

    HISTORICAL_DATA_TIMEOUT = 120  # seconds without new history before closing a batch
    HISTORICAL_BATCH_MAX_AGE = 120  # bound import latency during continuous streaming

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
        self._collector_lock = asyncio.Lock()
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
        self._historical_snapshot_size = 0
        self._last_new_historical_record_time: float | None = None
        self._historical_batch_started_time: float | None = None
        self._historical_completion_time: float | None = None
        self._auto_recovery_enabled = True
        self._auto_recovery_timeout = 300  # 5 minutes
        self._recovery_attempts = 0
        self._max_recovery_attempts = 3
        self._historical_data_pushers: list = []  # Track registered pushers
        self._all_pushers_complete = False
        self.historical_sync_generation = 0
        self.historical_batch_revision = 0
        self._realtime_listeners: list = []  # Track real-time data listeners

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval),
        )

    def diagnostics_snapshot(self) -> CoordinatorDiagnostics:
        """Return a public snapshot of connection, sync and recovery state."""
        return {
            "connected": self.connected, "last_error": self.last_error,
            "last_update_success": self.last_update_success,
            "total_updates": self.total_updates, "error_count": self.error_count,
            "historical_complete": self.historical_data_complete,
            "historical_records": self.historical_data_count,
            "generation": self.historical_sync_generation,
            "batch_revision": self.historical_batch_revision,
            "acknowledged": self.historical_sync_acknowledged,
            "pushers_registered": len(self._historical_data_pushers),
            "all_pushers_complete": self._all_pushers_complete,
            "auto_recovery_enabled": self._auto_recovery_enabled,
            "recovery_attempts": self._recovery_attempts,
            "max_recovery_attempts": self._max_recovery_attempts,
            "collector": (self.data or {}).get("debug_info", {}),
        }

    async def _async_setup(self) -> None:
        """Set up the coordinator."""
        await self._async_connect()

    async def _async_connect(self) -> None:
        async with self._collector_lock:
            return await self._async_connect_unlocked()

    async def _async_connect_unlocked(self) -> None:
        """Connect to the OWL device."""
        if self._collector is not None:
            await self.async_disconnect_unlocked()
        self._reset_import_session()
        self._historical_data_complete = False
        self._historical_data_count = 0
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
            if not await self._collector.connect():
                raise SerialException(f"Could not open serial port {self.port}")
            _LOGGER.debug("Collector.connect() completed")

            self._connected = True
            self._last_error = None
            self._historical_data_complete = False
            self._historical_data_count = 0
            _LOGGER.info(
                "Successfully connected to OWL device at %s. "
                "Historical and live packets may arrive interleaved.",
                self.port
            )
        except Exception as err:
            self._connected = False
            self._last_error = str(err)
            _LOGGER.error("Failed to connect to OWL device at %s: %s", self.port, err)
            raise UpdateFailed(f"Failed to connect to device: {err}") from err

    async def _async_update_data(self) -> dict[str, Any]:
        """Serialize a complete poll against reset, snapshots and reconnect."""
        async with self._collector_lock:
            return await self._async_update_data_unlocked()

    async def _async_update_data_unlocked(self) -> dict[str, Any]:
        """Unified data fetch method - handles both historical and real-time data transparently."""
        _LOGGER.debug(
            "Starting update cycle. Connected: %s, Historical Complete: %s",
            self._connected,
            self._historical_data_complete,
        )
        if not self._connected or self._collector is None:
            _LOGGER.debug("Not connected, attempting to connect.")
            await self._async_connect_unlocked()
            if not self._collector:
                raise UpdateFailed("Collector is not available after connection attempt.")

        for attempt in range(self.max_retries + 1):
            try:
                self._total_updates += 1
                current = None
                debug_info = {}
                new_historical_records = []

                # Keep checking history even while live packets are arriving.
                _LOGGER.debug("Checking historical data status. Complete: %s", self._historical_data_complete)
                new_historical_records = await self._process_and_consume_historical_data_unlocked()

                if (self._historical_data_complete and not self._historical_data_pushers
                        and not self.historical_sync_acknowledged):
                    await self._discard_imported_history_unlocked()

                # Phase 2: Always attempt to get a real-time reading.
                # Live packets can arrive while history is still being collected.
                _LOGGER.debug("Attempting to fetch current reading.")
                current, sample_timestamp = await self._read_live_sample_unlocked()
                if sample_timestamp is None or not 0 <= (dt_util.utcnow() - sample_timestamp).total_seconds() <= 90:
                    current = None

                # Add detailed logging for real-time mode issues and check for auto-recovery
                if current is None and self._historical_data_complete:
                    if self._historical_completion_time is None:
                        self._historical_completion_time = time.monotonic()
                        _LOGGER.info("Historical data completed. Starting real-time mode timer for automatic recovery.")

                    # Check if we need automatic recovery
                    elapsed_since_completion = time.monotonic() - self._historical_completion_time
                    if (self._auto_recovery_enabled and
                        not any(not p.is_processing_complete() for p in self._historical_data_pushers) and
                        elapsed_since_completion > self._auto_recovery_timeout and
                        self._recovery_attempts < self._max_recovery_attempts):

                        _LOGGER.warning(
                            "No real-time data for %.1f minutes after historical completion. "
                            "Attempting automatic recovery (attempt %d/%d).",
                            elapsed_since_completion / 60,
                            self._recovery_attempts + 1,
                            self._max_recovery_attempts
                        )

                        await self._attempt_automatic_recovery_unlocked()
                        return self.data  # Return existing data to avoid update failure

                    elif elapsed_since_completion > 60:  # Log warning after 1 minute
                        _LOGGER.warning(
                            "Historical data complete but still no real-time reading after %d updates "
                            "(%.1f minutes). Device may not have transitioned to real-time mode properly.",
                            self._total_updates,
                            elapsed_since_completion / 60
                        )

                _LOGGER.debug("Got current reading: %s", current)

                # Reset recovery state if we got real-time data
                if current is not None and self._historical_data_complete:
                    if self._recovery_attempts > 0:
                        _LOGGER.info("Real-time data restored. Resetting automatic recovery state.")
                        # Send success notification if we had attempted recovery
                        await self.hass.services.async_call(
                            "persistent_notification",
                            "create",
                            {
                                "title": "Energy OWL Recovery Success",
                                "message": "Real-time data has been restored successfully. Device is now operating normally.",
                                "notification_id": "energy_owl_recovery_success",
                            },
                        )

                    # Reset recovery state
                    self._recovery_attempts = 0
                    self._auto_recovery_enabled = True
                    self._historical_completion_time = None

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

                # Broadcast real-time data to listeners if we have a current reading
                if current is not None:
                    await self._broadcast_realtime_data(current)

                return {
                     "current": current,
                     "sample_timestamp": sample_timestamp,
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
                            await self._async_connect_unlocked()
                            _LOGGER.info("Reconnection successful")
                        except Exception as connect_err:
                            _LOGGER.warning("Reconnection failed: %s", connect_err, exc_info=True)
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

    async def _read_live_sample(self):
        """Read a coherent value/timestamp pair without racing serial lifecycle."""
        async with self._collector_lock:
            return await self._read_live_sample_unlocked()

    async def _read_live_sample_unlocked(self):
        collector = self._collector
        if collector is None:
            return None, None
        if isinstance(collector, TimestampedCollector):
            return collector.get_live_sample()
        # Only test doubles use this fallback; the runtime factory is pinned.
        current = await self.hass.async_add_executor_job(collector.get_current)
        return current, dt_util.utcnow()

    async def _process_and_consume_historical_data(self) -> list:
        async with self._collector_lock:
            return await self._process_and_consume_historical_data_unlocked()

    async def _process_and_consume_historical_data_unlocked(self) -> list:
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
            if new_count and self._historical_batch_started_time is None:
                self._historical_batch_started_time = time.monotonic()
            if new_count > self._last_historical_check:
                if self._historical_data_complete:
                    # A live packet or a quiet period is not an end-of-history
                    # marker. Reopen imports when another history batch arrives.
                    self.historical_batch_revision += 1
                    self._historical_data_complete = False
                    self._all_pushers_complete = False
                    self._historical_completion_time = None
                new_records = historical_data[self._last_historical_check:]
                _LOGGER.debug("Processing %d new historical records", len(new_records))
                self._last_historical_check = new_count
                # Reset our own timeout timer since we just got fresh data
                if self._last_new_historical_record_time is None:
                    _LOGGER.debug("Started historical data timeout timer.")
                self._last_new_historical_record_time = time.monotonic()
            elif (new_count == self._last_historical_check and new_count > 0
                  and self._last_new_historical_record_time is None):
                _LOGGER.info("Historical data count stable at %d records. Starting completion timeout.", new_count)
                self._last_new_historical_record_time = time.monotonic()

            self._historical_data_count = new_count

            # Live and historical packets are interleaved on real devices.
            # The library's completion flag is sticky after the first live
            # packet. Close on silence OR a bounded batch age so a continuous
            # history stream cannot indefinitely postpone persistence/import.
            complete_from_timeout = False
            if not self._historical_data_complete and self._last_new_historical_record_time is not None:
                elapsed = time.monotonic() - self._last_new_historical_record_time
                if elapsed > self.HISTORICAL_DATA_TIMEOUT:
                    _LOGGER.debug(
                        "No new historical data for over %s seconds (%.1f minutes). Closing batch with %d records",
                        self.HISTORICAL_DATA_TIMEOUT,
                        self.HISTORICAL_DATA_TIMEOUT / 60,
                        self._historical_data_count,
                    )
                    complete_from_timeout = True
            elif (not self._historical_data_complete and self._last_new_historical_record_time is None
                  and self._historical_data_count == 0 and self._total_updates > 1):
                self._last_new_historical_record_time = time.monotonic()

            batch_age_reached = (
                self._historical_batch_started_time is not None
                and time.monotonic() - self._historical_batch_started_time
                >= self.HISTORICAL_BATCH_MAX_AGE
            )
            if (complete_from_timeout or batch_age_reached) and not self._historical_data_complete:
                _LOGGER.info(
                    "Closing historical import batch (%s).",
                    "maximum batch age" if batch_age_reached else "history buffer quiet",
                )
                self._historical_data_complete = True
                self._fire_completion_event()
                if not self._historical_data_pushers:
                    # Historical import disabled: discard the local batch directly.
                    _LOGGER.info("No pushers registered; discarding the local history batch.")
                    await self._discard_imported_history_unlocked()
                else:
                    _LOGGER.info(
                        "Historical batch ready. Waiting for %d pushers before local buffer cleanup.",
                        len(self._historical_data_pushers)
                    )

            return new_records

        except Exception as err:
            _LOGGER.warning("Error processing historical data: %s", err, exc_info=True)
            return []

    def _fire_completion_event(self) -> None:
        """Fire the historical data completion event."""
        port_safe = self.port.replace("/", "-").replace("\\", "-")
        self.hass.bus.fire(
            f"{DOMAIN}_historical_data_complete",
            {"device_port": self.port, "device_id": f"CM160-{port_safe}"},
        )
        _LOGGER.debug("Fired historical data completion event.")

    @property
    def historical_sync_acknowledged(self) -> bool:
        """Return whether the current batch has completed local buffer cleanup.

        The legacy property name does not imply a device acknowledgement.
        """
        return self._all_pushers_complete

    async def _discard_imported_history(self) -> None:
        generation = self.historical_sync_generation
        revision = self.historical_batch_revision
        async with self._collector_lock:
            if (generation != self.historical_sync_generation
                    or revision != self.historical_batch_revision):
                return
            return await self._discard_imported_history_unlocked()

    async def _discard_imported_history_unlocked(self) -> None:
        """Discard only the imported local prefix; no device command is sent."""
        if not self._collector:
            raise UpdateFailed("Collector unavailable during historical buffer cleanup")

        generation = self.historical_sync_generation
        try:
            count = (self._historical_snapshot_size if self._historical_data_pushers
                     else self._last_historical_check)
            if isinstance(self._collector, TimestampedCollector):
                # Do not await: serial parsing runs on this event loop too.
                # Packets appended during Store/Recorder awaits must survive.
                self._collector.discard_historical_prefix(count)
            else:
                # Test doubles only; the runtime factory uses TimestampedCollector.
                await self.hass.async_add_executor_job(self._collector.clear_historical_data)
            self._last_historical_check = max(0, self._last_historical_check - count)
            self._historical_snapshot_size = 0
            self._historical_batch_started_time = None
            if generation == self.historical_sync_generation:
                self._all_pushers_complete = True
            _LOGGER.info("Imported historical prefix discarded from the local buffer; device streaming is unchanged.")
        except Exception as err:
            raise UpdateFailed("Could not discard imported historical buffer") from err

    async def _attempt_automatic_recovery(self) -> None:
        async with self._collector_lock:
            await self._attempt_automatic_recovery_unlocked()

    async def _attempt_automatic_recovery_unlocked(self) -> None:
        """Attempt automatic recovery when device is stuck."""
        self._recovery_attempts += 1

        try:
            _LOGGER.info("Starting automatic recovery attempt %d/%d", self._recovery_attempts, self._max_recovery_attempts)

            # Create a persistent notification about the recovery attempt
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "Energy OWL Automatic Recovery",
                    "message": f"CM160 device appears stuck. Attempting automatic recovery (attempt {self._recovery_attempts}/{self._max_recovery_attempts}).",
                    "notification_id": f"energy_owl_auto_recovery_{self._recovery_attempts}",
                },
            )

            # Step 1: Disconnect current connection
            _LOGGER.info("Disconnecting from device for recovery...")
            await self.async_disconnect_unlocked()

            # Step 2: Wait a moment
            await asyncio.sleep(2)

            # Step 3: Reset state variables
            self._connected = False
            # Reconnection starts a fresh history/import generation.
            self._historical_completion_time = None
            self._last_error = None

            # Step 4: Reconnect
            _LOGGER.info("Reconnecting to device...")
            await self._async_connect_unlocked()

            # Step 5: Send success notification
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "Energy OWL Recovery Complete",
                    "message": "Automatic recovery completed. Device reconnected and should resume normal operation.",
                    "notification_id": f"energy_owl_recovery_complete_{self._recovery_attempts}",
                },
            )

            _LOGGER.info("Automatic recovery attempt %d completed successfully", self._recovery_attempts)

        except Exception:
            _LOGGER.exception("Automatic recovery attempt %d failed", self._recovery_attempts)

            # Disable auto-recovery if we've reached max attempts
            if self._recovery_attempts >= self._max_recovery_attempts:
                self._auto_recovery_enabled = False
                _LOGGER.warning(
                    "Maximum recovery attempts (%d) reached. Disabling automatic recovery. "
                    "Manual intervention may be required.",
                    self._max_recovery_attempts
                )

                # Send final notification
                await self.hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "title": "Energy OWL Recovery Failed",
                        "message": f"Automatic recovery failed after {self._max_recovery_attempts} attempts. Manual intervention required. Try using the 'force_reconnect' service or physically reset the CM160 device.",
                        "notification_id": "energy_owl_recovery_failed",
                    },
                )

    def register_historical_pusher(self, pusher) -> None:
        """Register a historical data pusher."""
        if pusher not in self._historical_data_pushers:
            self._historical_data_pushers.append(pusher)
            _LOGGER.debug("Registered historical data pusher. Total pushers: %d", len(self._historical_data_pushers))

    def unregister_historical_pusher(self, pusher) -> None:
        """Unregister a historical data pusher."""
        if pusher in self._historical_data_pushers:
            self._historical_data_pushers.remove(pusher)
            _LOGGER.debug("Unregistered historical data pusher. Total pushers: %d", len(self._historical_data_pushers))

    async def notify_pusher_complete(self, pusher) -> None:
        """Notify that a pusher has completed processing."""
        _LOGGER.info("Pusher completed processing historical data.")

        if pusher not in self._historical_data_pushers or not self._historical_data_complete:
            return

        # Check if all pushers are complete
        all_complete = True
        for registered_pusher in self._historical_data_pushers:
            if (hasattr(registered_pusher, 'is_processing_complete')
                    and not registered_pusher.is_processing_complete()):
                all_complete = False
                break

        if all_complete and not self._all_pushers_complete:
            _LOGGER.info("All historical data pushers have completed. Cleaning up the local history buffer.")
            await self._discard_imported_history()

            # Send notification about completion (best-effort; may be unavailable in tests)
            try:
                await self.hass.services.async_call(
                    "persistent_notification",
                    "create",
                    {
                        "title": "Energy OWL Historical Processing Complete",
                        "message": "Historical statistics have been queued for Recorder and the imported local buffer has been cleaned up. Device streaming continues independently.",
                        "notification_id": "energy_owl_processing_complete",
                    },
                )
            except Exception:
                _LOGGER.debug("Completion notification unavailable", exc_info=True)

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

    async def get_historical_data(self, *, strict: bool = False) -> list:
        async with self._collector_lock:
            return await self.get_historical_data_unlocked(strict=strict)

    async def get_historical_data_unlocked(self, *, strict: bool = False) -> list:
        """Return the historical data from the collector."""
        if not self._collector:
            if strict:
                raise UpdateFailed("Collector unavailable during historical import")
            return []

        try:
            records = await self.hass.async_add_executor_job(
                self._collector.get_historical_data
            )
            if strict:
                self._historical_snapshot_size = len(records)
            return records
        except Exception as err:
            _LOGGER.warning("Error getting historical data: %s", err)
            if strict:
                raise UpdateFailed("Could not read historical data") from err
            return []

    def register_realtime_listener(self, listener) -> None:
        """Register a real-time data listener."""
        if listener not in self._realtime_listeners:
            self._realtime_listeners.append(listener)
            _LOGGER.debug("Registered real-time listener. Total listeners: %d", len(self._realtime_listeners))

    def unregister_realtime_listener(self, listener) -> None:
        """Unregister a real-time data listener."""
        if listener in self._realtime_listeners:
            self._realtime_listeners.remove(listener)
            _LOGGER.debug("Unregistered real-time listener. Total listeners: %d", len(self._realtime_listeners))

    async def _broadcast_realtime_data(self, current: float) -> None:
        """Broadcast real-time current data to all listeners."""
        if not self._realtime_listeners:
            return

        timestamp = dt_util.now()

        for listener in self._realtime_listeners:
            try:
                if hasattr(listener, 'on_realtime_data'):
                    await listener.on_realtime_data(current, timestamp)
            except Exception:
                _LOGGER.exception("Error broadcasting real-time data to listener")

    async def async_reset_historical_data(self) -> None:
        async with self._collector_lock:
            return await self.async_reset_historical_data_unlocked()

    async def async_reset_historical_data_unlocked(self) -> None:
        """Reset historical data state — public interface for service calls."""
        self._reset_import_session()
        self._historical_data_complete = False
        if self._collector:
            await self.hass.async_add_executor_job(
                self._collector.clear_historical_data
            )
        self._historical_data_count = 0

    def _reset_import_session(self) -> None:
        """Invalidate import completion and collection cursors on a new sync."""
        self.historical_sync_generation += 1
        self.historical_batch_revision = 0
        self._all_pushers_complete = False
        self._last_historical_check = 0
        self._historical_snapshot_size = 0
        self._last_new_historical_record_time = None
        self._historical_batch_started_time = None
        self._historical_completion_time = None
        self._historical_data_count = 0
        self.data = None

    async def async_reconnect(self) -> None:
        """Disconnect then reconnect — public interface for service calls."""
        async with self._collector_lock:
            await self.async_disconnect_unlocked()
            await self._async_connect_unlocked()

    async def async_disconnect(self) -> None:
        async with self._collector_lock:
            return await self.async_disconnect_unlocked()

    async def async_disconnect_unlocked(self) -> None:
        """Disconnect from the device."""
        self._reset_import_session()
        self._historical_data_complete = False
        if self._collector:
            _LOGGER.debug("Disconnecting from OWL device collector...")
            try:
                # The collector's disconnect method is async and handles task cleanup
                await self._collector.disconnect()
                _LOGGER.info("Successfully disconnected from OWL device.")
            except Exception as err:
                _LOGGER.warning(
                    "Error during collector disconnect: %s", err, exc_info=True
                )
            finally:
                self._collector = None
                self._connected = False
