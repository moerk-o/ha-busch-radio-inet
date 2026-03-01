"""Persistent UDP listener for Busch-Radio iNet.

Binds to port 4242 and receives all packets from the device:
  - ACK/NACK responses to GET and SET commands
  - NOTIFICATION push events (triggers follow-up GETs)
"""

import asyncio
import logging
from collections.abc import Callable

_LOGGER = logging.getLogger(__name__)


def parse_packet(message: str) -> dict:
    """Parse a raw UDP packet into a field dict.

    Lines with 'key:value' are stored as {key: value}.
    If the same key appears multiple times, the value becomes a list
    (used for ALL_STATION_INFO where CHANNEL/NAME/URL repeat).
    Lines without ':' are stored as {'_parameter': line} (e.g. 'POWER_STATUS').

    After parsing, ALL_STATION_INFO responses are post-processed into
    a '_stations' list of {'id', 'name', 'url'} dicts.
    """
    fields: dict = {}
    for raw_line in message.split("\r\n"):
        line = raw_line.strip()
        if not line:
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            # "ID:HA" is always part of the command echo (we send every
            # command with ID:HA).  The station ID in PLAYING_MODE responses
            # also uses the key "ID" (e.g. "ID:2"), so we skip the echo to
            # avoid a list collision.
            if key == "ID" and value == "HA":
                continue
            if key in fields:
                existing = fields[key]
                if isinstance(existing, list):
                    existing.append(value)
                else:
                    fields[key] = [existing, value]
            else:
                fields[key] = value
        else:
            # Parameter line (e.g. "POWER_STATUS", "ALL_STATION_INFO", "RADIO_ON")
            if "_parameter" not in fields:
                fields["_parameter"] = line

    # Post-process ALL_STATION_INFO into a station list
    channels = fields.get("CHANNEL")
    if channels is not None:
        if isinstance(channels, str):
            channels = [channels]
        names = fields.get("NAME", [])
        urls = fields.get("URL", [])
        if isinstance(names, str):
            names = [names]
        if isinstance(urls, str):
            urls = [urls]
        stations = []
        for i, ch in enumerate(channels):
            name = names[i] if i < len(names) else ""
            url = urls[i] if i < len(urls) else ""
            if name:  # Filter empty slots
                try:
                    stations.append({"id": int(ch), "name": name, "url": url})
                except ValueError:
                    _LOGGER.warning("Invalid channel number: %s", ch)
        fields["_stations"] = stations

    return fields


class _UDPProtocol(asyncio.DatagramProtocol):
    """asyncio DatagramProtocol that forwards received datagrams to a handler."""

    def __init__(self, on_message: Callable[[str], None]) -> None:
        self._on_message = on_message

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        _LOGGER.debug("UDP listener bound successfully")

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        try:
            message = data.decode("utf-8")
            _LOGGER.debug("UDP received from %s: %s", addr, message[:200])
            self._on_message(message)
        except Exception as exc:
            _LOGGER.error("Error processing UDP datagram from %s: %s", addr, exc)

    def error_received(self, exc: Exception) -> None:
        _LOGGER.error("UDP listener error: %s", exc)

    def connection_lost(self, exc: Exception | None) -> None:
        if exc:
            _LOGGER.warning("UDP listener connection lost: %s", exc)


class BuschRadioUDPListener:
    """Persistent UDP listener on port 4242.

    Parses incoming packets and:
    - Calls on_packet(fields) for GET/SET responses (ACK/NACK)
    - Sends follow-up GET commands for NOTIFICATION events
    """

    def __init__(
        self,
        port: int,
        on_packet: Callable[[dict], None],
        client,
    ) -> None:
        self._port = port
        self._on_packet = on_packet
        self._client = client
        self._transport: asyncio.DatagramTransport | None = None

    async def start(self) -> None:
        """Bind to the listen port and start receiving packets."""
        loop = asyncio.get_running_loop()
        self._transport, _ = await loop.create_datagram_endpoint(
            lambda: _UDPProtocol(self._handle_message),
            local_addr=("0.0.0.0", self._port),
        )
        _LOGGER.debug("UDP listener started on port %d", self._port)

    def stop(self) -> None:
        """Close the UDP socket."""
        if self._transport is not None:
            self._transport.close()
            self._transport = None
            _LOGGER.debug("UDP listener stopped")

    def _handle_message(self, message: str) -> None:
        """Route an incoming UDP message."""
        fields = parse_packet(message)
        command = fields.get("COMMAND")

        if command == "NOTIFICATION":
            asyncio.get_running_loop().create_task(
                self._handle_notification(fields)
            )
        else:
            self._on_packet(fields)

    async def _handle_notification(self, fields: dict) -> None:
        """Send the appropriate follow-up GET for a NOTIFICATION event."""
        event = fields.get("EVENT")
        _LOGGER.debug("Received NOTIFICATION event: %s", event)
        if event == "VOLUME_CHANGED":
            await self._client.send_get("VOLUME")
        elif event in ("STATION_CHANGED", "URL_IS_PLAYING"):
            await self._client.send_get("PLAYING_MODE")
        elif event in ("POWER_ON", "POWER_OFF"):
            await self._client.send_get("POWER_STATUS")
        else:
            _LOGGER.debug("Unknown NOTIFICATION event ignored: %s", event)
