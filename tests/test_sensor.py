"""Tests for sensor entity naming, unique IDs, and properties."""
import pytest
from homeassistant.const import EntityCategory

from custom_components.energy_owl import EnergyOwlData
from custom_components.energy_owl.base_entity import OwlEntity
from custom_components.energy_owl.current_sensor import OwlCMSensor
from custom_components.energy_owl.ha_historical_sensor import OwlHAHistoricalSensor
from custom_components.energy_owl.historical_data_sensor import OwlHistoricalDataSensor

# ---------------------------------------------------------------------------
# Class-level attribute tests.
#
# In HA 2024+, Entity uses descriptor machinery so accessing `Cls._attr_foo`
# can return a property object rather than the value set in a subclass.
# Use `cls.__dict__['attr']` to inspect only what *our* class defines.
# ---------------------------------------------------------------------------


def test_has_entity_name_defined_in_base():
    """OwlEntity must declare _attr_has_entity_name = True (Bronze requirement).

    HA 2024+ uses a CachedProperties metaclass that transforms _attr_foo = val
    into a property descriptor; the actual value is stored as __attr_foo.
    """
    assert OwlEntity.__dict__.get("__attr_has_entity_name") is True


def test_current_sensor_translation_key():
    assert OwlCMSensor.__dict__.get("__attr_translation_key") == "current"


def test_historical_status_translation_key():
    assert OwlHistoricalDataSensor.__dict__.get("__attr_translation_key") == "historical_data_status"


def test_historical_processor_translation_key():
    assert OwlHAHistoricalSensor.__dict__.get("__attr_translation_key") == "historical_data_processor"


def test_no_deprecated_attr_name_on_any_sensor():
    """None of our sensor classes must use the deprecated _attr_name."""
    for cls in (OwlCMSensor, OwlHistoricalDataSensor, OwlHAHistoricalSensor):
        assert "_attr_name" not in cls.__dict__, (
            f"{cls.__name__} still defines deprecated _attr_name"
        )


def test_diagnostic_entity_categories():
    assert OwlHistoricalDataSensor.__dict__.get("__attr_entity_category") == EntityCategory.DIAGNOSTIC
    assert OwlHAHistoricalSensor.__dict__.get("__attr_entity_category") == EntityCategory.DIAGNOSTIC


def test_current_sensor_has_no_entity_category():
    """Main current sensor must not carry an entity category."""
    assert "_attr_entity_category" not in OwlCMSensor.__dict__


# ---------------------------------------------------------------------------
# Instance-level / integration tests
# ---------------------------------------------------------------------------


async def test_sensor_platform_creates_three_entities(hass, mock_config_entry, mock_coordinator):
    """sensor.async_setup_entry must add exactly three entities."""
    from custom_components.energy_owl.sensor import async_setup_entry as sensor_setup

    mock_config_entry.add_to_hass(hass)
    mock_config_entry.runtime_data = EnergyOwlData(coordinator=mock_coordinator)

    entities: list = []
    await sensor_setup(hass, mock_config_entry, entities.extend)

    assert len(entities) == 3
    types = {type(e).__name__ for e in entities}
    assert types == {"OwlCMSensor", "OwlHistoricalDataSensor", "OwlHAHistoricalSensor"}


async def test_sensor_unique_ids_are_distinct(hass, mock_config_entry, mock_coordinator):
    """All three sensors must have distinct unique_ids."""
    from custom_components.energy_owl.sensor import async_setup_entry as sensor_setup

    mock_config_entry.add_to_hass(hass)
    mock_config_entry.runtime_data = EnergyOwlData(coordinator=mock_coordinator)

    entities: list = []
    await sensor_setup(hass, mock_config_entry, entities.extend)

    unique_ids = [e.unique_id for e in entities]
    assert len(unique_ids) == len(set(unique_ids)), f"Duplicate unique_ids: {unique_ids}"

    assert any("current" in uid for uid in unique_ids)
    assert any("historical-status" in uid for uid in unique_ids)
    assert any("historical-processor" in uid for uid in unique_ids)


def test_current_sensor_native_value(mock_coordinator, mock_config_entry):
    """Current sensor returns the 'current' value from coordinator data."""
    sensor = OwlCMSensor(mock_coordinator, mock_config_entry)
    assert sensor.native_value == pytest.approx(1.5)


def test_current_sensor_native_value_none_when_no_data(mock_coordinator, mock_config_entry):
    """Current sensor returns None when coordinator has no data yet."""
    mock_coordinator.data = None
    sensor = OwlCMSensor(mock_coordinator, mock_config_entry)
    assert sensor.native_value is None


def test_current_sensor_native_value_none_when_key_missing(mock_coordinator, mock_config_entry):
    """Current sensor returns None when 'current' key is absent from coordinator data."""
    mock_coordinator.data = {"connected": True}
    sensor = OwlCMSensor(mock_coordinator, mock_config_entry)
    assert sensor.native_value is None
