"""Tests for energy_owl __init__.py: setup, unload, services."""
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import CONF_PORT
from homeassistant.exceptions import ConfigEntryNotReady
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.energy_owl import EnergyOwlData, async_setup, async_setup_entry, async_unload_entry
from custom_components.energy_owl.const import CONF_NOT_FIRST_RUN, DOMAIN

# Unit tests isolate serial acquisition; loader coverage lives in test_services.py.


async def _setup(hass, entry, mock_coordinator):
    """Helper: call async_setup_entry with platform forwarding mocked."""
    entry.add_to_hass(hass)
    await async_setup(hass, {})
    with (
        patch("custom_components.energy_owl.OwlDataUpdateCoordinator", return_value=mock_coordinator),
        patch.object(hass.config_entries, "async_forward_entry_setups", new=AsyncMock()),
    ):
        return await async_setup_entry(hass, entry)


async def test_setup_entry_sets_runtime_data(hass, mock_config_entry, mock_coordinator):
    """async_setup_entry must store coordinator in entry.runtime_data."""
    result = await _setup(hass, mock_config_entry, mock_coordinator)

    assert result is True
    assert mock_config_entry.runtime_data is not None
    assert mock_config_entry.runtime_data.coordinator is mock_coordinator


async def test_setup_entry_calls_first_refresh(hass, mock_config_entry, mock_coordinator):
    """async_config_entry_first_refresh must be awaited exactly once."""
    await _setup(hass, mock_config_entry, mock_coordinator)

    mock_coordinator.async_config_entry_first_refresh.assert_awaited_once()


async def test_setup_entry_raises_config_entry_not_ready(hass, mock_config_entry, mock_coordinator):
    """A coordinator failure during first refresh must propagate as ConfigEntryNotReady."""
    mock_coordinator.async_config_entry_first_refresh.side_effect = Exception("serial error")

    with pytest.raises(ConfigEntryNotReady):
        await _setup(hass, mock_config_entry, mock_coordinator)


async def test_setup_entry_first_run_updates_config(hass, mock_coordinator):
    """On first run (CONF_NOT_FIRST_RUN absent) the config entry must be updated."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_PORT: "/dev/ttyUSB0"},  # no CONF_NOT_FIRST_RUN
        entry_id="first_run_entry",
        unique_id="/dev/ttyUSB0",
        version=1,
    )

    await _setup(hass, entry, mock_coordinator)

    assert entry.data.get(CONF_NOT_FIRST_RUN) is True


async def test_setup_entry_registers_all_services(hass, mock_config_entry, mock_coordinator):
    """All four custom services must be registered after setup."""
    await _setup(hass, mock_config_entry, mock_coordinator)

    for service in (
        "get_historical_data",
        "clear_historical_data",
        "export_historical_data_csv",
        "force_reconnect",
    ):
        assert hass.services.has_service(DOMAIN, service), f"Service '{service}' not registered"


async def test_services_not_registered_twice(hass, mock_config_entry, mock_coordinator):
    """Calling setup twice must not raise (services are idempotent)."""
    await _setup(hass, mock_config_entry, mock_coordinator)
    # second setup on the same hass should not raise
    with (
        patch("custom_components.energy_owl.OwlDataUpdateCoordinator", return_value=mock_coordinator),
        patch.object(hass.config_entries, "async_forward_entry_setups", new=AsyncMock()),
    ):
        await async_setup_entry(hass, mock_config_entry)

    assert hass.services.has_service(DOMAIN, "get_historical_data")


async def test_unload_entry_disconnects_coordinator(hass, mock_config_entry, mock_coordinator):
    """async_unload_entry must call coordinator.async_disconnect."""
    mock_config_entry.add_to_hass(hass)
    mock_config_entry.runtime_data = EnergyOwlData(coordinator=mock_coordinator)

    with patch.object(hass.config_entries, "async_unload_platforms", new=AsyncMock(return_value=True)):
        result = await async_unload_entry(hass, mock_config_entry)

    assert result is True
    mock_coordinator.async_disconnect.assert_awaited_once()


async def test_unload_entry_skips_disconnect_on_platform_failure(hass, mock_config_entry, mock_coordinator):
    """If platform unload fails, coordinator.async_disconnect must NOT be called."""
    mock_config_entry.add_to_hass(hass)
    mock_config_entry.runtime_data = EnergyOwlData(coordinator=mock_coordinator)

    with patch.object(hass.config_entries, "async_unload_platforms", new=AsyncMock(return_value=False)):
        result = await async_unload_entry(hass, mock_config_entry)

    assert result is False
    mock_coordinator.async_disconnect.assert_not_awaited()


async def test_unload_entry_keeps_services_for_last_entry(hass, mock_config_entry, mock_coordinator):
    """Actions remain available when the last entry is unloaded."""
    await _setup(hass, mock_config_entry, mock_coordinator)

    for svc in ("get_historical_data", "clear_historical_data", "export_historical_data_csv", "force_reconnect"):
        assert hass.services.has_service(DOMAIN, svc), f"Service {svc!r} not registered after setup"

    with patch.object(hass.config_entries, "async_unload_platforms", new=AsyncMock(return_value=True)):
        result = await async_unload_entry(hass, mock_config_entry)

    assert result is True
    for svc in ("get_historical_data", "clear_historical_data", "export_historical_data_csv", "force_reconnect"):
        assert hass.services.has_service(DOMAIN, svc)


async def test_unload_entry_keeps_services_when_other_entries_exist(hass, mock_coordinator):
    """Services must NOT be deregistered when at least one other entry remains loaded."""
    from custom_components.energy_owl.const import CONF_NOT_FIRST_RUN

    entry_a = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_PORT: "/dev/ttyUSB0", CONF_NOT_FIRST_RUN: True},
        entry_id="entry_a",
        unique_id="/dev/ttyUSB0",
        version=1,
    )
    entry_b = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_PORT: "/dev/ttyUSB1", CONF_NOT_FIRST_RUN: True},
        entry_id="entry_b",
        unique_id="/dev/ttyUSB1",
        version=1,
    )

    # Set up both entries
    await _setup(hass, entry_a, mock_coordinator)
    with (
        patch("custom_components.energy_owl.OwlDataUpdateCoordinator", return_value=mock_coordinator),
        patch.object(hass.config_entries, "async_forward_entry_setups", new=AsyncMock()),
    ):
        entry_b.add_to_hass(hass)
        await async_setup_entry(hass, entry_b)

    assert hass.services.has_service(DOMAIN, "get_historical_data")

    # Unload only entry_a; entry_b still active
    with patch.object(hass.config_entries, "async_unload_platforms", new=AsyncMock(return_value=True)):
        await async_unload_entry(hass, entry_a)

    # Services must still be registered
    assert hass.services.has_service(DOMAIN, "get_historical_data"), "Service removed too early"


async def test_importer_registered_before_first_refresh(hass, mock_config_entry, mock_coordinator):
    async def first_refresh():
        mock_coordinator.register_historical_pusher.assert_called_once()

    mock_coordinator.async_config_entry_first_refresh.side_effect = first_refresh
    await _setup(hass, mock_config_entry, mock_coordinator)
    assert mock_config_entry.runtime_data.importer is not None
    await mock_config_entry.runtime_data.importer.async_close()


async def test_import_disabled_has_no_importer(hass, mock_config_entry, mock_coordinator):
    from custom_components.energy_owl.const import CONF_ENABLE_HISTORICAL
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_config_entry, options={CONF_ENABLE_HISTORICAL: False})
    with (
        patch("custom_components.energy_owl.OwlDataUpdateCoordinator", return_value=mock_coordinator),
        patch.object(hass.config_entries, "async_forward_entry_setups", new=AsyncMock()),
    ):
        await async_setup_entry(hass, mock_config_entry)
    assert mock_config_entry.runtime_data.importer is None
    mock_coordinator.register_historical_pusher.assert_not_called()


async def test_platform_setup_failure_cleans_importer(hass, mock_config_entry, mock_coordinator):
    mock_config_entry.add_to_hass(hass)
    with (
        patch("custom_components.energy_owl.OwlDataUpdateCoordinator", return_value=mock_coordinator),
        patch.object(hass.config_entries, "async_forward_entry_setups", side_effect=RuntimeError("platform failed")),
    ):
        with pytest.raises(RuntimeError, match="platform failed"):
            await async_setup_entry(hass, mock_config_entry)
    mock_coordinator.unregister_historical_pusher.assert_called_once()
    mock_coordinator.async_disconnect.assert_awaited_once()


async def test_unload_closes_importer_before_disconnect(hass, mock_config_entry, mock_coordinator):
    mock_config_entry.add_to_hass(hass)
    importer = AsyncMock()
    mock_config_entry.runtime_data = EnergyOwlData(coordinator=mock_coordinator, importer=importer)

    async def disconnect():
        importer.async_close.assert_awaited_once()

    mock_coordinator.async_disconnect.side_effect = disconnect
    with patch.object(hass.config_entries, "async_unload_platforms", return_value=True):
        assert await async_unload_entry(hass, mock_config_entry)


async def test_cancelled_setup_closes_connection(hass, mock_config_entry, mock_coordinator):
    import asyncio
    mock_coordinator.async_config_entry_first_refresh.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await _setup(hass, mock_config_entry, mock_coordinator)
    mock_coordinator.async_disconnect.assert_awaited_once()
    mock_coordinator.unregister_historical_pusher.assert_called_once()


async def test_platform_rollback_failure_still_disconnects(hass, mock_config_entry, mock_coordinator):
    mock_config_entry.add_to_hass(hass)
    with (
        patch("custom_components.energy_owl.OwlDataUpdateCoordinator", return_value=mock_coordinator),
        patch.object(hass.config_entries, "async_forward_entry_setups", side_effect=RuntimeError("setup failed")),
        patch.object(hass.config_entries, "async_unload_platforms", side_effect=RuntimeError("rollback failed")),
    ):
        with pytest.raises(RuntimeError):
            await async_setup_entry(hass, mock_config_entry)
    mock_coordinator.async_disconnect.assert_awaited_once()
    mock_coordinator.unregister_historical_pusher.assert_called_once()
