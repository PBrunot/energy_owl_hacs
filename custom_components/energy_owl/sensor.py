"""Interfaces with the OWL sensors."""

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import EnergyOwlConfigEntry
from .current_sensor import OwlCMSensor
from .ha_historical_sensor import OwlHAHistoricalSensor
from .historical_data_sensor import OwlHistoricalDataSensor

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: EnergyOwlConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Sensors."""
    coordinator = config_entry.runtime_data.coordinator

    async_add_entities([
        OwlCMSensor(coordinator, config_entry),
        OwlHistoricalDataSensor(coordinator, config_entry),
        OwlHAHistoricalSensor(coordinator, config_entry),
    ])
