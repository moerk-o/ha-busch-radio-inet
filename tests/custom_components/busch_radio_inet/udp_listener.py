"""Persistent UDP listener for Busch-Radio iNet.

Binds once to port 4242 and receives packets from all registered devices.
Multiple devices are supported: each device registers its IP address and
callbacks; incoming packets are routed to the correct device by source IP.
"""

import asyncio
import logging
import socket as _socket
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

    def __init__(self, on_message: Callable[[str, tuple], None]) -> None:
        self._on_message = on_message

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        _LOGGER.debug("UDP listener bound successfully")

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        try:
            message = data.decode("utf-8")
            _LOGGER.debug("UDP received from %s: %s", addr, message[:200])
            self._on_message(message, addr)
        except Exception as exc:
            _LOGGER.error("Error processing UDP datagram from %s: %s", addr, exc)

    def error_received(self, exc: Exception) -> None:
        _LOGGER.error("UDP listener error: %s", exc)

    def connection_lost(self, exc: Exception | None) -> None:
        if exc:
            _LOGGER.warning("UDP listener connection lost: %s", exc)


class SharedUDPListener:
    """Shared UDP listener on port 4242, supporting multiple devices.

    Binds once and routes incoming packets to the correct device coordinator
    based on the source IP address of each datagram.

    Usage::

        listener = SharedUDPListener(port=4242)
        await listener.start()

        listener.register(host, on_packet, client, on_notification)
        # ... later ...
        listener.unregister(host)

        if not listener.has_devices:
            listener.stop()
    """

    def __init__(self, port: int) -> None:
        self._port = port
        # host -> (on_packet, on_notification, client)
        self._devices: dict[
            str,
            tuple[
                Callable[[dict], None],
                Callable[[str], None] | None,
                object,
            ],
        ] = {}
        self._transport: asyncio.DatagramTransport | None = None

    # ------------------------------------------------------------------
    # Device registration
    # ------------------------------------------------------------------

    def register(
        self,
        host: str,
        on_packet: Callable[[dict], None],
        client,
        on_notification: Callable[[str], None] | None = None,
    ) -> Callable[[], None]:
        """Register a device coordinator for the given host IP.

        Returns a callable that undoes this registration, restoring whatever
        was registered for the host before.  The config flow probes a device
        by registering temporarily and must not tear down the registration of
        an already loaded entry using the same host (see validate_connection()).
        """
        previous = self._devices.get(host)
        self._devices[host] = (on_packet, on_notification, client)
        _LOGGER.debug("Registered device %s (total: %d)", host, len(self._devices))

        def _undo() -> None:
            if previous is None:
                self.unregister(host)
            else:
                self._devices[host] = previous
                _LOGGER.debug("Restored previous registration for %s", host)

        return _undo

    def unregister(self, host: str) -> None:
        """Unregister a device coordinator."""
        self._devices.pop(host, None)
        _LOGGER.debug("Unregistered device %s (total: %d)", host, len(self._devices))

    @property
    def has_devices(self) -> bool:
        """Return True if at least one device is registered."""
        return bool(self._devices)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Bind to the listen port and start receiving packets.

        Uses SO_REUSEADDR so the socket can be rebound immediately after a
        previous close (e.g. on integration reload).  Falls back to a short
        retry loop in case the OS still needs a moment to release the port.
        """
        loop = asyncio.get_running_loop()
        last_exc: OSError | None = None
        for attempt in range(5):
            try:
                sock = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
                sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
                sock.bind(("0.0.0.0", self._port))
                sock.setblocking(False)
                self._transport, _ = await loop.create_datagram_endpoint(
                    lambda: _UDPProtocol(self._handle_datagram),
                    sock=sock,
                )
                _LOGGER.debug("UDP listener started on port %d", self._port)
                return
            except OSError as exc:
                last_exc = exc
                _LOGGER.debug(
                    "UDP port %d not yet free (attempt %d/5), retrying in 0.5 s …",
                    self._port,
                    attempt + 1,
                )
                await asyncio.sleep(0.5)
        raise last_exc  # type: ignore[misc]

    def stop(self) -> None:
        """Close the UDP socket."""
        if self._transport is not None:
            self._transport.close()
            self._transport = None
            _LOGGER.debug("UDP listener stopped")

    # ------------------------------------------------------------------
    # Internal routing
    # ------------------------------------------------------------------

    def _handle_datagram(self, message: str, addr: tuple) -> None:
        """Route an incoming UDP datagram to the correct device coordinator."""
        source_ip = addr[0]
        device = self._devices.get(source_ip)
        if device is None:
            _LOGGER.debug("UDP packet from unknown source %s ignored", source_ip)
            return

        on_packet, on_notification, client = device
        fields = parse_packet(message)
        command = fields.get("COMMAND")

        if command == "NOTIFICATION":
            asyncio.get_running_loop().create_task(
                self._handle_notification(fields, client, on_notification)
            )
        else:
            on_packet(fields)

    async def _handle_notification(
        self,
        fields: dict,
        client,
        on_notification: Callable[[str], None] | None,
    ) -> None:
        """Send the appropriate follow-up GET for a NOTIFICATION event."""
        event = fields.get("EVENT")
        _LOGGER.debug("Received NOTIFICATION event: %s", event)
        if event == "VOLUME_CHANGED":
            await client.send_get("VOLUME")
        elif event in ("STATION_CHANGED", "URL_IS_PLAYING"):
            await client.send_get("PLAYING_MODE")
        elif event in ("POWER_ON", "POWER_OFF"):
            await client.send_get("POWER_STATUS")
        else:
            _LOGGER.debug("Unknown NOTIFICATION event ignored: %s", event)

        if event and on_notification:
            on_notification(event)
