"""Regression tests for the statistics-only historical import path."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.components.recorder.statistics import valid_statistic_id

from custom_components.energy_owl.statistics import OwlStatisticsImporter


def make_importer(hass, entry, coordinator):
    coordinator.historical_sync_generation = 1
    coordinator.historical_data_complete = True
    coordinator.get_historical_data = AsyncMock(
        return_value=[
            {"timestamp": datetime(2024, 1, 1, 10, tzinfo=UTC), "current": 2.0}
        ]
    )
    return OwlStatisticsImporter(hass, entry, coordinator)


@pytest.mark.parametrize(
    "port", ["/dev/ttyUSB0", "COM3", "/dev/serial/by-id/usb-OWL_CM160"]
)
async def test_valid_external_statistics_and_acknowledgement(
    hass, mock_config_entry, mock_coordinator, port
):
    mock_coordinator.port = port
    importer = make_importer(hass, mock_config_entry, mock_coordinator)
    with patch(
        "custom_components.energy_owl.statistics.async_add_external_statistics"
    ) as submit:
        await importer._import(1)
    metadata, statistics = submit.call_args.args[1:]
    assert valid_statistic_id(metadata["statistic_id"])
    assert metadata["source"] == "energy_owl"
    assert metadata["unit_class"] == "energy"
    assert statistics[0]["sum"] == pytest.approx(0.46 / 60)
    mock_coordinator.get_historical_data.assert_awaited_once_with(strict=True)
    mock_coordinator.notify_pusher_complete.assert_awaited_once_with(importer)
    assert importer.is_processing_complete()
    await importer.async_close()


async def test_submission_failure_retries_without_acknowledging(
    hass, mock_config_entry, mock_coordinator
):
    importer = make_importer(hass, mock_config_entry, mock_coordinator)
    with patch(
        "custom_components.energy_owl.statistics.async_add_external_statistics",
        side_effect=ValueError("rejected"),
    ):
        await importer._import(1)
    assert not importer.is_processing_complete()
    mock_coordinator.notify_pusher_complete.assert_not_awaited()
    with patch(
        "custom_components.energy_owl.statistics.async_add_external_statistics"
    ) as submit:
        await importer._import(1)
    submit.assert_called_once()
    assert importer.is_processing_complete()
    await importer.async_close()


async def test_read_failure_is_not_empty_history(
    hass, mock_config_entry, mock_coordinator
):
    importer = make_importer(hass, mock_config_entry, mock_coordinator)
    mock_coordinator.get_historical_data.side_effect = RuntimeError("disconnected")
    await importer._import(1)
    assert not importer.is_processing_complete()
    mock_coordinator.notify_pusher_complete.assert_not_awaited()
    await importer.async_close()


async def test_empty_history_releases_device_without_statistics(
    hass, mock_config_entry, mock_coordinator
):
    importer = make_importer(hass, mock_config_entry, mock_coordinator)
    mock_coordinator.get_historical_data.return_value = []
    with patch(
        "custom_components.energy_owl.statistics.async_add_external_statistics"
    ) as submit:
        await importer._import(1)
    submit.assert_not_called()
    mock_coordinator.notify_pusher_complete.assert_awaited_once_with(importer)
    await importer.async_close()


async def test_generation_change_discards_obsolete_snapshot(
    hass, mock_config_entry, mock_coordinator
):
    importer = make_importer(hass, mock_config_entry, mock_coordinator)
    mock_coordinator.historical_sync_generation = 2
    with patch(
        "custom_components.energy_owl.statistics.async_add_external_statistics"
    ) as submit:
        await importer._import(1)
    submit.assert_not_called()
    assert not importer.is_processing_complete()
    mock_coordinator.notify_pusher_complete.assert_not_awaited()
    await importer.async_close()


async def test_close_cancels_import_and_unsubscribes(
    hass, mock_config_entry, mock_coordinator
):
    importer = make_importer(hass, mock_config_entry, mock_coordinator)
    started = asyncio.Event()

    async def wait_for_history(**kwargs):
        started.set()
        await asyncio.Event().wait()

    mock_coordinator.get_historical_data.side_effect = wait_for_history
    importer.start()
    importer._handle_update()  # must not schedule a second concurrent import
    await started.wait()
    await importer.async_close()
    assert importer._task.cancelled()
    mock_coordinator.get_historical_data.assert_awaited_once()
    mock_coordinator.async_add_listener.return_value.assert_called_once()
    mock_coordinator.unregister_historical_pusher.assert_called_once_with(importer)
    mock_coordinator.notify_pusher_complete.assert_not_awaited()


async def test_acknowledgement_retry_does_not_resubmit(
    hass, mock_config_entry, mock_coordinator
):
    importer = make_importer(hass, mock_config_entry, mock_coordinator)
    mock_coordinator.notify_pusher_complete.side_effect = [
        RuntimeError("serial error"),
        None,
    ]
    with patch(
        "custom_components.energy_owl.statistics.async_add_external_statistics"
    ) as submit:
        await importer._import(1)
        await importer._import(1)
    submit.assert_called_once()
    assert mock_coordinator.notify_pusher_complete.await_count == 2
    await importer.async_close()


@pytest.mark.parametrize("current", [float("nan"), float("inf"), -1])
async def test_invalid_history_not_submitted_or_acknowledged(
    hass, mock_config_entry, mock_coordinator, current
):
    importer = make_importer(hass, mock_config_entry, mock_coordinator)
    mock_coordinator.get_historical_data.return_value[0]["current"] = current
    with patch(
        "custom_components.energy_owl.statistics.async_add_external_statistics"
    ) as submit:
        await importer._import(1)
    submit.assert_not_called()
    mock_coordinator.notify_pusher_complete.assert_not_awaited()
    await importer.async_close()


async def test_real_recorder_import_preserves_unrelated_states(
    hass, mock_config_entry, mock_coordinator, tmp_path
):
    """Import through the real Recorder queue while a separate sensor records."""
    from functools import partial

    from homeassistant.components.recorder.history import get_last_state_changes
    from homeassistant.components.recorder.statistics import statistics_during_period
    from homeassistant.helpers.recorder import async_initialize_recorder
    from homeassistant.setup import async_setup_component
    from pytest_homeassistant_custom_component.components.recorder.common import (
        async_recorder_block_till_done,
        async_trigger_db_commit,
    )

    async_initialize_recorder(hass)
    assert await async_setup_component(
        hass,
        "recorder",
        {
            "recorder": {
                "db_url": f"sqlite:///{tmp_path / 'recorder.db'}",
                "auto_purge": False,
            }
        },
    )
    await hass.async_block_till_done()
    await hass.async_start()
    importer = make_importer(hass, mock_config_entry, mock_coordinator)
    hass.states.async_set("sensor.unrelated", "1")
    await importer._import(1)  # no statistics API mock: validates and queues the import
    hass.states.async_set("sensor.unrelated", "2")
    await hass.async_block_till_done()
    # Drain the events first: the commit helper can skip scheduling when the
    # Recorder thread has not yet marked its session as needing a commit.
    await async_recorder_block_till_done(hass)
    async_trigger_db_commit(hass)
    await async_recorder_block_till_done(hass)
    states = await hass.async_add_executor_job(
        get_last_state_changes, hass, 1, "sensor.unrelated"
    )
    assert states["sensor.unrelated"][0].state == "2"
    statistics = await hass.async_add_executor_job(
        partial(
            statistics_during_period,
            hass,
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 2, tzinfo=UTC),
            {"energy_owl:cm160_dev_ttyusb0_v2_energy"},
            "hour",
            None,
            {"sum"},
        )
    )
    assert statistics["energy_owl:cm160_dev_ttyusb0_v2_energy"][0][
        "sum"
    ] == pytest.approx(0.46 / 60)
    mock_coordinator.notify_pusher_complete.assert_awaited_once()
    await importer.async_close()


async def test_snapshot_is_durable_before_ack_and_replayed_without_device(
    hass, mock_config_entry, mock_coordinator
):
    """A queued-but-uncommitted import is recoverable after the device is cleared."""
    from copy import deepcopy

    importer = make_importer(hass, mock_config_entry, mock_coordinator)
    saved = None

    async def save(data):
        nonlocal saved
        saved = deepcopy(data)

    importer._store.async_save = AsyncMock(side_effect=save)
    importer._store.async_load = AsyncMock(return_value=None)

    async def acknowledge(pusher):
        assert saved is not None
        assert saved["archive"] or saved["minutes"]

    mock_coordinator.notify_pusher_complete.side_effect = acknowledge
    with patch(
        "custom_components.energy_owl.statistics.async_add_external_statistics",
        side_effect=RuntimeError("recorder offline"),
    ):
        await importer._import(1)
    mock_coordinator.notify_pusher_complete.assert_not_awaited()
    assert saved is not None
    await importer.async_close()

    recovered = make_importer(hass, mock_config_entry, mock_coordinator)
    recovered._store.async_load = AsyncMock(return_value=saved)
    mock_coordinator.get_historical_data.side_effect = RuntimeError(
        "device unavailable"
    )
    with patch(
        "custom_components.energy_owl.statistics.async_add_external_statistics"
    ) as submit:
        await recovered._import(1)
    submit.assert_called_once()
    assert submit.call_args.args[2][-1]["sum"] == pytest.approx(0.46 / 60)
    await recovered.async_close()


async def test_storage_failure_prevents_submission_and_ack(
    hass, mock_config_entry, mock_coordinator
):
    importer = make_importer(hass, mock_config_entry, mock_coordinator)
    importer._store.async_save = AsyncMock(side_effect=OSError("disk full"))
    with patch(
        "custom_components.energy_owl.statistics.async_add_external_statistics"
    ) as submit:
        await importer._import(1)
    submit.assert_not_called()
    mock_coordinator.notify_pusher_complete.assert_not_awaited()
    assert not importer.is_processing_complete()
    await importer.async_close()


def test_history_replaces_overlapping_live_estimate_without_double_counting():
    from datetime import timedelta

    from custom_components.energy_owl.energy import EnergyInterval
    from custom_components.energy_owl.statistics import EnergyLedger

    ledger = EnergyLedger()
    t = datetime(2026, 11, 1, 10, tzinfo=UTC)
    live = EnergyInterval(t, t + timedelta(minutes=1), 1000)
    history = EnergyInterval(t, t + timedelta(minutes=1), 500)
    ledger.add(live)
    ledger.add(live)  # repeated live delivery cannot double count
    assert ledger.statistics()[-1]["sum"] == pytest.approx(1 / 60)
    ledger.add(history, historical=True)
    ledger.add(live)
    ledger.add(history, historical=True)
    assert ledger.statistics()[-1]["sum"] == pytest.approx(0.5 / 60)


def test_restart_and_overlapping_download_preserve_cumulative_baseline():
    from copy import deepcopy
    from datetime import timedelta

    from custom_components.energy_owl.energy import EnergyInterval
    from custom_components.energy_owl.statistics import EnergyLedger

    t = datetime(2026, 11, 1, 10, tzinfo=UTC)
    first = EnergyInterval(t, t + timedelta(minutes=1), 600)
    second = EnergyInterval(
        t + timedelta(hours=1), t + timedelta(hours=1, minutes=1), 1200
    )
    ledger = EnergyLedger()
    ledger.add(first, historical=True)
    restored = EnergyLedger(deepcopy(ledger.data))
    restored.add(first, historical=True)
    restored.add(second, historical=True)
    assert [s["sum"] for s in restored.statistics()] == pytest.approx([0.01, 0.03])
    restored.compact(t + timedelta(days=40))
    archived = EnergyLedger(deepcopy(restored.data))
    archived.add(first, historical=True)
    assert archived.statistics() == restored.statistics()
    assert archived.minutes == {}


async def test_combined_source_continues_with_live_after_history(
    hass, mock_config_entry, mock_coordinator
):
    from datetime import timedelta

    from homeassistant.util import dt as dt_util

    importer = make_importer(hass, mock_config_entry, mock_coordinator)
    t = dt_util.utcnow().replace(second=0, microsecond=0) - timedelta(minutes=3)
    mock_coordinator.get_historical_data.return_value = [{"timestamp": t, "current": 2}]
    with patch(
        "custom_components.energy_owl.statistics.async_add_external_statistics"
    ) as submit:
        await importer._import(1)
        mock_coordinator.historical_sync_acknowledged = True
        data = mock_coordinator.data
        t += timedelta(minutes=2)
        for offset in (0, 30):
            if offset:
                # Late history reopens a batch without breaking live integration.
                mock_coordinator.historical_batch_revision += 1
                mock_coordinator.historical_data_complete = False
            data.update(
                current=2,
                sample_timestamp=t + timedelta(seconds=offset),
                connected=True,
            )
            with patch.object(
                dt_util, "utcnow", return_value=t + timedelta(seconds=offset)
            ):
                await importer._import(1)
    assert submit.call_args.args[2][-1]["sum"] == pytest.approx(0.46 * 90 / 3600)
    assert {call.args[1]["statistic_id"] for call in submit.call_args_list} == {
        "energy_owl:cm160_dev_ttyusb0_v2_energy"
    }
    await importer.async_close()
