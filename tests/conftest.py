"""Pytest configuration and fixtures for energy_owl tests."""
from unittest.mock import AsyncMock, MagicMock

# ---------------------------------------------------------------------------
# Mock collector fixture; the real owlsensor package is installed for API coverage.
# ---------------------------------------------------------------------------

_mock_collector = MagicMock()
_mock_collector.connect = AsyncMock()
_mock_collector.disconnect = AsyncMock()
_mock_collector.get_current = MagicMock(return_value=1.5)
_mock_collector.get_historical_data = MagicMock(return_value=[])
_mock_collector.is_historical_data_complete = MagicMock(return_value=True)
_mock_collector.clear_historical_data = MagicMock()

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

import pytest
from homeassistant.const import CONF_PORT
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.energy_owl.const import CONF_NOT_FIRST_RUN, DOMAIN


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations for every test in this suite."""
    yield


@pytest.fixture
def mock_config_entry():
    """Config entry for a device that has already completed its first run."""
    return MockConfigEntry(
        domain=DOMAIN,
        data={CONF_PORT: "/dev/ttyUSB0", CONF_NOT_FIRST_RUN: True},
        entry_id="test_entry_id",
        unique_id="/dev/ttyUSB0",
        version=1,
    )


@pytest.fixture
def coordinator_data():
    """Realistic coordinator data dict."""
    return {
        "current": 1.5,
        "connected": True,
        "last_error": None,
        "error_count": 0,
        "total_updates": 5,
        "historical_data_complete": True,
        "historical_data_count": 100,
        "new_historical_records": [],
        "debug_info": {},
    }


@pytest.fixture
def mock_coordinator(coordinator_data):
    """A pre-configured mock coordinator."""
    coordinator = MagicMock()
    coordinator.async_config_entry_first_refresh = AsyncMock()
    coordinator.async_disconnect = AsyncMock()
    coordinator.data = coordinator_data
    coordinator.last_update_success = True
    coordinator.connected = True
    coordinator.historical_data_complete = True
    coordinator.historical_data_count = 100
    coordinator._collector = _mock_collector
    coordinator._historical_data_complete = True
    coordinator._historical_data_count = 100
    coordinator._last_historical_check = 0
    coordinator.register_historical_pusher = MagicMock()
    coordinator.register_realtime_listener = MagicMock()
    coordinator.unregister_historical_pusher = MagicMock()
    coordinator.unregister_realtime_listener = MagicMock()
    coordinator.port = "/dev/ttyUSB0"
    coordinator.historical_sync_acknowledged = False
    coordinator.historical_sync_generation = 0
    coordinator.get_historical_data = AsyncMock(return_value=[])
    coordinator.notify_pusher_complete = AsyncMock()
    return coordinator
