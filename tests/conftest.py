"""Pytest configuration and fixtures for energy_owl tests."""
import sys
from unittest.mock import AsyncMock, MagicMock

# ---------------------------------------------------------------------------
# Mock external libraries BEFORE any component module is imported.
# ---------------------------------------------------------------------------

_mock_serial = MagicMock()
_mock_serial.SerialException = Exception
sys.modules.setdefault("serial", _mock_serial)

_mock_collector = MagicMock()
_mock_collector.connect = AsyncMock()
_mock_collector.disconnect = AsyncMock()
_mock_collector.get_current = MagicMock(return_value=1.5)
_mock_collector.get_historical_data = MagicMock(return_value=[])
_mock_collector.is_historical_data_complete = MagicMock(return_value=True)
_mock_collector.clear_historical_data = MagicMock()

_mock_owlsensor = MagicMock()
_mock_owlsensor.CMDataCollector = MagicMock
_mock_owlsensor.get_async_datacollector = MagicMock(return_value=_mock_collector)
sys.modules.setdefault("owlsensor", _mock_owlsensor)


class _MockHistoricalSensor:
    _attr_historical_states = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def async_write_ha_historical_states(self):
        pass

    async def async_update_historical(self):
        pass


class _MockPollUpdateMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class _MockHistoricalState:
    def __init__(self, state, dt):
        self.state = state
        self.dt = dt


_mock_ha_hist = MagicMock()
_mock_ha_hist.HistoricalSensor = _MockHistoricalSensor
_mock_ha_hist.PollUpdateMixin = _MockPollUpdateMixin
_mock_ha_hist.HistoricalState = _MockHistoricalState
sys.modules.setdefault("homeassistant_historical_sensor", _mock_ha_hist)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

import pytest
from homeassistant.const import CONF_PORT
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.energy_owl.const import CONF_NOT_FIRST_RUN, DOMAIN


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
    coordinator.get_historical_data = AsyncMock(return_value=[])
    coordinator.notify_pusher_complete = AsyncMock()
    return coordinator
