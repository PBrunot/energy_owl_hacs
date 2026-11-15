"""Tests for sensor entity naming, unique IDs, and properties."""
import pytest
from homeassistant.const import EntityCategory

from custom_components.energy_owl import EnergyOwlData
from custom_components.energy_owl.const import (
    CONF_VOLTAGE,
    CONF_VOLTAGE_ENTITY,
    DEFAULT_VOLTAGE,
    DOMAIN,
)
from custom_components.energy_owl.current_sensor import OwlCMSensor
from custom_components.energy_owl.energy_sensor import OwlEnergySensor
from custom_components.energy_owl.historical_data_sensor import OwlHistoricalDataSensor
from custom_components.energy_owl.power_sensor import OwlPowerSensor
from pytest_homeassistant_custom_component.common import MockConfigEntry

# ---------------------------------------------------------------------------
# Class-level attribute tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sensor_class, translation_key", [
    (OwlCMSensor, "current"),
    (OwlPowerSensor, "power"),
    (OwlEnergySensor, "energy"),
    (OwlHistoricalDataSensor, "historical_data_status"),
])
def test_entity_naming(mock_coordinator, mock_config_entry, sensor_class, translation_key):
    entity = sensor_class(mock_coordinator, mock_config_entry)
    assert entity.has_entity_name is True
    assert entity.translation_key == translation_key


def test_diagnostic_defaults(mock_coordinator, mock_config_entry):
    entity = OwlHistoricalDataSensor(mock_coordinator, mock_config_entry)
    assert entity.entity_category == EntityCategory.DIAGNOSTIC
    assert entity.entity_registry_enabled_default is False


# ---------------------------------------------------------------------------
# Platform entity count tests
# ---------------------------------------------------------------------------


async def test_sensor_platform_creates_four_entities(hass, mock_config_entry, mock_coordinator):
    """With historical import enabled (default), four entities must be created."""
    from custom_components.energy_owl.sensor import async_setup_entry as sensor_setup

    mock_config_entry.add_to_hass(hass)
    mock_config_entry.runtime_data = EnergyOwlData(coordinator=mock_coordinator)

    entities: list = []
    await sensor_setup(hass, mock_config_entry, entities.extend)

    assert len(entities) == 4
    types = {type(e).__name__ for e in entities}
    assert types == {"OwlCMSensor", "OwlPowerSensor", "OwlEnergySensor", "OwlHistoricalDataSensor"}


async def test_sensor_platform_creates_four_entities_when_historical_disabled(hass, mock_coordinator):
    """With historical import disabled, four entities must be created (no OwlHAHistoricalSensor)."""
    from custom_components.energy_owl.sensor import async_setup_entry as sensor_setup
    from custom_components.energy_owl.const import CONF_ENABLE_HISTORICAL

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"port": "/dev/ttyUSB0"},
        options={CONF_ENABLE_HISTORICAL: False},
        entry_id="no_hist_entry",
        unique_id="/dev/ttyUSB0",
        version=1,
    )
    entry.add_to_hass(hass)
    entry.runtime_data = EnergyOwlData(coordinator=mock_coordinator)

    entities: list = []
    await sensor_setup(hass, entry, entities.extend)

    assert len(entities) == 4
    types = {type(e).__name__ for e in entities}
    assert "OwlHAHistoricalSensor" not in types
    assert {"OwlCMSensor", "OwlPowerSensor", "OwlEnergySensor", "OwlHistoricalDataSensor"} == types


async def test_sensor_unique_ids_are_distinct(hass, mock_config_entry, mock_coordinator):
    """All four sensors must have distinct unique_ids."""
    from custom_components.energy_owl.sensor import async_setup_entry as sensor_setup

    mock_config_entry.add_to_hass(hass)
    mock_config_entry.runtime_data = EnergyOwlData(coordinator=mock_coordinator)

    entities: list = []
    await sensor_setup(hass, mock_config_entry, entities.extend)

    unique_ids = [e.unique_id for e in entities]
    assert len(unique_ids) == len(set(unique_ids)), f"Duplicate unique_ids: {unique_ids}"

    assert any("current" in uid for uid in unique_ids)
    assert any("power" in uid for uid in unique_ids)
    assert any("energy" in uid for uid in unique_ids)
    assert any("historical-status" in uid for uid in unique_ids)


# ---------------------------------------------------------------------------
# OwlCMSensor — value tests
# ---------------------------------------------------------------------------


def test_current_sensor_native_value(mock_coordinator, mock_config_entry):
    sensor = OwlCMSensor(mock_coordinator, mock_config_entry)
    assert sensor.native_value == pytest.approx(1.5)


def test_current_sensor_native_value_none_when_no_data(mock_coordinator, mock_config_entry):
    mock_coordinator.data = None
    sensor = OwlCMSensor(mock_coordinator, mock_config_entry)
    assert sensor.native_value is None


def test_current_sensor_native_value_none_when_key_missing(mock_coordinator, mock_config_entry):
    mock_coordinator.data = {"connected": True}
    sensor = OwlCMSensor(mock_coordinator, mock_config_entry)
    assert sensor.native_value is None


# ---------------------------------------------------------------------------
# OwlPowerSensor — value and voltage tests
# ---------------------------------------------------------------------------


def test_power_sensor_native_value_uses_default_voltage(mock_coordinator, mock_config_entry):
    """Power = current × DEFAULT_VOLTAGE when no option is configured."""
    sensor = OwlPowerSensor(mock_coordinator, mock_config_entry)
    # mock_coordinator.data["current"] == 1.5 A, voltage = 230 V
    expected = round(1.5 * DEFAULT_VOLTAGE, 1)
    assert sensor.native_value == pytest.approx(expected)


def test_power_sensor_native_value_none_when_no_data(mock_coordinator, mock_config_entry):
    mock_coordinator.data = None
    assert OwlPowerSensor(mock_coordinator, mock_config_entry).native_value is None


def test_power_sensor_native_value_none_when_current_missing(mock_coordinator, mock_config_entry):
    mock_coordinator.data = {"connected": True}
    assert OwlPowerSensor(mock_coordinator, mock_config_entry).native_value is None


def test_power_sensor_uses_configured_voltage(mock_coordinator):
    """When CONF_VOLTAGE is set in options, that voltage must be used."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"port": "/dev/ttyUSB0"},
        options={CONF_VOLTAGE: 120.0},
        version=1,
    )
    sensor = OwlPowerSensor(mock_coordinator, entry)
    expected = round(1.5 * 120.0, 1)
    assert sensor.native_value == pytest.approx(expected)


async def test_power_sensor_uses_voltage_entity_state(hass, mock_coordinator):
    """When CONF_VOLTAGE_ENTITY points to a valid state, that value overrides the default."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"port": "/dev/ttyUSB0"},
        options={CONF_VOLTAGE_ENTITY: "sensor.grid_voltage", CONF_VOLTAGE: 230.0},
        version=1,
    )
    sensor = OwlPowerSensor(mock_coordinator, entry)
    sensor.hass = hass  # inject hass (not yet added to the platform)

    # Before the entity exists in states, falls back to configured default
    assert sensor._get_voltage() == pytest.approx(230.0)

    # Set state in HA
    hass.states.async_set("sensor.grid_voltage", "240.5")
    assert sensor._get_voltage() == pytest.approx(240.5)
    expected = round(1.5 * 240.5, 1)
    assert sensor.native_value == pytest.approx(expected)


async def test_power_sensor_falls_back_when_entity_unavailable(hass, mock_coordinator):
    """Unavailable/unknown voltage entity must fall back to the configured default."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"port": "/dev/ttyUSB0"},
        options={CONF_VOLTAGE_ENTITY: "sensor.grid_voltage", CONF_VOLTAGE: 230.0},
        version=1,
    )
    sensor = OwlPowerSensor(mock_coordinator, entry)
    sensor.hass = hass

    for bad_state in ("unavailable", "unknown"):
        hass.states.async_set("sensor.grid_voltage", bad_state)
        assert sensor._get_voltage() == pytest.approx(230.0), f"Should fall back for state={bad_state!r}"


def test_power_sensor_extra_attrs_contains_voltage_used(mock_coordinator, mock_config_entry):
    """Power sensor must expose voltage_used_v in extra_state_attributes."""
    sensor = OwlPowerSensor(mock_coordinator, mock_config_entry)
    attrs = sensor.extra_state_attributes
    assert "voltage_used_v" in attrs
    assert attrs["voltage_used_v"] == pytest.approx(DEFAULT_VOLTAGE)


# ---------------------------------------------------------------------------
# OwlEnergySensor — basic value tests (accumulation logic in test_energy_sensor.py)
# ---------------------------------------------------------------------------


def test_energy_sensor_native_value_starts_at_zero(mock_coordinator, mock_config_entry):
    sensor = OwlEnergySensor(mock_coordinator, mock_config_entry)
    assert sensor.native_value == pytest.approx(0.0)


def test_energy_sensor_reflects_accumulated_total(mock_coordinator, mock_config_entry):
    sensor = OwlEnergySensor(mock_coordinator, mock_config_entry)
    sensor._total_kwh = 3.7
    assert sensor.native_value == pytest.approx(3.7)


def test_energy_sensor_extra_attrs_contains_voltage(mock_coordinator, mock_config_entry):
    sensor = OwlEnergySensor(mock_coordinator, mock_config_entry)
    attrs = sensor.extra_state_attributes
    assert "voltage_used_v" in attrs
