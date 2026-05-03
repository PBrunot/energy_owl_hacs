"""Tests for sensor entity naming, unique IDs, and properties."""
from unittest.mock import patch

import pytest
from homeassistant.const import EntityCategory

from custom_components.energy_owl.current_sensor import OwlCMSensor
from custom_components.energy_owl.ha_historical_sensor import OwlHAHistoricalSensor
from custom_components.energy_owl.historical_data_sensor import OwlHistoricalDataSensor


# ---------------------------------------------------------------------------
# Entity naming (HA 2024/2025 requirement: has_entity_name + translation_key)
# ---------------------------------------------------------------------------

def test_current_sensor_has_entity_name():
    assert OwlCMSensor._attr_has_entity_name is True


def test_historical_status_sensor_has_entity_name():
    assert OwlHistoricalDataSensor._attr_has_entity_name is True


def test_historical_processor_sensor_has_entity_name():
    assert OwlHAHistoricalSensor._attr_has_entity_name is True


def test_current_sensor_translation_key():
    assert OwlCMSensor._attr_translation_key == "current"


def test_historical_status_sensor_translation_key():
    assert OwlHistoricalDataSensor._attr_translation_key == "historical_data_status"


def test_historical_processor_sensor_translation_key():
    assert OwlHAHistoricalSensor._attr_translation_key == "historical_data_processor"


# ---------------------------------------------------------------------------
# No _attr_name (deprecated in HA 2024/2025)
# ---------------------------------------------------------------------------

def test_current_sensor_no_attr_name():
    assert not hasattr(OwlCMSensor, "_attr_name") or OwlCMSensor._attr_name is None


def test_historical_status_no_attr_name():
    assert not hasattr(OwlHistoricalDataSensor, "_attr_name") or OwlHistoricalDataSensor._attr_name is None


def test_historical_processor_no_attr_name():
    assert not hasattr(OwlHAHistoricalSensor, "_attr_name") or OwlHAHistoricalSensor._attr_name is None


# ---------------------------------------------------------------------------
# Entity categories (diagnostic entities must be marked)
# ---------------------------------------------------------------------------

def test_historical_status_is_diagnostic():
    assert OwlHistoricalDataSensor._attr_entity_category == EntityCategory.DIAGNOSTIC


def test_historical_processor_is_diagnostic():
    assert OwlHAHistoricalSensor._attr_entity_category == EntityCategory.DIAGNOSTIC


def test_current_sensor_no_entity_category():
    assert getattr(OwlCMSensor, "_attr_entity_category", None) is None


# ---------------------------------------------------------------------------
# Unique IDs (via instance, using mock fixtures)
# ---------------------------------------------------------------------------

async def test_sensor_unique_ids(hass, mock_config_entry, mock_coordinator):
    """All three sensors must have distinct unique IDs."""
    mock_config_entry.add_to_hass(hass)

    with patch("custom_components.energy_owl.OwlDataUpdateCoordinator", return_value=mock_coordinator):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    entity_registry = hass.data.get("entity_registry") or __import__(
        "homeassistant.helpers.entity_registry", fromlist=["async_get"]
    ).async_get(hass)

    from homeassistant.helpers.entity_registry import async_get
    er = async_get(hass)
    entries = [e for e in er.entities.values() if e.config_entry_id == mock_config_entry.entry_id]

    unique_ids = [e.unique_id for e in entries]
    assert len(unique_ids) == len(set(unique_ids)), "Duplicate unique IDs found"
    assert any("current" in uid for uid in unique_ids)
    assert any("historical-status" in uid for uid in unique_ids)
    assert any("historical-processor" in uid for uid in unique_ids)


# ---------------------------------------------------------------------------
# native_value logic
# ---------------------------------------------------------------------------

async def test_current_sensor_native_value(hass, mock_config_entry, mock_coordinator):
    """Current sensor must return the 'current' value from coordinator data."""
    mock_config_entry.add_to_hass(hass)

    with patch("custom_components.energy_owl.OwlDataUpdateCoordinator", return_value=mock_coordinator):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    state = hass.states.get("sensor.energy_owl_cm160_dev_ttyusb0_current")
    assert state is not None
    assert float(state.state) == pytest.approx(1.5)


async def test_current_sensor_none_when_no_data(hass, mock_config_entry, mock_coordinator):
    """Current sensor must return None when coordinator has no data."""
    mock_coordinator.data = None
    mock_config_entry.add_to_hass(hass)

    with patch("custom_components.energy_owl.OwlDataUpdateCoordinator", return_value=mock_coordinator):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    state = hass.states.get("sensor.energy_owl_cm160_dev_ttyusb0_current")
    assert state is None or state.state in ("unknown", "unavailable")
