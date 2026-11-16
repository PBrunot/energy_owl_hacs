"""Coverage for freshness, identity continuity and public diagnostics."""
from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util

from custom_components.energy_owl import EnergyOwlData
from custom_components.energy_owl.const import DOMAIN
from custom_components.energy_owl.current_sensor import OwlCMSensor
from custom_components.energy_owl.diagnostics import async_get_config_entry_diagnostics
from custom_components.energy_owl.energy_sensor import OwlEnergySensor
from custom_components.energy_owl.historical_data_sensor import OwlHistoricalDataSensor
from custom_components.energy_owl.power_sensor import OwlPowerSensor
from custom_components.energy_owl.statistics import OwlStatisticsImporter


@pytest.mark.parametrize("sensor_type", [OwlCMSensor, OwlPowerSensor, OwlEnergySensor])
async def test_measurement_freshness(hass, mock_config_entry, mock_coordinator, sensor_type):
    sensor = sensor_type(mock_coordinator, mock_config_entry)
    mock_coordinator.data["sample_timestamp"] = dt_util.utcnow()
    assert sensor.available
    mock_coordinator.last_update_success = False
    assert not sensor.available
    mock_coordinator.last_update_success = True
    mock_coordinator.data["sample_timestamp"] -= timedelta(seconds=91)
    assert not sensor.available
    mock_coordinator.data["sample_timestamp"] = dt_util.utcnow()
    mock_coordinator.data["current"] = None
    assert not sensor.available


async def test_enum_status(mock_config_entry, mock_coordinator):
    sensor = OwlHistoricalDataSensor(mock_coordinator, mock_config_entry)
    assert sensor.native_value == "complete"
    mock_coordinator.data["historical_sync_status"] = "syncing"
    assert sensor.native_value == "syncing"
    assert sensor.extra_state_attributes["records_collected"] == 100
    measurement = OwlCMSensor(mock_coordinator, mock_config_entry)
    assert "total_updates" not in measurement.extra_state_attributes


async def test_reconfigure_retains_identities(hass, mock_config_entry, mock_coordinator):
    mock_config_entry.add_to_hass(hass)
    before = OwlCMSensor(mock_coordinator, mock_config_entry).unique_id
    importer = OwlStatisticsImporter(hass, mock_config_entry, mock_coordinator)
    statistic_id = importer._metadata()["statistic_id"]
    await importer.async_close()
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "reconfigure", "entry_id": mock_config_entry.entry_id},
    )
    with patch("custom_components.energy_owl.config_flow.validate_input", return_value={"port": "/dev/ttyUSB1"}):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"port": "/dev/ttyUSB1"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data["port"] == "/dev/ttyUSB1"
    assert OwlCMSensor(mock_coordinator, mock_config_entry).unique_id == before
    mock_coordinator.port = "/dev/ttyUSB1"
    importer = OwlStatisticsImporter(hass, mock_config_entry, mock_coordinator)
    assert importer._metadata()["statistic_id"] == statistic_id
    await importer.async_close()


async def test_diagnostics(hass, mock_config_entry, mock_coordinator):
    mock_config_entry.runtime_data = EnergyOwlData(mock_coordinator)
    mock_coordinator.diagnostics_snapshot.return_value = {"connected": True}
    data = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    assert data["coordinator"] == {"connected": True}
    assert data["dependencies"]["owlsensor"]
    assert data["import"] == {"enabled": False}


async def test_poll_serializes_reset(hass):
    import asyncio
    from unittest.mock import MagicMock

    from custom_components.energy_owl.coordinator import OwlDataUpdateCoordinator
    coordinator = OwlDataUpdateCoordinator(hass, "/dev/test")
    coordinator._collector = MagicMock()
    coordinator._collector.get_debug_info.return_value = {}
    coordinator._connected = True
    coordinator._historical_data_complete = True
    coordinator._all_pushers_complete = True
    entered = asyncio.Event()
    release = asyncio.Event()

    async def sample():
        entered.set()
        await release.wait()
        return 1.0, dt_util.utcnow()

    with patch.object(coordinator, "_read_live_sample_unlocked", side_effect=sample):
        poll = asyncio.create_task(coordinator._async_update_data())
        await entered.wait()
        reset = asyncio.create_task(coordinator.async_reset_historical_data())
        await asyncio.sleep(0)
        assert not reset.done()
        assert coordinator.historical_sync_generation == 0
        release.set()
        await poll
        await reset
    assert coordinator.historical_sync_generation == 1
    assert coordinator.data is None
    assert not coordinator.historical_data_complete


async def test_reconfigure_duplicate_never_connects(hass, mock_config_entry):
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    mock_config_entry.add_to_hass(hass)
    other = MockConfigEntry(domain=DOMAIN, data={"port": "/dev/occupied"}, unique_id="/dev/occupied")
    other.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "reconfigure", "entry_id": mock_config_entry.entry_id},
    )
    with patch("custom_components.energy_owl.config_flow.validate_input") as validate:
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"port": "/dev/occupied"})
    assert result["reason"] == "already_configured"
    validate.assert_not_called()


async def test_reconfigure_failure_keeps_port(hass, mock_config_entry):
    from custom_components.energy_owl.config_flow import CannotConnect
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "reconfigure", "entry_id": mock_config_entry.entry_id},
    )
    with patch("custom_components.energy_owl.config_flow.validate_input", side_effect=CannotConnect):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"port": "/dev/bad"})
    assert result["errors"] == {"base": "cannot_connect"}
    assert mock_config_entry.data["port"] == "/dev/ttyUSB0"
