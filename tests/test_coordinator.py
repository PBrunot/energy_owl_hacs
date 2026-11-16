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


async def test_no_pusher_discards_local_batch_after_quiet_period(hass):
    """A quiet batch can be discarded locally when historical import is disabled."""
    records = [{"timestamp": datetime(2024, 1, 1, 10, 0, tzinfo=UTC), "current": 1.5}]
    collector = _make_collector(records=records, complete=True)
    coordinator = _prep_coordinator(hass, collector=collector)

    coordinator._last_historical_check = 1
    coordinator._last_new_historical_record_time = time.monotonic() - 121

    assert coordinator._historical_data_pushers == []

    await coordinator._process_and_consume_historical_data()

    assert coordinator._historical_data_complete is True
    collector.clear_historical_data.assert_called_once()


async def test_pusher_registered_delays_local_cleanup(hass):
    """A quiet batch must remain buffered until its importer completes."""
    records = [{"timestamp": datetime(2024, 1, 1, 10, 0, tzinfo=UTC), "current": 1.5}]
    collector = _make_collector(records=records, complete=True)
    coordinator = _prep_coordinator(hass, collector=collector)

    coordinator._last_historical_check = 1
    coordinator._last_new_historical_record_time = time.monotonic() - 121

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


async def test_failed_acknowledgement_can_be_retried(hass):
    from homeassistant.helpers.update_coordinator import UpdateFailed
    collector = _make_collector()
    collector.clear_historical_data.side_effect = [RuntimeError("serial failure"), None]
    coordinator = _prep_coordinator(hass, collector=collector, historical_complete=True)
    pusher = MagicMock()
    pusher.is_processing_complete.return_value = True
    coordinator.register_historical_pusher(pusher)
    with pytest.raises(UpdateFailed):
        await coordinator.notify_pusher_complete(pusher)
    assert not coordinator.historical_sync_acknowledged
    await coordinator.notify_pusher_complete(pusher)
    assert coordinator.historical_sync_acknowledged
    assert collector.clear_historical_data.call_count == 2


async def test_strict_historical_read_propagates_error(hass):
    from homeassistant.helpers.update_coordinator import UpdateFailed
    collector = _make_collector()
    collector.get_historical_data.side_effect = RuntimeError("serial failure")
    coordinator = _prep_coordinator(hass, collector=collector)
    with pytest.raises(UpdateFailed):
        await coordinator.get_historical_data(strict=True)
    collector.clear_historical_data.assert_not_called()


async def test_live_fallback_preserves_history_for_importer(hass):
    collector = _make_collector(complete=False)
    collector.get_current.return_value = 1.5
    coordinator = _prep_coordinator(hass, collector=collector)
    pusher = MagicMock()
    pusher.is_processing_complete.return_value = False
    coordinator.register_historical_pusher(pusher)
    result = await coordinator._async_update_data()
    assert result["current"] == 1.5
    assert not result["historical_data_complete"]
    collector.clear_historical_data.assert_not_called()


async def test_reset_invalidates_snapshot_before_clear_completes(hass):
    collector = _make_collector()
    coordinator = _prep_coordinator(hass, collector=collector, historical_complete=True)
    generation = coordinator.historical_sync_generation

    def clear():
        assert coordinator.historical_sync_generation != generation
        assert not coordinator.historical_data_complete

    collector.clear_historical_data.side_effect = clear
    await coordinator.async_reset_historical_data()
    assert not coordinator.historical_sync_acknowledged


@pytest.mark.parametrize("connected", [False, True])
async def test_connection_result_controls_status(hass, caplog, connected):
    """Only a successful library return may mark the coordinator connected."""
    from homeassistant.helpers.update_coordinator import UpdateFailed

    collector = _make_collector()
    collector.connect = AsyncMock(return_value=connected)
    coordinator = OwlDataUpdateCoordinator(hass, "/dev/test")
    with patch("custom_components.energy_owl.coordinator.get_async_datacollector", return_value=collector):
        if connected:
            await coordinator._async_connect()
            assert coordinator.connected
            assert coordinator.last_error is None
        else:
            with pytest.raises(UpdateFailed, match="Could not open serial port"):
                await coordinator._async_connect()
            assert not coordinator.connected
            assert "Could not open serial port" in coordinator.last_error
            assert "Successfully connected to OWL device" not in caplog.text


@pytest.mark.parametrize("poll_during_save", [False, True])
async def test_interleaved_real_packets_and_late_history_are_imported(
    hass, mock_config_entry, poll_during_save
):
    """Replay hardware packets, including history arriving during persistence."""
    from copy import deepcopy

    from custom_components.energy_owl.collector import get_async_datacollector
    from custom_components.energy_owl.statistics import OwlStatisticsImporter

    collector = get_async_datacollector("/dev/not-opened", "CM160", 5)
    collector.connected = True
    coordinator = _prep_coordinator(hass, collector=collector)
    importer = OwlStatisticsImporter(hass, mock_config_entry, coordinator)
    importer._store.async_load = AsyncMock(return_value=None)
    saved = []

    async def save(data):
        saved.append(deepcopy(data))
        if len(saved) == 1:
            # The snapshot is already taken; this record must survive cleanup.
            await collector.parse_packet(bytes.fromhex("591a0b0e0713e2044600d2"))
            if poll_during_save:
                coordinator.async_set_updated_data(await coordinator._async_update_data())

    importer._store.async_save = AsyncMock(side_effect=save)
    with patch("custom_components.energy_owl.statistics.async_add_external_statistics") as submit:
        await collector.parse_packet(bytes.fromhex("591a0b0e0712e2044700d2"))
        await collector.parse_packet(bytes.fromhex("511a0b0e0712e2044700ca"))
        assert collector.is_historical_data_complete()
        first = await coordinator._async_update_data()
        coordinator.async_set_updated_data(first)
        assert first["current"] == 5.0
        assert not first["historical_data_complete"]
        assert len(collector.get_historical_data()) == 1

        # Only history silence closes the batch, regardless of the sticky flag.
        coordinator._last_new_historical_record_time = time.monotonic() - 121
        coordinator.async_set_updated_data(await coordinator._async_update_data())
        await importer._import(coordinator.historical_sync_generation)
        assert importer.is_processing_complete() is (not poll_during_save)
        assert len(collector.get_historical_data()) == (2 if poll_during_save else 1)
        assert collector.get_historical_data()[-1]["timestamp"].minute == 19
        assert saved  # durable before imported prefix was discarded

        generation = coordinator.historical_sync_generation
        revision = coordinator.historical_batch_revision
        coordinator.async_set_updated_data(await coordinator._async_update_data())
        assert coordinator.historical_sync_generation == generation
        assert coordinator.historical_batch_revision == revision + (not poll_during_save)
        assert not coordinator.historical_data_complete
        assert not importer.is_processing_complete()
        coordinator._last_new_historical_record_time = time.monotonic() - 121
        coordinator.async_set_updated_data(await coordinator._async_update_data())
        await importer._import(coordinator.historical_sync_generation)
        assert collector.get_historical_data() == []
        assert importer.is_processing_complete()
        assert submit.call_args.args[2][-1]["sum"] == pytest.approx((5.0 + 4.9) * 230 / 60000)
        assert saved[-1] != saved[0]
    await importer.async_close()


async def test_history_arriving_before_quiet_period_keeps_collection_open(hass):
    collector = _make_collector(complete=True)
    coordinator = _prep_coordinator(hass, collector=collector)
    collector.get_current.return_value = 1.5
    for minute in range(3):
        collector.get_historical_data.return_value = [
            {"timestamp": datetime(2026, 11, 14, 7, n, tzinfo=UTC), "current": 2}
            for n in range(minute + 1)
        ]
        coordinator._last_new_historical_record_time = time.monotonic() - 121
        result = await coordinator._async_update_data()
        assert result["current"] == 1.5
        assert not coordinator.historical_data_complete
    collector.clear_historical_data.assert_not_called()
