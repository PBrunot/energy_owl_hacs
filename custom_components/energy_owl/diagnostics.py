"""Diagnostics support for Energy OWL CM160 integration."""

from __future__ import annotations

import time
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .coordinator import OwlDataUpdateCoordinator

TO_REDACT: set[str] = set()  # nothing sensitive, but keep the pattern for future use


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: OwlDataUpdateCoordinator = entry.runtime_data.coordinator

    connection_info = _build_connection_info(coordinator)
    historical_info = _build_historical_info(coordinator)
    recovery_info = _build_recovery_info(coordinator)

    return async_redact_data(
        {
            "config_entry": {
                "title": entry.title,
                "version": entry.version,
                "port": coordinator.port,
            },
            "connection": connection_info,
            "historical_sync": historical_info,
            "auto_recovery": recovery_info,
            "coordinator": {
                "total_updates": coordinator.total_updates,
                "error_count": coordinator.error_count,
                "last_error": coordinator.last_error,
                "last_update_success": coordinator.last_update_success,
            },
        },
        TO_REDACT,
    )


def _build_connection_info(coordinator: OwlDataUpdateCoordinator) -> dict[str, Any]:
    """Build connection status block."""
    info: dict[str, Any] = {
        "connected": coordinator.connected,
        "port": coordinator.port,
        "last_error": coordinator.last_error,
    }
    if not coordinator.connected and coordinator.last_error:
        info["hint"] = (
            "Device is not connected. Common causes: wrong port path, "
            "device not plugged in, or another process has the port open. "
            "Try unplugging and re-plugging the CM160 USB adapter, then use "
            "the 'force_reconnect' service, or reload the integration."
        )
    return info


def _build_historical_info(coordinator: OwlDataUpdateCoordinator) -> dict[str, Any]:
    """Build historical data synchronisation block."""
    info: dict[str, Any] = {
        "complete": coordinator.historical_data_complete,
        "records_collected": coordinator.historical_data_count,
        "pushers_registered": len(coordinator._historical_data_pushers),
        "all_pushers_complete": coordinator._all_pushers_complete,
    }
    if coordinator._last_new_historical_record_time is not None:
        elapsed = time.monotonic() - coordinator._last_new_historical_record_time
        info["seconds_since_last_new_record"] = round(elapsed, 1)
    return info


def _build_recovery_info(coordinator: OwlDataUpdateCoordinator) -> dict[str, Any]:
    """Build automatic-recovery status block."""
    info: dict[str, Any] = {
        "auto_recovery_enabled": coordinator._auto_recovery_enabled,
        "recovery_attempts": coordinator._recovery_attempts,
        "max_recovery_attempts": coordinator._max_recovery_attempts,
    }
    if coordinator._historical_completion_time is not None:
        elapsed = time.monotonic() - coordinator._historical_completion_time
        info["minutes_since_historical_completion"] = round(elapsed / 60, 1)
        info["auto_recovery_timeout_minutes"] = round(
            coordinator._auto_recovery_timeout / 60, 1
        )
    return info
