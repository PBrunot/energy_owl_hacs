"""Durable, idempotent energy statistics through Home Assistant Recorder APIs."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .const import CONF_VOLTAGE, DEFAULT_VOLTAGE, DOMAIN
from .energy import (
    EnergyInterval,
    LiveEnergyIntegrator,
    history_intervals,
    positive_number,
    resolve_voltage,
)

if TYPE_CHECKING:
    from . import EnergyOwlConfigEntry
    from .coordinator import OwlDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)
RETENTION = timedelta(days=35)


def _hour(timestamp):
    return timestamp.replace(minute=0, second=0, microsecond=0)


class EnergyLedger:
    """Minute history overrides live intervals; closed old hours are immutable.

    Keep 35 days of minute resolution for overlapping 30-day device downloads.
    Older hourly totals retain the cumulative baseline without unbounded samples.
    Persist the entire ledger BEFORE submitting statistics or discarding local records.
    """

    def __init__(self, data=None):
        self.data = (
            data if data is not None else {"minutes": {}, "archive": {}, "cutoff": None}
        )
        if not isinstance(self.data, dict) or not all(
            k in self.data for k in ("minutes", "archive", "cutoff")
        ):
            raise ValueError("Invalid stored energy ledger")
        self.minutes = self.data["minutes"]
        self.archive = self.data["archive"]

    def add(self, interval: EnergyInterval, *, historical=False):
        start, end = interval.start, interval.end
        while start < end:
            minute = start.replace(second=0, microsecond=0)
            stop = min(end, minute + timedelta(minutes=1))
            key = minute.isoformat()
            if self.data["cutoff"] is None or key >= self.data["cutoff"]:
                slot = self.minutes.setdefault(key, {"history": None, "live": []})
                if historical:
                    # Freeze the first accepted voltage estimate for a device minute.
                    # A repeated download must never alter already accepted energy.
                    if slot["history"] is None:
                        slot["history"] = (
                            interval.power_w * (stop - start).total_seconds() / 3600000
                        )
                elif slot["history"] is None:
                    piece = [start.timestamp(), stop.timestamp(), interval.power_w]
                    if piece not in slot["live"]:
                        slot["live"].append(piece)
            start = stop

    @staticmethod
    def _value(slot):
        if slot["history"] is not None:
            return slot["history"]
        # Union intervals: retries/overlapping callbacks cannot double count time.
        end = float("-inf")
        total = 0.0
        for start, stop, power in sorted(slot["live"]):
            start = max(start, end)
            if stop > start:
                total += power * (stop - start) / 3600000
                end = stop
        return total

    def compact(self, now):
        cutoff = _hour(now - RETENTION).isoformat()
        if self.data["cutoff"] is not None:
            cutoff = max(cutoff, self.data["cutoff"])
        for key in list(self.minutes):
            if key < cutoff:
                hour = _hour(datetime.fromisoformat(key)).isoformat()
                self.archive[hour] = self.archive.get(hour, 0.0) + self._value(
                    self.minutes.pop(key)
                )
        self.data["cutoff"] = cutoff

    def statistics(self):
        hours = defaultdict(float, self.archive)
        for key, slot in self.minutes.items():
            hours[_hour(datetime.fromisoformat(key)).isoformat()] += self._value(slot)
        cumulative = 0.0
        result = []
        for hour, energy in sorted(hours.items()):
            cumulative += energy
            result.append(
                StatisticData(
                    start=datetime.fromisoformat(hour), sum=cumulative, state=cumulative
                )
            )
        return result


class OwlStatisticsImporter:
    """Entry-owned importer and live journal, independent of enabled entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: EnergyOwlConfigEntry,
        coordinator: OwlDataUpdateCoordinator,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator
        self._task: asyncio.Task[None] | None = None
        self._unsubscribe: Callable[[], None] | None = None
        self._generation: int | None = None
        self._revision: int | None = None
        self._complete = False
        self._closed = False
        self._loaded = False
        self._replay = True
        self._last_submitted = None
        self._observed_generation = None
        self._ledger = EnergyLedger()
        self._integrator = LiveEnergyIntegrator()
        self._store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.energy")
        self._lock = asyncio.Lock()
        coordinator.register_historical_pusher(self)

    async def async_load(self):
        if not self._loaded:
            data = await self._store.async_load()
            self._ledger = EnergyLedger(data)
            self._loaded = True

    def start(self) -> None:
        self._unsubscribe = self.coordinator.async_add_listener(self._handle_update)
        self._handle_update()

    @callback
    def _handle_update(self) -> None:
        if self._closed:
            return
        generation = self.coordinator.historical_sync_generation
        if (self._generation != generation
                or self._revision != self.coordinator.historical_batch_revision):
            self._complete = False
        if self._task is None or self._task.done():
            self._task = self.hass.async_create_task(self._import(generation))

    def is_processing_complete(self) -> bool:
        return (
            self._complete
            and self._generation == self.coordinator.historical_sync_generation
            and self._revision == self.coordinator.historical_batch_revision
        )

    def diagnostics_snapshot(self) -> dict[str, bool | int | None]:
        """Return import progress without exposing journal contents."""
        return {"loaded": self._loaded, "closed": self._closed,
                "processing": self._task is not None and not self._task.done(),
                "complete": self.is_processing_complete(), "generation": self._generation,
                "replay_pending": self._replay}

    def _voltage(self) -> float:
        # Historical records have no historical voltage. Freeze configured voltage,
        # rather than applying a varying live voltage to the same old download.
        return positive_number(self.entry.options.get(CONF_VOLTAGE, DEFAULT_VOLTAGE))

    def _metadata(self):
        port = self.entry.data.get("identity_port", self.coordinator.port).replace("/", "-").replace("\\", "-")
        return StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=f"Energy OWL CM160 ({self.coordinator.port}) Estimated Energy",
            source=DOMAIN,
            statistic_id=f"{DOMAIN}:{slugify(f'CM160-{port}-v2_energy')}",
            unit_class="energy",
            unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        )

    def _publish(self):
        stats = self._ledger.statistics()
        if stats and stats != self._last_submitted:
            async_add_external_statistics(self.hass, self._metadata(), stats)
            self._last_submitted = stats
        self._replay = False

    async def _import(self, generation: int) -> None:
        async with self._lock:
            revision = self.coordinator.historical_batch_revision
            try:
                await self.async_load()
                # Recovery must not depend on the serial device being reachable.
                if self._replay:
                    self._publish()
                if self._observed_generation != generation:
                    self._integrator.reset()
                    self._observed_generation = generation
                if (generation != self.coordinator.historical_sync_generation
                        or revision != self.coordinator.historical_batch_revision):
                    return
                data = self.coordinator.data or {}
                interval = self._integrator.sample(
                    data.get("current"),
                    resolve_voltage(self.hass, self.entry.options),
                    data.get("sample_timestamp"),
                    valid=self.coordinator.last_update_success
                    and data.get("connected", False),
                )
                changed = interval is not None
                if interval:
                    self._ledger.add(interval)
                collecting = not self.coordinator.historical_data_complete
                if not collecting and not self.is_processing_complete():
                    records = await self.coordinator.get_historical_data(strict=True)
                    if (generation != self.coordinator.historical_sync_generation
                            or revision != self.coordinator.historical_batch_revision):
                        return
                    intervals, rejected = history_intervals(records, self._voltage())
                    if rejected:
                        _LOGGER.warning(
                            "Skipped %d invalid or ambiguous historical minutes",
                            rejected,
                        )
                    for interval in intervals:
                        self._ledger.add(interval, historical=True)
                    changed = (
                        True  # persist even an empty batch before local cleanup
                    )
                if changed:
                    self._ledger.compact(dt_util.utcnow())
                    # Store is atomic; failure prevents local buffer cleanup. On restart replay
                    # the ledger even if the previous API submission was never committed.
                    await self._store.async_save(self._ledger.data)
                    self._replay = True
                if self._replay:
                    self._publish()
                if (generation != self.coordinator.historical_sync_generation
                        or revision != self.coordinator.historical_batch_revision):
                    return
                if not collecting:
                    self._generation = generation
                    self._revision = revision
                    self._complete = True
                    if not self.coordinator.historical_sync_acknowledged:
                        await self.coordinator.notify_pusher_complete(self)
            except Exception:
                _LOGGER.exception(
                    "Energy statistics journal/submission failed; retrying without discarding local history"
                )

    async def async_close(self) -> None:
        self._closed = True
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
        self.coordinator.unregister_historical_pusher(self)


def _build_hourly_statistics(records: list, voltage: float) -> list[StatisticData]:
    ledger = EnergyLedger()
    intervals, _ = history_intervals(records, voltage)
    for interval in intervals:
        ledger.add(interval, historical=True)
    return ledger.statistics()
