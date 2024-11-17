"""Interfaces with the OWL sensors."""

import logging
import random

from owlsensor import CMDataCollector

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfElectricCurrent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, OWL_OBJECT

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Sensors."""
    # This gets the data update coordinator from hass.data as specified in your __init__.py
    collector: CMDataCollector = hass.data[DOMAIN][config_entry.entry_id][OWL_OBJECT]

    if collector is None:
        _LOGGER.error("Missing coordinator")

    sensors = [OwmCMSensor(collector)]

    # Create the sensors.
    async_add_entities(sensors)

    await collector.connect()


class OwmCMSensor(SensorEntity):
    """Representation of a Sensor."""

    _attr_name = "CM160 - Current"
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, collector: CMDataCollector):
        self.collector = collector
        self._attr_device_info = DeviceInfo(
            manufacturer="Energy OWL", model="CM160", name="CM160"
        )

    def update(self) -> None:
        """Fetch new state data for the sensor.

        This is the only method that should fetch new data for Home Assistant.
        """
        if self.collector is not None:
            _LOGGER.info("Update called on %s", self)
            if self.collector.serialdevice == "test":
                self._attr_native_value = random.randint(0, 100) / 10.0
            else:
                self._attr_native_value = self.collector.get_current()
