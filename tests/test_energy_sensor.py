"""Tests for OwlEnergySensor: accumulation, backfill logic, hourly statistics builder."""
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.energy_owl.const import DOMAIN
from custom_components.energy_owl.energy_sensor import OwlEnergySensor, _build_hourly_statistics

# ---------------------------------------------------------------------------
# _build_hourly_statistics — pure function, no hass needed
# ---------------------------------------------------------------------------

UTC = timezone.utc


def test_build_empty_input():
    assert _build_hourly_statistics([], 230.0) == []


def test_build_single_record():
    """One record in hour 10 → single bucket, sum = avg_current × voltage ÷ 1000."""
    records = [{"timestamp": datetime(2024, 1, 1, 10, 30, tzinfo=UTC), "current": 2.0}]
    stats = _build_hourly_statistics(records, 230.0)

    assert len(stats) == 1
    assert stats[0]["start"] == datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
    # 2.0 A × 230 V × 1 h ÷ 1000 = 0.46 kWh
    assert stats[0]["sum"] == pytest.approx(0.46, rel=1e-3)


def test_build_multiple_records_same_hour_averaged():
    """Multiple records in the same hour → average current, single bucket."""
    records = [
        {"timestamp": datetime(2024, 1, 1, 10, 0, tzinfo=UTC), "current": 2.0},
        {"timestamp": datetime(2024, 1, 1, 10, 15, tzinfo=UTC), "current": 4.0},
        {"timestamp": datetime(2024, 1, 1, 10, 30, tzinfo=UTC), "current": 6.0},
    ]
    stats = _build_hourly_statistics(records, 230.0)

    assert len(stats) == 1
    # avg = 4.0, 4.0 × 230 ÷ 1000 = 0.92 kWh
    assert stats[0]["sum"] == pytest.approx(0.92, rel=1e-3)


def test_build_cumulative_sum():
    """Sum must be strictly cumulative across hours (TOTAL_INCREASING semantics)."""
    records = [
        {"timestamp": datetime(2024, 1, 1, 10, 0, tzinfo=UTC), "current": 2.0},
        {"timestamp": datetime(2024, 1, 1, 11, 0, tzinfo=UTC), "current": 2.0},
        {"timestamp": datetime(2024, 1, 1, 12, 0, tzinfo=UTC), "current": 2.0},
    ]
    stats = _build_hourly_statistics(records, 230.0)

    assert len(stats) == 3
    # Each hour: 2.0 × 230 ÷ 1000 = 0.46 kWh
    assert stats[0]["sum"] == pytest.approx(0.46, rel=1e-3)
    assert stats[1]["sum"] == pytest.approx(0.92, rel=1e-3)
    assert stats[2]["sum"] == pytest.approx(1.38, rel=1e-3)
    # Monotonically increasing
    assert stats[0]["sum"] < stats[1]["sum"] < stats[2]["sum"]


def test_build_skips_invalid_current():
    """Records with non-numeric current must be silently skipped."""
    records = [
        {"timestamp": datetime(2024, 1, 1, 10, 0, tzinfo=UTC), "current": "bad"},
        {"timestamp": datetime(2024, 1, 1, 10, 15, tzinfo=UTC), "current": 2.0},
    ]
    stats = _build_hourly_statistics(records, 230.0)

    assert len(stats) == 1
    # Only the valid record counts; avg = 2.0
    assert stats[0]["sum"] == pytest.approx(0.46, rel=1e-3)


def test_build_voltage_scales_linearly():
    """Doubling the voltage must double the kWh result."""
    records = [{"timestamp": datetime(2024, 1, 1, 10, 0, tzinfo=UTC), "current": 2.0}]
    stats_230 = _build_hourly_statistics(records, 230.0)
    stats_460 = _build_hourly_statistics(records, 460.0)

    assert stats_460[0]["sum"] == pytest.approx(stats_230[0]["sum"] * 2, rel=1e-6)


def test_build_hour_start_truncated_to_minute_zero():
    """start in each StatisticData must have minute=0, second=0."""
    records = [
        {"timestamp": datetime(2024, 1, 1, 10, 47, 33, tzinfo=UTC), "current": 1.0},
    ]
    stats = _build_hourly_statistics(records, 230.0)

    assert stats[0]["start"].minute == 0
    assert stats[0]["start"].second == 0


def test_build_unsorted_input_is_ordered():
    """Records provided out of order must produce correctly ordered statistics."""
    records = [
        {"timestamp": datetime(2024, 1, 1, 12, 0, tzinfo=UTC), "current": 1.0},
        {"timestamp": datetime(2024, 1, 1, 10, 0, tzinfo=UTC), "current": 3.0},
        {"timestamp": datetime(2024, 1, 1, 11, 0, tzinfo=UTC), "current": 2.0},
    ]
    stats = _build_hourly_statistics(records, 230.0)

    assert len(stats) == 3
    assert stats[0]["start"].hour == 10
    assert stats[1]["start"].hour == 11
    assert stats[2]["start"].hour == 12


# ---------------------------------------------------------------------------
# OwlEnergySensor._handle_coordinator_update — accumulation via callback
# ---------------------------------------------------------------------------


def _make_entry_no_options():
    return MockConfigEntry(
        domain=DOMAIN,
        data={"port": "/dev/ttyUSB0"},
        options={},
        version=1,
    )


def _make_coordinator_data(current, historical_complete=False):
    return {
        "current": current,
        "connected": True,
        "last_error": None,
        "error_count": 0,
        "total_updates": 5,
        "historical_data_complete": historical_complete,
        "historical_data_count": 0,
        "new_historical_records": [],
        "debug_info": {},
    }


async def test_energy_accumulates_over_one_hour(hass, mock_coordinator, mock_config_entry):
    """2 A × 230 V over 1 hour must accumulate 0.46 kWh."""
    sensor = OwlEnergySensor(mock_coordinator, mock_config_entry)
    sensor.hass = hass

    now = dt_util.utcnow()
    sensor._last_update = now - timedelta(hours=1)
    mock_coordinator.data = _make_coordinator_data(current=2.0)

    with patch.object(sensor, "async_write_ha_state"):
        sensor._handle_coordinator_update()

    assert sensor._total_kwh == pytest.approx(0.46, rel=1e-2)


async def test_energy_accumulates_additive(hass, mock_coordinator, mock_config_entry):
    """Energy must add up across multiple update cycles."""
    sensor = OwlEnergySensor(mock_coordinator, mock_config_entry)
    sensor.hass = hass

    now = dt_util.utcnow()
    mock_coordinator.data = _make_coordinator_data(current=2.0)

    with patch.object(sensor, "async_write_ha_state"):
        # First cycle: set baseline
        sensor._last_update = now - timedelta(hours=1)
        sensor._handle_coordinator_update()
        after_first = sensor._total_kwh

        # Second cycle: another hour (pretend 1h has passed since now)
        sensor._last_update = now - timedelta(hours=1)
        sensor._handle_coordinator_update()

    # Should have doubled
    assert sensor._total_kwh == pytest.approx(after_first * 2, rel=1e-2)


async def test_energy_no_accumulation_on_first_update(hass, mock_coordinator, mock_config_entry):
    """On the very first update (_last_update is None), energy must not jump."""
    sensor = OwlEnergySensor(mock_coordinator, mock_config_entry)
    sensor.hass = hass
    assert sensor._last_update is None

    mock_coordinator.data = _make_coordinator_data(current=5.0)

    with patch.object(sensor, "async_write_ha_state"):
        sensor._handle_coordinator_update()

    assert sensor._total_kwh == pytest.approx(0.0)
    assert sensor._last_update is not None  # timestamp was recorded


async def test_energy_no_accumulation_when_current_none(hass, mock_coordinator, mock_config_entry):
    """When current is None (historical sync phase), energy total must not change."""
    sensor = OwlEnergySensor(mock_coordinator, mock_config_entry)
    sensor.hass = hass
    sensor._last_update = dt_util.utcnow() - timedelta(hours=1)
    sensor._total_kwh = 1.0

    mock_coordinator.data = _make_coordinator_data(current=None)

    with patch.object(sensor, "async_write_ha_state"):
        sensor._handle_coordinator_update()

    assert sensor._total_kwh == pytest.approx(1.0)  # unchanged


# ---------------------------------------------------------------------------
# Historical backfill trigger
# ---------------------------------------------------------------------------


async def test_backfill_triggered_once_on_historical_complete(hass, mock_coordinator, mock_config_entry):
    """_push_historical_statistics must be scheduled exactly once when historical_data_complete becomes True."""
    sensor = OwlEnergySensor(mock_coordinator, mock_config_entry)
    sensor.hass = hass

    mock_coordinator.data = _make_coordinator_data(current=None, historical_complete=True)

    with (
        patch.object(sensor, "_push_historical_statistics", new_callable=AsyncMock) as mock_push,
        patch.object(sensor, "async_write_ha_state"),
    ):
        sensor._handle_coordinator_update()
        await hass.async_block_till_done()

    mock_push.assert_awaited_once()
    assert sensor._historical_backfill_done is True


async def test_backfill_not_triggered_twice(hass, mock_coordinator, mock_config_entry):
    """Backfill must not fire again on subsequent updates after completion."""
    sensor = OwlEnergySensor(mock_coordinator, mock_config_entry)
    sensor.hass = hass
    sensor._historical_backfill_done = True  # already done

    mock_coordinator.data = _make_coordinator_data(current=None, historical_complete=True)

    with (
        patch.object(sensor, "_push_historical_statistics", new_callable=AsyncMock) as mock_push,
        patch.object(sensor, "async_write_ha_state"),
    ):
        sensor._handle_coordinator_update()
        await hass.async_block_till_done()

    mock_push.assert_not_called()


async def test_backfill_not_triggered_before_historical_complete(hass, mock_coordinator, mock_config_entry):
    """Backfill must not fire while historical sync is still in progress."""
    sensor = OwlEnergySensor(mock_coordinator, mock_config_entry)
    sensor.hass = hass

    mock_coordinator.data = _make_coordinator_data(current=None, historical_complete=False)

    with (
        patch.object(sensor, "_push_historical_statistics", new_callable=AsyncMock) as mock_push,
        patch.object(sensor, "async_write_ha_state"),
    ):
        sensor._handle_coordinator_update()
        await hass.async_block_till_done()

    mock_push.assert_not_called()
    assert sensor._historical_backfill_done is False


# ---------------------------------------------------------------------------
# _push_historical_statistics — calls recorder API
# ---------------------------------------------------------------------------


async def test_push_calls_async_add_external_statistics(hass, mock_coordinator, mock_config_entry):
    """_push_historical_statistics must call async_add_external_statistics with valid args."""
    sensor = OwlEnergySensor(mock_coordinator, mock_config_entry)
    sensor.hass = hass

    records = [
        {"timestamp": datetime(2024, 1, 1, 10, 0, tzinfo=UTC), "current": 2.0},
        {"timestamp": datetime(2024, 1, 1, 11, 0, tzinfo=UTC), "current": 3.0},
    ]
    mock_coordinator.get_historical_data = AsyncMock(return_value=records)

    with patch("custom_components.energy_owl.energy_sensor.async_add_external_statistics") as mock_recorder:
        await sensor._push_historical_statistics()

    mock_recorder.assert_called_once()
    call_args = mock_recorder.call_args
    _hass_arg, metadata, stats = call_args.args
    assert metadata["has_sum"] is True
    assert len(stats) == 2  # two hourly buckets
    # Cumulative sum increases
    assert stats[0]["sum"] < stats[1]["sum"]


async def test_push_skips_when_no_records(hass, mock_coordinator, mock_config_entry):
    """_push_historical_statistics must not call the recorder when there are no records."""
    sensor = OwlEnergySensor(mock_coordinator, mock_config_entry)
    sensor.hass = hass
    mock_coordinator.get_historical_data = AsyncMock(return_value=[])

    with patch("custom_components.energy_owl.energy_sensor.async_add_external_statistics") as mock_recorder:
        await sensor._push_historical_statistics()

    mock_recorder.assert_not_called()


async def test_push_handles_recorder_error_gracefully(hass, mock_coordinator, mock_config_entry):
    """A recorder exception must be caught; the sensor must not propagate it."""
    sensor = OwlEnergySensor(mock_coordinator, mock_config_entry)
    sensor.hass = hass
    records = [{"timestamp": datetime(2024, 1, 1, 10, 0, tzinfo=UTC), "current": 2.0}]
    mock_coordinator.get_historical_data = AsyncMock(return_value=records)

    with patch(
        "custom_components.energy_owl.energy_sensor.async_add_external_statistics",
        side_effect=RuntimeError("recorder unavailable"),
    ):
        # Must not raise
        await sensor._push_historical_statistics()
