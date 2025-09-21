"""Interfaces with the OWL sensors."""

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import COORDINATOR, DOMAIN
from .coordinator import OwlDataUpdateCoordinator
from .current_sensor import OwlCMSensor
from .historical_current_sensor import OwlHistoricalCurrentSensor
from .historical_data_pusher import OwlHistoricalDataPusher
from .historical_data_sensor import OwlHistoricalDataSensor

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Sensors."""
    coordinator: OwlDataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id][COORDINATOR]

    # Create historical current sensor first so pusher can reference it
    historical_current_sensor = OwlHistoricalCurrentSensor(coordinator, config_entry)

    sensors = [
        OwlCMSensor(coordinator, config_entry),
        OwlHistoricalDataSensor(coordinator, config_entry),
        historical_current_sensor,
        OwlHistoricalDataPusher(coordinator, config_entry, historical_current_sensor),
    ]

    async_add_entities(sensors)
