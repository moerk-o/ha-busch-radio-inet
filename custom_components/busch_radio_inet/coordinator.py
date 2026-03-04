"""State coordinator for Busch-Radio iNet.

Holds the complete device state and notifies registered callbacks whenever
something changes.  Also runs a fallback poll every POLL_INTERVAL seconds
in case a NOTIFICATION was missed.
"""

import asyncio
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
        self.media_title: str | None = None  # ICY StreamTitle (None = use station_name)
        self.media_image_url: str | None = None  # artwork URL (Tier 1 or Tier 2)
        self.device_name: str | None = None
        self.sw_version: str | None = None
        self.serial_number: str | None = None
        self.energy_mode: str | None = None

        self._callbacks: list[Callable[[], None]] = []
        self._cancel_poll: Callable | None = None
        self._icy_fetcher = None  # set via set_icy_fetcher()
        self._artwork_client = None  # set via set_artwork_client()
        self._artwork_task: asyncio.Task | None = None
        self._artwork_generation: int = 0

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

    def start_icy_if_playing(self) -> None:
        """Start ICY fetch if the radio is already playing.

        Called once after startup/reload to handle the case where the radio
        was already playing when the integration loaded (no URL_IS_PLAYING
        event is emitted for a stream that is already running).
        """
        if not self.power or not self.station_id:
            return
        url = self._get_current_stream_url()
        if url and self._icy_fetcher is not None:
            _LOGGER.debug("Radio already playing on startup – starting ICY fetch for %s", url)
            self._icy_fetcher.start(url)

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

        # --- Power state + energy mode (from GET POWER_STATUS) ---
        if "POWER" in fields:
            new_power = fields["POWER"] == "ON"
            if self.power != new_power:
                self.power = new_power
                changed = True

        if "ENERGY_MODE" in fields:
            new_mode = fields["ENERGY_MODE"]
            if self.energy_mode != new_mode:
                self.energy_mode = new_mode
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
                    self.media_image_url = None  # clear immediately; callback follows
                    changed = True
                    self._schedule_artwork_lookup()  # Tier 2 trigger
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

    def set_media_title(self, title: str | None) -> None:
        """Update media title from ICY metadata."""
        if self.media_title != title:
            self.media_title = title
            self._notify_callbacks()
            if title and " - " in title:  # Tier 1 trigger
                self._schedule_artwork_lookup()

    def set_media_image(self, url: str | None) -> None:
        """Update artwork URL and notify callbacks if changed."""
        if self.media_image_url != url:
            self.media_image_url = url
            self._notify_callbacks()

    def handle_notification(self, event: str) -> None:
        """React to a raw NOTIFICATION event forwarded by the UDP listener."""
        _LOGGER.debug("Coordinator handling notification: %s", event)
        if event == "STATION_CHANGED":
            self._on_station_changed()
        elif event == "URL_IS_PLAYING":
            self._on_url_is_playing()
        elif event == "POWER_OFF":
            self._on_power_off()

    def set_icy_fetcher(self, fetcher) -> None:
        """Attach an ICY fetcher (IcyIntervalScheduler or IcyPersistentConnection)."""
        self._icy_fetcher = fetcher

    def stop_icy(self) -> None:
        """Stop any running ICY fetch/timer."""
        if self._icy_fetcher is not None:
            self._icy_fetcher.stop()

    def set_artwork_client(self, client) -> None:
        """Attach the ArtworkClient (called from __init__.py after setup)."""
        self._artwork_client = client

    def stop_artwork(self) -> None:
        """Cancel any running artwork lookup task."""
        if self._artwork_task is not None:
            self._artwork_task.cancel()
            self._artwork_task = None

    def _on_station_changed(self) -> None:
        """Station is changing – stop ICY fetch, cancel artwork, clear stale title."""
        if self._icy_fetcher is not None:
            self._icy_fetcher.stop()
        self.stop_artwork()
        self.media_image_url = None  # cleared; set_media_title(None) triggers callback
        self.set_media_title(None)

    def _on_url_is_playing(self) -> None:
        """Stream is stable – start ICY fetch for the current station."""
        url = self._get_current_stream_url()
        if url and self._icy_fetcher is not None:
            self._icy_fetcher.start(url)

    def _on_power_off(self) -> None:
        """Device switched off – stop ICY fetch, cancel artwork, clear title."""
        if self._icy_fetcher is not None:
            self._icy_fetcher.stop()
        self.stop_artwork()
        self.set_media_image(None)
        self.set_media_title(None)

    def _get_current_stream_url(self) -> str | None:
        """Return the stream URL for the currently playing station_id."""
        if not self.station_id:
            return None
        for station in self.station_list:
            if station["id"] == self.station_id:
                return station.get("url")
        return None

    # ------------------------------------------------------------------
    # Artwork lookup (Cancel-and-Replace + Generation Counter)
    # ------------------------------------------------------------------

    def _schedule_artwork_lookup(self) -> None:
        """Cancel any running lookup and start a fresh one."""
        if self._artwork_client is None:
            return
        if self._artwork_task is not None:
            self._artwork_task.cancel()
        self._artwork_generation += 1
        self._artwork_task = self._hass.async_create_task(
            self._async_artwork_lookup(self._artwork_generation)
        )

    async def _async_artwork_lookup(self, generation: int) -> None:
        """Fetch artwork (Tier 1 then Tier 2) and update media_image_url."""
        try:
            url: str | None = None
            title = self.media_title

            # Tier 1: music artwork when "Artist - Title" format is present
            if title and " - " in title:
                artist, _, song = title.partition(" - ")
                url = await self._artwork_client.fetch_music_artwork(
                    artist.strip(), song.strip()
                )

            # Tier 2: station logo as final fallback
            if url is None:
                url = await self._artwork_client.fetch_station_logo(
                    self._get_current_stream_url(), self.station_name or ""
                )

            # Only write result if this generation is still current
            if generation == self._artwork_generation:
                self.set_media_image(url)
        except asyncio.CancelledError:
            pass  # Normal: stop_artwork() or a newer _schedule_artwork_lookup() called

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
