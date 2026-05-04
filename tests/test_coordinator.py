"""Tests for OwlDataUpdateCoordinator — bug-fix regression suite."""
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.energy_owl.coordinator import OwlDataUpdateCoordinator

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_collector(records=None, complete=True):
    """Return a synchronous mock collector for executor-job calls."""
    c = MagicMock()
    c.get_historical_data = MagicMock(return_value=records or [])
    c.is_historical_data_complete = MagicMock(return_value=complete)
    c.clear_historical_data = MagicMock()
    c.get_current = MagicMock(return_value=None)
    return c


def _prep_coordinator(hass, *, collector, historical_complete=False, last_check=0):
    """Create a coordinator with pre-set internals to skip real connection logic."""
    coordinator = OwlDataUpdateCoordinator(hass, "/dev/ttyUSB0")
    coordinator._collector = collector
    coordinator._connected = True
    coordinator._historical_data_complete = historical_complete
    coordinator._last_historical_check = last_check
    coordinator._historical_data_count = last_check
    coordinator._total_updates = 1
    coordinator._last_new_historical_record_time = None
    return coordinator


# ---------------------------------------------------------------------------
# Regression: NameError was HISTORICAL_DATA_TIMEOUT vs self.HISTORICAL_DATA_TIMEOUT
# ---------------------------------------------------------------------------


def test_historical_data_timeout_class_constant():
    """Class constant must be 120 seconds and reachable via self."""
    assert OwlDataUpdateCoordinator.HISTORICAL_DATA_TIMEOUT == 120


async def test_timeout_path_does_not_raise_name_error(hass):
    """Triggering the 2-minute timeout must not raise NameError (regression for missing 'self.')."""
    records = [{"timestamp": datetime(2024, 1, 1, 10, 0, tzinfo=UTC), "current": 1.5}]
    collector = _make_collector(records=records, complete=False)
    coordinator = _prep_coordinator(hass, collector=collector, last_check=1)

    # Simulate that last new record arrived 200 s ago (> HISTORICAL_DATA_TIMEOUT = 120 s)
    coordinator._last_new_historical_record_time = time.monotonic() - 200
    coordinator._historical_data_count = 1

    # Must complete without NameError
    await coordinator._process_and_consume_historical_data()

    assert coordinator._historical_data_complete is True


# ---------------------------------------------------------------------------
# Regression: deadlock when no pushers registered
# ---------------------------------------------------------------------------


async def test_no_pusher_acknowledges_device_immediately(hass):
    """With no registered pushers and historical complete, device must be acknowledged at once."""
    records = [{"timestamp": datetime(2024, 1, 1, 10, 0, tzinfo=UTC), "current": 1.5}]
    collector = _make_collector(records=records, complete=True)
    coordinator = _prep_coordinator(hass, collector=collector)

    assert coordinator._historical_data_pushers == []

    await coordinator._process_and_consume_historical_data()

    assert coordinator._historical_data_complete is True
    collector.clear_historical_data.assert_called_once()


async def test_pusher_registered_delays_acknowledgement(hass):
    """With a pusher registered, device acknowledgement must NOT be called immediately."""
    records = [{"timestamp": datetime(2024, 1, 1, 10, 0, tzinfo=UTC), "current": 1.5}]
    collector = _make_collector(records=records, complete=True)
    coordinator = _prep_coordinator(hass, collector=collector)

    # Register a fake pusher
    fake_pusher = MagicMock()
    fake_pusher.is_processing_complete = MagicMock(return_value=False)
    coordinator.register_historical_pusher(fake_pusher)

    await coordinator._process_and_consume_historical_data()

    assert coordinator._historical_data_complete is True
    # clear_historical_data was NOT called because pusher hasn't finished
    collector.clear_historical_data.assert_not_called()


async def test_all_pushers_complete_calls_acknowledge(hass):
    """notify_pusher_complete must call acknowledge when all pushers report done."""
    collector = _make_collector(complete=True)
    coordinator = _prep_coordinator(hass, collector=collector)

    fake_pusher = MagicMock()
    fake_pusher.is_processing_complete = MagicMock(return_value=True)
    coordinator.register_historical_pusher(fake_pusher)
    coordinator._historical_data_complete = True
    coordinator._all_pushers_complete = False

    await coordinator.notify_pusher_complete(fake_pusher)

    collector.clear_historical_data.assert_called_once()
    assert coordinator._all_pushers_complete is True


# ---------------------------------------------------------------------------
# _emit_historical_records is removed — bus must NOT be flooded
# ---------------------------------------------------------------------------


async def test_historical_records_do_not_fire_ha_bus_events(hass):
    """After the refactor, no per-record bus events must be fired during historical sync."""
    fired_events: list = []
    hass.bus.async_listen("energy_owl_historical_data", lambda e: fired_events.append(e))

    records = [
        {"timestamp": datetime(2024, 1, 1, 10, 0, tzinfo=UTC), "current": 1.0},
        {"timestamp": datetime(2024, 1, 1, 10, 15, tzinfo=UTC), "current": 2.0},
    ]
    collector = _make_collector(records=records, complete=False)
    coordinator = _prep_coordinator(hass, collector=collector)

    await coordinator._process_and_consume_historical_data()
    await hass.async_block_till_done()

    assert len(fired_events) == 0, "No per-record bus events should be fired"


# ---------------------------------------------------------------------------
# register / unregister pusher and listener
# ---------------------------------------------------------------------------


def test_register_unregister_pusher(hass):
    coordinator = OwlDataUpdateCoordinator(hass, "/dev/ttyUSB0")
    pusher = MagicMock()

    coordinator.register_historical_pusher(pusher)
    assert pusher in coordinator._historical_data_pushers

    # Registering twice must not duplicate
    coordinator.register_historical_pusher(pusher)
    assert coordinator._historical_data_pushers.count(pusher) == 1

    coordinator.unregister_historical_pusher(pusher)
    assert pusher not in coordinator._historical_data_pushers


def test_register_unregister_realtime_listener(hass):
    coordinator = OwlDataUpdateCoordinator(hass, "/dev/ttyUSB0")
    listener = MagicMock()

    coordinator.register_realtime_listener(listener)
    assert listener in coordinator._realtime_listeners

    coordinator.register_realtime_listener(listener)
    assert coordinator._realtime_listeners.count(listener) == 1

    coordinator.unregister_realtime_listener(listener)
    assert listener not in coordinator._realtime_listeners


# ---------------------------------------------------------------------------
# async_reset_historical_data
# ---------------------------------------------------------------------------


async def test_reset_historical_data_clears_state(hass):
    collector = _make_collector()
    coordinator = _prep_coordinator(hass, collector=collector, historical_complete=True, last_check=10)
    coordinator._historical_data_count = 10

    await coordinator.async_reset_historical_data()

    assert coordinator._historical_data_complete is False
    assert coordinator._historical_data_count == 0
    assert coordinator._last_historical_check == 0
    collector.clear_historical_data.assert_called_once()
