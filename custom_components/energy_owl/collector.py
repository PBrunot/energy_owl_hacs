"""Receipt timestamps for the owlsensor 0.7.2 live packet stream."""

from time import monotonic

from homeassistant.util import dt as dt_util
from owlsensor import SUPPORTED_SENSORS, CMDataCollector
from owlsensor.const import CURRENT


class TimestampedCollector(CMDataCollector):
    """Observe successful live packets, including repeated identical readings."""

    _live_sample = (None, None)
    _last_packet_at: float | None = None

    async def connect(self) -> bool:
        """Start the inactivity timer when the serial session opens."""
        connected = await super().connect()
        if connected:
            self._last_packet_at = monotonic()
        return connected

    async def get_packet(self) -> bytearray:
        """Track serial activity independently of live and historical batch state."""
        packet = await super().get_packet()
        if packet:
            self._last_packet_at = monotonic()
        return packet

    def transport_idle_for(self, seconds: float) -> bool:
        """Return whether an open session has stopped delivering packets."""
        return self._last_packet_at is not None and monotonic() - self._last_packet_at >= seconds

    @property
    def transport_lost(self) -> bool:
        """Detect a failed serial stream even if owlsensor still marks it connected."""
        return (
            not self.connected
            or (self.reader is not None and self.reader.at_eof())
            or (self.writer is not None and self.writer.is_closing())
            or (self.update_task is not None and self.update_task.done())
        )

    async def read_data(self):
        """Leave reconnect and disposal of the old transport to the coordinator."""
        if self.transport_lost:
            return None
        return await super().read_data()

    @property
    def sample_timestamp(self):
        return self._live_sample[1]

    def get_live_sample(self):
        return (None, None) if self.transport_lost else self._live_sample

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
