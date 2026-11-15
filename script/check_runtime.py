"""Exercise current HA runtime imports and action registration without pytest shims."""

import asyncio
import sys
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def main() -> None:
    """Construct actual HA/OWL objects without opening a physical serial port."""
    from homeassistant.core import HomeAssistant, SupportsResponse
    from homeassistant.helpers import frame

    from custom_components.energy_owl import async_setup
    from custom_components.energy_owl.collector import get_async_datacollector
    from custom_components.energy_owl.config_flow import OwlConfigFlow
    from custom_components.energy_owl.const import DOMAIN
    from custom_components.energy_owl.coordinator import OwlDataUpdateCoordinator
    from custom_components.energy_owl.sensor import async_setup_entry
    from custom_components.energy_owl.statistics import OwlStatisticsImporter

    with TemporaryDirectory() as config_dir:
        hass = HomeAssistant(config_dir)
        frame.async_setup(hass)
        assert await async_setup(hass, {})
        assert hass.services.supports_response(DOMAIN, "get_historical_data") is SupportsResponse.OPTIONAL
        for action in ("get_historical_data", "clear_historical_data", "export_historical_data_csv", "force_reconnect"):
            assert hass.services.has_service(DOMAIN, action)
        coordinator = OwlDataUpdateCoordinator(hass, "/dev/not-opened")
        assert not coordinator.connected
        collector = get_async_datacollector("/dev/not-opened", "CM160", 5)
        assert not collector.connected
        assert collector.get_live_sample() == (None, None)
        assert OwlConfigFlow.VERSION == 1
        assert callable(async_setup_entry) and callable(OwlStatisticsImporter)
        await collector.disconnect()
        await coordinator.async_disconnect()
    print(f"Runtime imports, constructors and action registration pass on HA {version('homeassistant')}")


if __name__ == "__main__":
    asyncio.run(main())
