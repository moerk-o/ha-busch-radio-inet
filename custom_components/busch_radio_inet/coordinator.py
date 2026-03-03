"""State coordinator for Busch-Radio iNet.

Holds the complete device state and notifies registered callbacks whenever
something changes.  Also runs a fallback poll every POLL_INTERVAL seconds
in case a NOTIFICATION was missed.
"""

import logging
from collections.abc import Callable
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

from .const import POLL_INTERVAL

_LOGGER = logging.getLogger(__name__)


class BuschRadioCoordinator:
    """Manages device state and notifies the media_player entity on changes."""

    def __init__(self, hass: HomeAssistant, client) -> None:
        self._hass = hass
        self._client = client

        # Device state – all None until the first response arrives
        self.power: bool | None = None
        self.volume: int | None = None       # raw 0–31
        self.muted: bool = False
        self.station_id: int | None = None
        self.station_name: str | None = None
        self.station_list: list[dict] = []   # [{'id', 'name', 'url'}, …]
        self.device_name: str | None = None
        self.sw_version: str | None = None
        self.serial_number: str | None = None

        self._callbacks: list[Callable[[], None]] = []
        self._cancel_poll: Callable | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_ready(self) -> bool:
        """True once we have received at least power state and volume."""
        return self.power is not None and self.volume is not None

    def register_callback(self, callback: Callable[[], None]) -> None:
        """Register a function to be called on every state change."""
        self._callbacks.append(callback)

    def unregister_callback(self, callback: Callable[[], None]) -> None:
        """Remove a previously registered callback."""
        self._callbacks.remove(callback)

    def start_polling(self) -> None:
        """Start the periodic fallback poll."""
        self._cancel_poll = async_track_time_interval(
            self._hass,
            self._async_poll,
            timedelta(seconds=POLL_INTERVAL),
        )

    def stop_polling(self) -> None:
        """Cancel the periodic fallback poll."""
        if self._cancel_poll is not None:
            self._cancel_poll()
            self._cancel_poll = None

    def handle_packet(self, fields: dict) -> None:
        """Process a parsed UDP packet and update state.

        Called by the listener for every non-NOTIFICATION packet.
        """
        if fields.get("RESPONSE") == "NACK":
            _LOGGER.debug(
                "Received NACK for command '%s', ignoring",
                fields.get("_parameter", "?"),
            )
            return

        changed = False

        # --- Power state (from GET POWER_STATUS or SET RADIO_ON/OFF ACK) ---
        if "POWER" in fields:
            new_power = fields["POWER"] == "ON"
            if self.power != new_power:
                self.power = new_power
                changed = True

        # --- Power state from SET ACK (RADIO_ON / RADIO_OFF) ---
        param = fields.get("_parameter")
        if param == "RADIO_ON" and fields.get("RESPONSE") == "ACK":
            if self.power is not True:
                self.power = True
                changed = True
        elif param == "RADIO_OFF" and fields.get("RESPONSE") == "ACK":
            if self.power is not False:
                self.power = False
                changed = True

        # --- Volume ---
        if "VOLUME_SET" in fields:
            try:
                vol = int(fields["VOLUME_SET"])
                if self.volume != vol:
                    self.volume = vol
                    changed = True
            except (ValueError, TypeError):
                _LOGGER.warning("Invalid VOLUME_SET value: %s", fields["VOLUME_SET"])

        # --- Playing mode: active ---
        if fields.get("PLAYING") == "STATION":
            try:
                sid = int(fields.get("ID", 0))
                name = fields.get("NAME", "")
                if self.station_id != sid or self.station_name != name:
                    self.station_id = sid
                    self.station_name = name
                    changed = True
            except (ValueError, TypeError):
                _LOGGER.warning("Invalid station ID: %s", fields.get("ID"))

        # --- Playing mode: stopped ---
        if fields.get("MODE") == "PLAYING STOPPED":
            if self.station_id is not None or self.station_name is not None:
                self.station_id = None
                self.station_name = None
                changed = True

        # --- Station list (ALL_STATION_INFO) ---
        if "_stations" in fields:
            new_list = fields["_stations"]
            if self.station_list != new_list:
                self.station_list = new_list
                changed = True

        # --- Device info (INFO_BLOCK) ---
        if "SERNO" in fields:
            self.serial_number = fields.get("SERNO")
            self.sw_version = fields.get("SW-VERSION")
            self.device_name = fields.get("NAME")
            changed = True

        if changed:
            self._notify_callbacks()

    def set_muted(self, muted: bool) -> None:
        """Update mute state (tracked locally; device has no GET for mute)."""
        if self.muted != muted:
            self.muted = muted
            self._notify_callbacks()

    def set_station(self, station_id: int, station_name: str) -> None:
        """Optimistically update station after a PLAY command."""
        if self.station_id != station_id or self.station_name != station_name:
            self.station_id = station_id
            self.station_name = station_name
            self._notify_callbacks()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _notify_callbacks(self) -> None:
        for cb in self._callbacks:
            cb()

    async def _async_poll(self, _now=None) -> None:
        """Periodic fallback poll – keeps state fresh if a notification was lost."""
        _LOGGER.debug("Fallback poll: refreshing device state")
        await self._client.send_get("POWER_STATUS")
        await self._client.send_get("VOLUME")
        await self._client.send_get("PLAYING_MODE")
