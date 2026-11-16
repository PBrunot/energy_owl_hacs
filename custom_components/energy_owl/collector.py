"""Receipt timestamps for the owlsensor 0.7.2 live packet stream."""

from homeassistant.util import dt as dt_util
from owlsensor import SUPPORTED_SENSORS, CMDataCollector
from owlsensor.const import CURRENT


class TimestampedCollector(CMDataCollector):
    """Observe successful live packets, including repeated identical readings."""

    _live_sample = (None, None)

    @property
    def sample_timestamp(self):
        return self._live_sample[1]

    def get_live_sample(self):
        return self._live_sample if self.connected else (None, None)

    def discard_historical_prefix(self, count: int) -> None:
        """Discard a persisted prefix on the event loop, preserving newer packets.

        owlsensor 0.7.2 only exposes a whole-buffer clear. Its parser appends on
        this same event loop, so this synchronous slice cannot race an append.
        This is local housekeeping; it sends no command to the device.
        """
        del self._historical_data[:count]

    async def parse_packet(self, buffer):
        result = await super().parse_packet(buffer)
        # Match the pinned library's post-parse consistency check. An invalid
        # packet must not make its previous cached current look fresh.
        if result is not None and result.get(CURRENT) is not None:
            current = result[CURRENT]
            if 0 <= current <= 100:
                self._live_sample = (current, dt_util.utcnow())
        return result


def get_async_datacollector(port, model, timeout):
    return TimestampedCollector(port, SUPPORTED_SENSORS[model], timeout)
