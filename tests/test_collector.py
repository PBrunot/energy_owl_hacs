"""Real owlsensor API compatibility and receipt timestamp regression."""

from unittest.mock import AsyncMock, patch

from owlsensor import CMDataCollector

from custom_components.energy_owl.collector import get_async_datacollector


async def test_only_live_packets_advance_timestamp():
    collector = get_async_datacollector("/dev/test-not-opened", "CM160", 5)
    assert isinstance(collector, CMDataCollector)
    assert collector.sample_timestamp is None
    with patch.object(CMDataCollector, "parse_packet", new_callable=AsyncMock) as parse:
        parse.return_value = None
        await collector.parse_packet(bytearray())
        assert collector.sample_timestamp is None
        parse.return_value = {"Current": 2}
        await collector.parse_packet(bytearray())
        first = collector.sample_timestamp
        assert first is not None
        await collector.parse_packet(
            bytearray()
        )  # identical current is still a fresh packet
        assert collector.sample_timestamp >= first
        parse.return_value = None
        await collector.parse_packet(bytearray())
        assert collector.sample_timestamp >= first


async def test_invalid_packet_does_not_refresh_cached_sample():
    collector = get_async_datacollector("/dev/test-not-opened", "CM160", 5)
    collector.connected = True
    with patch.object(CMDataCollector, "parse_packet", new_callable=AsyncMock) as parse:
        parse.return_value = {"Current": 2}
        await collector.parse_packet(bytearray())
        sample = collector.get_live_sample()
        parse.return_value = {"Current": 999}
        await collector.parse_packet(bytearray())
        assert collector.get_live_sample() == sample
        collector.connected = False
        assert collector.get_live_sample() == (None, None)
