"""Cumulative energy sensor for Energy OWL CM160 — required for Energy Dashboard."""

import logging
from collections import defaultdict
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import callback
from homeassistant.util import dt as dt_util

from .base_entity import OwlEntity
from .const import DOMAIN
from .coordinator import OwlDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# Compatibility shim: HA 2024.6+ uses StatisticMeanType; older builds used has_mean bool.
try:
    from homeassistant.components.recorder.models import StatisticMeanType
    _STAT_MEAN: dict = {"mean_type": StatisticMeanType.NONE}
except (ImportError, AttributeError):
    _STAT_MEAN: dict = {"has_mean": False}

from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import async_add_external_statistics


class OwlEnergySensor(OwlEntity, SensorEntity):
    """Cumulative energy in kWh — compatible with Energy Dashboard.

    Real-time energy is integrated from successive current readings.
    On first historical-data completion, past records are back-filled
    via async_add_external_statistics (official HA recorder API).
    """

    _attr_translation_key = "energy"
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 3

    def __init__(self, coordinator: OwlDataUpdateCoordinator, config_entry: ConfigEntry) -> None:
        """Initialize the energy sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{self._device_unique_id}-energy"
        self._total_kwh: float = 0.0
        self._last_update: datetime | None = None
        self._historical_backfill_done: bool = False

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success or self.coordinator.connected

    @property
    def native_value(self) -> float:
        """Return cumulative energy in kWh."""
        return round(self._total_kwh, 4)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose voltage source and backfill state."""
        attrs = super().extra_state_attributes
        attrs["voltage_used_v"] = self._get_voltage()
        attrs["historical_backfill_done"] = self._historical_backfill_done
        return attrs

    @callback
    def _handle_coordinator_update(self) -> None:
        """Integrate energy and trigger historical backfill when ready."""
        if not self.coordinator.data:
            super()._handle_coordinator_update()
            return

        current = self.coordinator.data.get("current")
        if current is not None:
            now = dt_util.utcnow()
            if self._last_update is not None:
                delta_hours = (now - self._last_update).total_seconds() / 3600
                self._total_kwh += (current * self._get_voltage() * delta_hours) / 1000
            self._last_update = now

        # Trigger backfill exactly once after historical sync completes.
        if (
            self.coordinator.data.get("historical_data_complete", False)
            and not self._historical_backfill_done
        ):
            self._historical_backfill_done = True
            self.hass.async_create_task(self._push_historical_statistics())

        super()._handle_coordinator_update()

    async def _push_historical_statistics(self) -> None:
        """Back-fill energy statistics from CM160 historical records."""
        records = await self.coordinator.get_historical_data()
        if not records:
            _LOGGER.debug("No historical records available for energy backfill.")
            return

        voltage = self._get_voltage()
        statistic_id = f"{DOMAIN}:{self._device_unique_id}_energy"

        metadata = StatisticMetaData(
            **_STAT_MEAN,
            has_sum=True,
            name=f"Energy OWL CM160 ({self.coordinator.port}) Energy",
            source=DOMAIN,
            statistic_id=statistic_id,
            unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        )

        stats = _build_hourly_statistics(records, voltage)
        if not stats:
            _LOGGER.warning("Historical records produced no hourly statistics buckets.")
            return

        try:
            async_add_external_statistics(self.hass, metadata, stats)
            _LOGGER.info(
                "Pushed %d hourly energy statistics (%.3f kWh total) for %s",
                len(stats),
                stats[-1].sum,
                statistic_id,
            )
        except Exception as err:
            _LOGGER.error("Failed to push historical energy statistics: %s", err)


def _build_hourly_statistics(records: list, voltage: float) -> list[StatisticData]:
    """Group records into UTC hour buckets and return cumulative StatisticData list.

    Each bucket uses the average current for that hour × voltage × 1 h to compute
    energy (kWh), then accumulates a running sum for TOTAL_INCREASING compatibility.
    """
    sorted_records = sorted(records, key=lambda r: r["timestamp"])
    if not sorted_records:
        return []

    hourly_currents: dict = defaultdict(list)
    for record in sorted_records:
        ts = dt_util.as_utc(record["timestamp"])
        hour_start = ts.replace(minute=0, second=0, microsecond=0)
        try:
            hourly_currents[hour_start].append(float(record["current"]))
        except (ValueError, TypeError):
            _LOGGER.debug("Skipping record with non-numeric current: %s", record)

    cumulative = 0.0
    stats: list[StatisticData] = []
    for hour_start in sorted(hourly_currents.keys()):
        currents = hourly_currents[hour_start]
        avg_current = sum(currents) / len(currents)
        kwh = avg_current * voltage / 1000  # avg A × V × 1 h ÷ 1000
        cumulative += kwh
        stats.append(StatisticData(start=hour_start, sum=cumulative))

    return stats
