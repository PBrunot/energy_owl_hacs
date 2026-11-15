"""Energy accounting: observed minutes and bounded live sample intervals."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.util import dt as dt_util

from custom_components.energy_owl.energy import (
    EnergyInterval,
    LiveEnergyIntegrator,
    history_intervals,
)
from custom_components.energy_owl.energy_sensor import OwlEnergySensor
from custom_components.energy_owl.statistics import (
    EnergyLedger,
    _build_hourly_statistics,
)


def test_history_one_minute_not_one_hour():
    record = {"timestamp": datetime(2024, 1, 1, 10, 30, tzinfo=UTC), "current": 2}
    assert _build_hourly_statistics([record], 230)[0]["sum"] == pytest.approx(0.46 / 60)


def test_history_missing_minutes_and_duplicates():
    records = [
        {"timestamp": datetime(2024, 1, 1, 10, 0, tzinfo=UTC), "current": 2},
        {"timestamp": datetime(2024, 1, 1, 10, 59, tzinfo=UTC), "current": 2},
    ]
    stats = _build_hourly_statistics(records + records, 230)
    assert len(stats) == 1
    assert stats[0]["sum"] == pytest.approx(0.46 * 2 / 60)


def test_conflicting_duplicates_fail_batch():
    t = datetime(2024, 1, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="Conflicting"):
        history_intervals(
            [{"timestamp": t, "current": 1}, {"timestamp": t, "current": 2}], 230
        )


def test_naive_device_clock_uses_ha_timezone_and_rejects_dst_folds():
    with patch.object(dt_util, "DEFAULT_TIME_ZONE", ZoneInfo("Europe/Rome")):
        intervals, rejected = history_intervals(
            [
                {"timestamp": datetime(2024, 1, 1, 12), "current": 1},
                {"timestamp": datetime(2024, 10, 27, 2, 30), "current": 1},
                {"timestamp": datetime(2024, 3, 31, 2, 30), "current": 1},
            ],
            230,
        )
    assert intervals[0].start == datetime(2024, 1, 1, 11, tzinfo=UTC)
    assert len(intervals) == 1
    assert rejected == 2


def test_aware_dst_repeated_hour_is_two_distinct_utc_hours():
    zone = ZoneInfo("Europe/Rome")
    stats = _build_hourly_statistics(
        [
            {
                "timestamp": datetime(2024, 10, 27, 2, 30, tzinfo=zone, fold=0),
                "current": 1,
            },
            {
                "timestamp": datetime(2024, 10, 27, 2, 30, tzinfo=zone, fold=1),
                "current": 1,
            },
        ],
        230,
    )
    assert [s["start"].hour for s in stats] == [0, 1]
    assert stats[-1]["sum"] == pytest.approx(0.23 * 2 / 60)


def test_partial_intervals_split_utc_hour_without_extrapolating():
    ledger = EnergyLedger()
    t = datetime(2024, 1, 1, 10, 59, 30, tzinfo=UTC)
    ledger.add(EnergyInterval(t, t + timedelta(seconds=60), 3600))
    stats = ledger.statistics()
    assert [s["sum"] for s in stats] == pytest.approx([0.03, 0.06])


@pytest.mark.parametrize("gap", [0, -1, 91, 7200])
def test_no_energy_for_duplicate_reversed_or_large_sample_gaps(gap):
    live = LiveEnergyIntegrator()
    t = dt_util.utcnow()
    assert live.sample(2, 230, t, now=t) is None
    new = t + timedelta(seconds=gap)
    assert live.sample(10, 230, new, now=new) is None


def test_live_uses_previous_power_and_stops_at_missing_data():
    live = LiveEnergyIntegrator()
    t = dt_util.utcnow()
    live.sample(2, 230, t, now=t)
    t2 = t + timedelta(seconds=30)
    interval = live.sample(10, 240, t2, now=t2)
    assert interval.kwh == pytest.approx(460 * 30 / 3600000)
    live.sample(None, 230, None)
    t3 = t2 + timedelta(seconds=30)
    assert live.sample(10, 230, t3, now=t3) is None


@pytest.mark.parametrize("current", [float("nan"), float("inf"), -1, None])
def test_invalid_sample_resets_baseline(current):
    live = LiveEnergyIntegrator()
    t = dt_util.utcnow()
    live.sample(2, 230, t, now=t)
    assert (
        live.sample(
            current, 230, t + timedelta(seconds=1), now=t + timedelta(seconds=1)
        )
        is None
    )
    assert (
        live.sample(2, 230, t + timedelta(seconds=2), now=t + timedelta(seconds=2))
        is None
    )


def test_cached_stale_sample_resets_baseline():
    live = LiveEnergyIntegrator()
    t = dt_util.utcnow()
    live.sample(2, 230, t, now=t)
    assert live.sample(2, 230, t, now=t + timedelta(minutes=5)) is None
    new = t + timedelta(minutes=5)
    assert live.sample(2, 230, new, now=new) is None


async def test_live_sensor_gap_and_first_sample_after_restore(
    hass, mock_coordinator, mock_config_entry
):
    sensor = OwlEnergySensor(mock_coordinator, mock_config_entry)
    sensor.hass = hass
    sensor._total_kwh = 7  # restored counter; no restored sample baseline
    t = dt_util.utcnow()
    data = mock_coordinator.data
    data.update(current=2, sample_timestamp=t, connected=True)
    with (
        patch.object(sensor, "async_write_ha_state"),
        patch.object(dt_util, "utcnow", return_value=t),
    ):
        sensor._handle_coordinator_update()
        assert sensor.native_value == 7
        data["sample_timestamp"] = t + timedelta(seconds=30)
        with patch.object(dt_util, "utcnow", return_value=t + timedelta(seconds=30)):
            sensor._handle_coordinator_update()
        assert sensor._total_kwh == pytest.approx(7 + 460 * 30 / 3600000)
        before = sensor._total_kwh
        data["current"] = None
        sensor._handle_coordinator_update()
        data.update(current=10, sample_timestamp=t + timedelta(hours=2))
        with patch.object(dt_util, "utcnow", return_value=t + timedelta(hours=2)):
            sensor._handle_coordinator_update()
        assert sensor._total_kwh == before


async def test_voltage_millivolts_converted_and_invalid_falls_back(hass):
    from custom_components.energy_owl.energy import resolve_voltage

    options = {"voltage_entity": "sensor.voltage", "voltage": 230}
    hass.states.async_set("sensor.voltage", "240000", {"unit_of_measurement": "mV"})
    assert resolve_voltage(hass, options) == 240
    hass.states.async_set("sensor.voltage", "nan")
    assert resolve_voltage(hass, options) == 230


async def test_reconnect_resets_live_baseline_even_without_failed_poll(hass, mock_coordinator, mock_config_entry):
    sensor = OwlEnergySensor(mock_coordinator, mock_config_entry)
    sensor.hass = hass
    t = dt_util.utcnow()
    data = mock_coordinator.data
    with patch.object(sensor, "async_write_ha_state"):
        data.update(current=2, connected=True, sample_timestamp=t)
        sensor._handle_coordinator_update()
        mock_coordinator.historical_sync_generation += 1
        data.update(sample_timestamp=t + timedelta(seconds=30))
        with patch.object(dt_util, "utcnow", return_value=t + timedelta(seconds=30)):
            sensor._handle_coordinator_update()
        assert sensor.native_value == 0
