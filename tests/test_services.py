"""Regression coverage for action targets, errors and integration loading."""
from unittest.mock import AsyncMock, patch

import pytest
import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.setup import async_setup_component

from custom_components.energy_owl import EnergyOwlData, async_setup
from custom_components.energy_owl.const import DOMAIN


async def target(hass, entry, coordinator):
    entry.add_to_hass(hass)
    entry.runtime_data = EnergyOwlData(coordinator=coordinator)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, "test")},
    )
    await async_setup(hass, {})
    return device.id


async def test_actions_exist_without_entries(hass):
    assert await async_setup_component(hass, DOMAIN, {})
    assert hass.services.supports_response(DOMAIN, "get_historical_data") is SupportsResponse.OPTIONAL
    assert hass.services.has_service(DOMAIN, "force_reconnect")


@pytest.mark.parametrize("data", [{}, {"device_id": []}, {"device_id": ["one", "two"]}, {"device_id": "missing"}])
async def test_invalid_targets(hass, data):
    await async_setup(hass, {})
    with pytest.raises((ServiceValidationError, vol.Invalid)):
        await hass.services.async_call(DOMAIN, "force_reconnect", data, blocking=True)


async def test_unloaded_target(hass, mock_config_entry, mock_coordinator):
    device_id = await target(hass, mock_config_entry, mock_coordinator)
    mock_config_entry.mock_state(hass, ConfigEntryState.NOT_LOADED)
    with pytest.raises(ServiceValidationError) as error:
        await hass.services.async_call(DOMAIN, "force_reconnect", {"device_id": device_id}, blocking=True)
    assert error.value.translation_key == "entry_not_loaded"


async def test_foreign_target(hass, mock_config_entry):
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    entry = MockConfigEntry(domain="other")
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(config_entry_id=entry.entry_id, identifiers={("other", "test")})
    await async_setup(hass, {})
    with pytest.raises(ServiceValidationError) as error:
        await hass.services.async_call(DOMAIN, "force_reconnect", {"device_id": device.id}, blocking=True)
    assert error.value.translation_key == "invalid_target"


async def test_history_response(hass, mock_config_entry, mock_coordinator):
    device_id = await target(hass, mock_config_entry, mock_coordinator)
    result = await hass.services.async_call(
        DOMAIN, "get_historical_data", {"device_id": device_id}, blocking=True, return_response=True,
    )
    assert result["records"] == []
    mock_coordinator.get_historical_data.assert_awaited_once_with(strict=True)


async def test_force_reconnect_targets_loaded_device(hass, mock_config_entry, mock_coordinator, caplog):
    device_id = await target(hass, mock_config_entry, mock_coordinator)
    mock_coordinator.async_reconnect = AsyncMock()
    await hass.services.async_call(DOMAIN, "force_reconnect", {"device_id": device_id}, blocking=True)
    mock_coordinator.async_reconnect.assert_awaited_once_with()
    assert "DeviceEntry.config_entries" not in caplog.text


async def test_csv_write_error(hass, mock_config_entry, mock_coordinator):
    from homeassistant.util import dt as dt_util
    device_id = await target(hass, mock_config_entry, mock_coordinator)
    mock_coordinator.get_historical_data.return_value = [{"timestamp": dt_util.utcnow(), "current": 1}]
    with patch("custom_components.energy_owl.services.open", side_effect=OSError("disk full")):
        with pytest.raises(HomeAssistantError) as error:
            await hass.services.async_call(DOMAIN, "export_historical_data_csv", {"device_id": device_id}, blocking=True)
    assert error.value.translation_key == "export_failed"


async def test_empty_csv_is_error(hass, mock_config_entry, mock_coordinator):
    device_id = await target(hass, mock_config_entry, mock_coordinator)
    with pytest.raises(ServiceValidationError) as error:
        await hass.services.async_call(DOMAIN, "export_historical_data_csv", {"device_id": device_id}, blocking=True)
    assert error.value.translation_key == "no_history"


@pytest.mark.parametrize("failure", [RuntimeError("serial failure"), UpdateFailed("read failed")])
async def test_device_failure_is_error(hass, mock_config_entry, mock_coordinator, failure):
    device_id = await target(hass, mock_config_entry, mock_coordinator)
    mock_coordinator.async_reconnect = AsyncMock(side_effect=failure)
    with pytest.raises(HomeAssistantError) as error:
        await hass.services.async_call(DOMAIN, "force_reconnect", {"device_id": device_id}, blocking=True)
    assert error.value.translation_key == "action_failed"


async def test_loader_setup_unload(hass, mock_config_entry, mock_coordinator):
    mock_config_entry.add_to_hass(hass)
    with patch("custom_components.energy_owl.OwlDataUpdateCoordinator", return_value=mock_coordinator):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        assert mock_config_entry.state is ConfigEntryState.LOADED
        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    mock_coordinator.async_disconnect.assert_awaited_once()
    assert hass.services.has_service(DOMAIN, "get_historical_data")
