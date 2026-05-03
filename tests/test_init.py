"""Tests for energy_owl __init__.py: setup, unload, services."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_PORT
from homeassistant.exceptions import ConfigEntryNotReady
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.energy_owl.const import CONF_NOT_FIRST_RUN, DOMAIN


async def test_setup_entry_sets_runtime_data(hass, mock_config_entry, mock_coordinator):
    """async_setup_entry must store coordinator in entry.runtime_data."""
    mock_config_entry.add_to_hass(hass)

    with patch("custom_components.energy_owl.OwlDataUpdateCoordinator", return_value=mock_coordinator):
        result = await hass.config_entries.async_setup(mock_config_entry.entry_id)

    assert result is True
    assert mock_config_entry.runtime_data is not None
    assert mock_config_entry.runtime_data.coordinator is mock_coordinator


async def test_setup_entry_calls_first_refresh(hass, mock_config_entry, mock_coordinator):
    """async_config_entry_first_refresh must be awaited during setup."""
    mock_config_entry.add_to_hass(hass)

    with patch("custom_components.energy_owl.OwlDataUpdateCoordinator", return_value=mock_coordinator):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)

    mock_coordinator.async_config_entry_first_refresh.assert_awaited_once()


async def test_setup_entry_raises_config_entry_not_ready(hass, mock_config_entry, mock_coordinator):
    """A coordinator failure during first refresh must raise ConfigEntryNotReady."""
    mock_coordinator.async_config_entry_first_refresh.side_effect = Exception("serial error")
    mock_config_entry.add_to_hass(hass)

    with patch("custom_components.energy_owl.OwlDataUpdateCoordinator", return_value=mock_coordinator):
        result = await hass.config_entries.async_setup(mock_config_entry.entry_id)

    assert result is False
    assert mock_config_entry.state.value == "setup_error"


async def test_setup_entry_first_run_updates_config(hass, mock_coordinator):
    """On first run (CONF_NOT_FIRST_RUN absent), the config entry must be updated."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_PORT: "/dev/ttyUSB0"},  # no CONF_NOT_FIRST_RUN
        entry_id="first_run_entry",
        unique_id="/dev/ttyUSB0",
        version=1,
    )
    entry.add_to_hass(hass)

    with patch("custom_components.energy_owl.OwlDataUpdateCoordinator", return_value=mock_coordinator):
        await hass.config_entries.async_setup(entry.entry_id)

    assert entry.data.get(CONF_NOT_FIRST_RUN) is True


async def test_setup_entry_registers_services(hass, mock_config_entry, mock_coordinator):
    """All four services must be registered after setup."""
    mock_config_entry.add_to_hass(hass)

    with patch("custom_components.energy_owl.OwlDataUpdateCoordinator", return_value=mock_coordinator):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)

    for service in ("get_historical_data", "clear_historical_data", "export_historical_data_csv", "force_reconnect"):
        assert hass.services.has_service(DOMAIN, service), f"Service {service} not registered"


async def test_unload_entry_disconnects_coordinator(hass, mock_config_entry, mock_coordinator):
    """async_unload_entry must call coordinator.async_disconnect."""
    mock_config_entry.add_to_hass(hass)

    with patch("custom_components.energy_owl.OwlDataUpdateCoordinator", return_value=mock_coordinator):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        result = await hass.config_entries.async_unload(mock_config_entry.entry_id)

    assert result is True
    mock_coordinator.async_disconnect.assert_awaited_once()


async def test_unload_entry_does_not_leave_hass_data(hass, mock_config_entry, mock_coordinator):
    """After unload, hass.data must not contain stale coordinator references."""
    mock_config_entry.add_to_hass(hass)

    with patch("custom_components.energy_owl.OwlDataUpdateCoordinator", return_value=mock_coordinator):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.config_entries.async_unload(mock_config_entry.entry_id)

    assert DOMAIN not in hass.data or mock_config_entry.entry_id not in hass.data.get(DOMAIN, {})
