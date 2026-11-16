"""User-visible recovery is independent of routine historical import batches."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.util import dt as dt_util

from custom_components.energy_owl.collector import get_async_datacollector
from custom_components.energy_owl.coordinator import OwlDataUpdateCoordinator
from custom_components.energy_owl.historical_data_sensor import OwlHistoricalDataSensor
from custom_components.energy_owl.statistics import OwlStatisticsImporter


@pytest.fixture
async def recovery(hass, mock_config_entry, freezer):
    freezer.move_to("2026-11-16T19:29:47+00:00")
    collector = get_async_datacollector("/dev/not-opened", "CM160", 5)
    collector.connected = True
    coordinator = OwlDataUpdateCoordinator(hass, "/dev/not-opened")
    coordinator._collector = collector
    coordinator._connected = True
    coordinator._total_updates = 1
    coordinator._auto_recovery_enabled = False
    importer = OwlStatisticsImporter(hass, mock_config_entry, coordinator)
    importer._store.async_load = AsyncMock(return_value=None)
    importer._store.async_save = AsyncMock()
    clock = SimpleNamespace(elapsed=0)
    notifications, events = [], []

    async def notification(call):
        notifications.append(dict(call.data))

    hass.services.async_register("persistent_notification", "create", notification)
    hass.bus.async_listen("energy_owl_historical_data_complete", events.append)

    async def poll():
        coordinator.async_set_updated_data(await coordinator._async_update_data())
        await importer._import(coordinator.historical_sync_generation)
        await hass.async_block_till_done()

    with (
        patch("custom_components.energy_owl.coordinator.time", SimpleNamespace(monotonic=lambda: clock.elapsed)),
        patch.object(dt_util, "DEFAULT_TIME_ZONE", ZoneInfo("Europe/Rome")),
        patch("custom_components.energy_owl.statistics.async_add_external_statistics") as submit,
    ):
        yield SimpleNamespace(
            collector=collector, coordinator=coordinator, importer=importer,
            clock=clock, poll=poll, notifications=notifications, events=events,
            submit=submit, freezer=freezer,
            sensor=OwlHistoricalDataSensor(coordinator, mock_config_entry),
        )
    await importer.async_close()


def older_minutes(count, *, offset=0):
    start = datetime(2026, 11, 16, 10, tzinfo=UTC)
    return [{"timestamp": start + timedelta(minutes=n), "current": 2}
            for n in range(offset, offset + count)]


async def test_log_open_minute_is_retained_and_routine_batches_are_silent(recovery, caplog):
    """Replay the 20:29 batch: the open 20:29 minute must not be rejected/lost."""
    r = recovery
    # Actual packets from the v0.9.4 hardware capture (20:27, 20:28, 20:29).
    for packet in ("591a0b10141be2041e00c1", "591a0b10141ce2042000c4", "591a0b10141de2041f00c4"):
        await r.collector.parse_packet(bytes.fromhex(packet))

    async def save_with_concurrent_export(data):
        # An action reading the entire buffer cannot enlarge the imported prefix.
        await r.coordinator.get_historical_data(strict=True)

    r.importer._store.async_save.side_effect = save_with_concurrent_export
    await r.poll()
    r.clock.elapsed = 120
    await r.poll()
    assert len(r.importer._ledger.minutes) == 2
    assert [record["timestamp"].minute for record in r.collector.get_historical_data()] == [29]
    assert "Skipped" not in caplog.text

    # No subsequent packet is needed to retry the retained open minute.
    r.freezer.move_to("2026-11-16T19:30:17+00:00")
    r.clock.elapsed = 150
    await r.poll()
    assert r.sensor.native_value == "complete"
    r.clock.elapsed = 270
    await r.poll()
    assert len(r.importer._ledger.minutes) == 3
    assert r.collector.get_historical_data() == []
    r.clock.elapsed = 450
    await r.poll()
    assert r.sensor.native_value == "complete"
    assert r.notifications == []
    assert r.events == []


async def test_backfill_notifies_once_across_batches_and_ignores_replays(recovery):
    r = recovery
    r.collector._historical_data.extend(older_minutes(40))
    await r.poll()
    r.clock.elapsed = 120
    await r.poll()
    assert r.coordinator.diagnostics_snapshot()["recovered_minutes"] == 40
    assert not r.notifications

    r.clock.elapsed = 150
    r.collector._historical_data.extend(older_minutes(40, offset=30))
    await r.poll()
    r.clock.elapsed = 270
    await r.poll()
    assert r.coordinator.diagnostics_snapshot()["recovered_minutes"] == 70
    r.clock.elapsed = 300
    await r.poll()
    assert r.sensor.native_value == "syncing"
    assert not r.notifications  # wait until the recovery settles

    r.clock.elapsed = 400
    await r.poll()
    assert r.sensor.native_value == "complete"
    assert len(r.notifications) == len(r.events) == 1
    assert "70 previously missing" in r.notifications[0]["message"]

    # Large replay of already-persisted history is not another recovery.
    r.collector._historical_data.extend(older_minutes(70) * 2)
    r.clock.elapsed = 430
    await r.poll()
    r.clock.elapsed = 550
    await r.poll()
    r.clock.elapsed = 700
    await r.poll()
    assert r.sensor.native_value == "complete"
    assert len(r.notifications) == len(r.events) == 1


@pytest.mark.parametrize("count", [0, 59, 60])
async def test_recovery_threshold_and_storage_failure(recovery, count):
    r = recovery
    r.collector._historical_data.extend(older_minutes(count) * 2)
    await r.poll()
    r.importer._store.async_save.side_effect = OSError("disk full")
    r.clock.elapsed = 150
    await r.poll()
    assert not r.notifications
    assert r.coordinator.diagnostics_snapshot()["recovered_minutes"] == 0
    assert len(r.collector.get_historical_data()) == count * 2

    r.importer._store.async_save.side_effect = None
    r.clock.elapsed = 180
    await r.poll()
    assert r.collector.get_historical_data() == []
    r.clock.elapsed = 310
    await r.poll()
    assert r.sensor.native_value == "complete"
    assert len(r.notifications) == len(r.events) == (1 if count >= 60 else 0)


async def test_small_separate_backfills_do_not_accumulate_into_notification(recovery):
    r = recovery
    for offset, elapsed in ((0, 0), (40, 500)):
        r.collector._historical_data.extend(older_minutes(40, offset=offset))
        r.clock.elapsed = elapsed
        await r.poll()
        r.clock.elapsed += 120
        await r.poll()
        r.clock.elapsed += 150
        await r.poll()
    assert r.sensor.native_value == "complete"
    assert not r.notifications
    assert not r.events


async def test_open_minute_preserves_older_records_after_it(recovery):
    """An interleaved old record after the open minute survives prefix cleanup."""
    r = recovery
    open_record = {"timestamp": datetime(2026, 11, 16, 19, 29, tzinfo=UTC), "current": 2}
    r.collector._historical_data.extend([open_record, *older_minutes(1)])
    await r.poll()
    r.clock.elapsed = 120
    await r.poll()
    assert len(r.collector.get_historical_data()) == 2
    assert r.importer._ledger.minutes == {}
    r.freezer.move_to("2026-11-16T19:30:17+00:00")
    r.clock.elapsed = 150
    await r.poll()
    r.clock.elapsed = 270
    await r.poll()
    assert r.collector.get_historical_data() == []
    assert len(r.importer._ledger.minutes) == 2
    assert not r.notifications
