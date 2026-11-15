"""Load real integration, coordinator and platforms with only serial I/O replaced."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.energy_owl.collector import TimestampedCollector
from custom_components.energy_owl.const import CONF_ENABLE_HISTORICAL, DOMAIN


def collector():
    """Model the pinned serial API, including its boolean connection result."""
    device = MagicMock(spec=TimestampedCollector)
    device.connect = AsyncMock(return_value=True)
    device.disconnect = AsyncMock()
    device.get_historical_data.return_value = []
    device.is_historical_data_complete.return_value = True
    device.get_live_sample.side_effect = lambda: (1.5, dt_util.utcnow())
    return device


@pytest.mark.parametrize("import_enabled", [False, True])
async def test_real_coordinator_setup_unload(hass, mock_config_entry, import_enabled):
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_config_entry, options={CONF_ENABLE_HISTORICAL: import_enabled})
    dr.async_get(hass).async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={(DOMAIN, "CM160--dev-ttyUSB0-v2")},
        sw_version="0.9.2",
    )
    serial = collector()
    with patch("custom_components.energy_owl.coordinator.get_async_datacollector", return_value=serial):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        assert mock_config_entry.state is ConfigEntryState.LOADED
        assert mock_config_entry.runtime_data.coordinator.connected
        assert (mock_config_entry.runtime_data.importer is not None) == import_enabled
        entities = er.async_entries_for_config_entry(er.async_get(hass), mock_config_entry.entry_id)
        assert len(entities) == 4
        current = next(entity for entity in entities if entity.unique_id.endswith("-current"))
        assert hass.states.get(current.entity_id).state == "1.5"
        devices = dr.async_entries_for_config_entry(dr.async_get(hass), mock_config_entry.entry_id)
        assert len(devices) == 1
        assert devices[0].sw_version is None
        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    serial.disconnect.assert_awaited_once()


async def test_real_setup_connection_refusal(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    serial = collector()
    serial.connect.return_value = False
    with patch("custom_components.energy_owl.coordinator.get_async_datacollector", return_value=serial):
        assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
    serial.disconnect.assert_awaited_once()
    assert not er.async_entries_for_config_entry(er.async_get(hass), mock_config_entry.entry_id)


async def test_config_flow_through_loader(hass, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    serial = collector()
    with patch("custom_components.energy_owl.config_flow.get_async_datacollector", return_value=serial):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"port": mock_config_entry.data["port"]})
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "already_configured"
        serial.connect.assert_not_awaited()
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        serial.connect.return_value = False
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"port": "/dev/missing"})
        assert result["errors"] == {"base": "cannot_connect"}
        serial.disconnect.assert_awaited_once()
