"""UDP client for Busch-Radio iNet – fire-and-forget sender."""

import asyncio
import logging

_LOGGER = logging.getLogger(__name__)


class BuschRadioUDPClient:
    """Send UDP commands to the device on port 4244.

    Fire-and-forget: no receive socket, all responses arrive via the listener.
    """

    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port

    async def send_raw(self, message: str) -> None:
        """Send a raw UDP message string to the device."""
        data = message.encode()
        loop = asyncio.get_running_loop()
        transport = None
        try:
            transport, _ = await loop.create_datagram_endpoint(
                asyncio.DatagramProtocol,
                remote_addr=(self._host, self._port),
            )
            transport.sendto(data)
        except OSError as exc:
            _LOGGER.error(
                "Failed to send UDP command to %s:%s – %s", self._host, self._port, exc
            )
        finally:
            if transport is not None:
                transport.close()

    async def send_get(self, parameter: str) -> None:
        """Send a GET command: COMMAND:GET\\r\\n<parameter>\\r\\nID:HA\\r\\n\\r\\n"""
        await self.send_raw(f"COMMAND:GET\r\n{parameter}\r\nID:HA\r\n\r\n")

    async def send_set(self, parameter: str) -> None:
        """Send a SET command: COMMAND:SET\\r\\n<parameter>\\r\\nID:HA\\r\\n\\r\\n"""
        await self.send_raw(f"COMMAND:SET\r\n{parameter}\r\nID:HA\r\n\r\n")

    async def send_play(self, parameter: str) -> None:
        """Send a PLAY command: COMMAND:PLAY\\r\\n<parameter>\\r\\nID:HA\\r\\n\\r\\n"""
        await self.send_raw(f"COMMAND:PLAY\r\n{parameter}\r\nID:HA\r\n\r\n")
