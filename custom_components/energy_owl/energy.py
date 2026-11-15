"""Validated timestamp-based energy estimates (unity power factor)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite

from homeassistant.util import dt as dt_util

MAX_SAMPLE_GAP = 90  # seconds; three coordinator polling intervals
HISTORY_INTERVAL = timedelta(minutes=1)


def positive_number(value, *, allow_zero=False) -> float:
    number = float(value)
    if not isfinite(number) or number < 0 or (not allow_zero and number == 0):
        raise ValueError("Measurement must be finite and nonnegative")
    return number


def utc_timestamp(value: datetime) -> datetime:
    """Normalize aware timestamps; interpret device wall clock in HA's timezone.

    The CM160 supplies no UTC offset or DST fold. Reject ambiguous/nonexistent
    local times rather than guessing and importing them into the wrong hour.
    """
    if not isinstance(value, datetime):
        raise TypeError("Invalid timestamp")
    if value.tzinfo is None:
        zone = dt_util.DEFAULT_TIME_ZONE
        first = value.replace(tzinfo=zone, fold=0)
        second = value.replace(tzinfo=zone, fold=1)
        if first.utcoffset() != second.utcoffset():
            raise ValueError("Ambiguous or nonexistent device wall-clock time")
        value = first
    return dt_util.as_utc(value)


@dataclass(frozen=True)
class EnergyInterval:
    start: datetime
    end: datetime
    power_w: float

    @property
    def kwh(self) -> float:
        return self.power_w * (self.end - self.start).total_seconds() / 3600000


class LiveEnergyIntegrator:
    """Left-rectangle integration; never extrapolate across missing/stale data."""

    def __init__(self):
        self._previous: tuple[datetime, float] | None = None

    def reset(self):
        self._previous = None

    def sample(self, current, voltage, timestamp, *, valid=True, now=None):
        try:
            if not valid or timestamp is None:
                raise ValueError("Unavailable sample")
            timestamp = utc_timestamp(timestamp)
            now = dt_util.as_utc(now or dt_util.utcnow())
            if not 0 <= (now - timestamp).total_seconds() <= MAX_SAMPLE_GAP:
                raise ValueError("Stale sample")
            power = positive_number(current, allow_zero=True) * positive_number(voltage)
            if not isfinite(power):
                raise ValueError("Power overflow")
        except (TypeError, ValueError):
            self.reset()
            return None
        previous = self._previous
        if previous and timestamp <= previous[0]:
            # A duplicate poll of a cached device reading contributes no energy.
            return None
        self._previous = (timestamp, power)
        if previous and (timestamp - previous[0]).total_seconds() <= MAX_SAMPLE_GAP:
            return EnergyInterval(previous[0], timestamp, previous[1])
        return None


def history_intervals(records, voltage, *, now=None):
    """A CM160 minute record represents [timestamp, timestamp + one minute).

    Missing minutes are never filled. Identical duplicates collapse; conflicting
    duplicates fail the batch so a later record cannot hide an earlier failure.
    """
    voltage = positive_number(voltage)
    now = dt_util.as_utc(now or dt_util.utcnow())
    unique = {}
    rejected = 0
    for record in records:
        try:
            start = utc_timestamp(record["timestamp"])
            current = positive_number(record["current"], allow_zero=True)
            if start.second or start.microsecond or start + HISTORY_INTERVAL > now:
                raise ValueError("Invalid device minute")
            power = positive_number(current * voltage, allow_zero=True)
        except (KeyError, TypeError, ValueError):
            rejected += 1
            continue
        if start in unique and unique[start] != power:
            raise ValueError("Conflicting historical records at the same timestamp")
        unique[start] = power
    if records and not unique:
        raise ValueError("No valid historical minutes")
    return [
        EnergyInterval(t, t + HISTORY_INTERVAL, p) for t, p in sorted(unique.items())
    ], rejected


def resolve_voltage(hass, options):
    """Return valid live volts, with the fixed configured voltage as fallback."""
    from homeassistant.util.unit_conversion import ElectricPotentialConverter

    from .const import CONF_VOLTAGE, CONF_VOLTAGE_ENTITY, DEFAULT_VOLTAGE

    entity_id = options.get(CONF_VOLTAGE_ENTITY)
    state = hass.states.get(entity_id) if entity_id else None
    if state:
        try:
            voltage = positive_number(state.state)
            unit = state.attributes.get("unit_of_measurement", "V")
            return positive_number(
                ElectricPotentialConverter.convert(voltage, unit, "V")
            )
        except (ValueError, TypeError):
            pass
    return positive_number(options.get(CONF_VOLTAGE, DEFAULT_VOLTAGE))
