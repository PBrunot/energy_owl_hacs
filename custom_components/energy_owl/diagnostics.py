"""Diagnostics support for Energy OWL."""

from importlib.metadata import version
from typing import Any

from homeassistant.core import HomeAssistant

from . import EnergyOwlConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: EnergyOwlConfigEntry
) -> dict[str, Any]:
    """Return public coordinator and importer snapshots."""
    return {
        "config_entry": {"title": entry.title, "version": entry.version,
                         "port": entry.data["port"]},
        "dependencies": {name: version(name) for name in ("owlsensor", "serialx")},
        "coordinator": entry.runtime_data.coordinator.diagnostics_snapshot(),
        "import": (entry.runtime_data.importer.diagnostics_snapshot()
                   if entry.runtime_data.importer else {"enabled": False}),
    }
