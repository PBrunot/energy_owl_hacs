"""Cumulative energy sensor for Energy OWL CM160 — required for Energy Dashboard."""

import logging
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import callback

from .base_entity import OwlEntity
from .coordinator import OwlDataUpdateCoordinator
from .energy import LiveEnergyIntegrator, positive_number

_LOGGER = logging.getLogger(__name__)


class OwlEnergySensor(OwlEntity, RestoreSensor):
    """Cumulative energy in kWh — compatible with Energy Dashboard.

    Real-time energy is integrated from successive current readings.
    Historical statistics are handled separately by the entry-owned importer.
    """

    _attr_translation_key = "energy"
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 3

    def __init__(
        self, coordinator: OwlDataUpdateCoordinator, config_entry: ConfigEntry
    ) -> None:
        """Initialize the energy sensor."""
        super().__init__(coordinator, config_entry)
        self._attr_unique_id = f"{self._device_unique_id}-energy"
        self._total_kwh: float = 0.0
        self._integrator = LiveEnergyIntegrator()
        self._generation = None

    async def async_added_to_hass(self) -> None:
        """Restore last known energy total on startup."""
        await super().async_added_to_hass()
        last_sensor_data = await self.async_get_last_sensor_data()
        if last_sensor_data is not None:
            try:
                self._total_kwh = positive_number(
                    last_sensor_data.native_value, allow_zero=True
                )
                self._integrator.reset()
                _LOGGER.debug("Restored energy total: %.4f kWh", self._total_kwh)
            except (ValueError, TypeError):
                _LOGGER.warning(
                    "Could not restore energy total from last state; starting from 0"
                )

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self.coordinator.connected

    @property
    def native_value(self) -> float:
        """Return cumulative energy in kWh."""
        return round(self._total_kwh, 4)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the voltage used for live energy estimation."""
        attrs = super().extra_state_attributes
        attrs["voltage_used_v"] = self._get_voltage()
        return attrs

    @callback
    def _handle_coordinator_update(self) -> None:
        """Integrate live energy; historical import is owned by the config entry."""
        generation = self.coordinator.historical_sync_generation
        if generation != self._generation:
            self._integrator.reset()
            self._generation = generation
        data = self.coordinator.data or {}
        interval = self._integrator.sample(
            data.get("current"),
            self._get_voltage(),
            data.get("sample_timestamp"),
            valid=self.coordinator.last_update_success and data.get("connected", False),
        )
        if interval:
            self._total_kwh += interval.kwh
        super()._handle_coordinator_update()
