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

from .const import POLL_INTERVAL, QUERY_SPACING, STARTUP_RETRY_DELAYS

_LOGGER = logging.getLogger(__name__)


class BuschRadioCoordinator:
    """Manages device state and notifies the media_player entity on changes."""

    def __init__(self, hass: HomeAssistant, client, host: str = "") -> None:
        self._hass = hass
        self._client = client
        self._host = host

        # Device state – all None until the first response arrives
        self.power: bool | None = None
        self.volume: int | None = None       # raw 0–31
        self.muted: bool = False
        self.station_id: int | None = None
        self.station_name: str | None = None
        self.station_list: list[dict] = []   # [{'id', 'name', 'url'}, …]
        self.input_source: str | None = None  # "UPnP"/"AUX" when active, else None (station mode)
        self.media_title: str | None = None  # ICY StreamTitle (None = use station_name)
        self.media_image_url: str | None = None  # artwork URL (Tier 1 or Tier 2)
        self.device_name: str | None = None
        self.sw_version: str | None = None
        self.serial_number: str | None = None
        self.mac_address: str | None = None
        self.energy_mode: str | None = None

        # PLAYING_MODE has no field of its own that survives an "idle" answer,
        # so completion of that query is tracked explicitly.
        self._playing_mode_known: bool = False

        self._reachable: bool = True  # set False when the device stops answering
        self._reachability_client = None  # set via set_reachability_client()

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
        """True once the device has reported its power state.

        Volume is deliberately not required: it arrives in its own UDP answer,
        and nothing that decides what the entity shows depends on it — see
        TECHNICAL_REFERENCE.md 3.1.
        """
        return self.power is not None

    @property
    def available(self) -> bool:
        """True when initialised and the device is currently reachable."""
        return self.is_ready and self._reachable

    def set_reachability_client(self, client) -> None:
        """Attach the HTTP client used by the fallback poll to verify reachability."""
        self._reachability_client = client

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
            _LOGGER.debug("[%s] Radio already playing on startup – starting ICY fetch for %s", self._host, url)
            self._icy_fetcher.start(url)

    def handle_packet(self, fields: dict) -> None:
        """Process a parsed UDP packet and update state.

        Called by the listener for every non-NOTIFICATION packet.
        """
        if fields.get("RESPONSE") == "NACK":
            _LOGGER.debug(
                "[%s] Received NACK for command '%s', ignoring",
                self._host,
                fields.get("_parameter", "?"),
            )
            return

        # Any packet means the device is alive – recover from 'unavailable'.
        self._mark_reachable()

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
                _LOGGER.warning("[%s] Invalid VOLUME_SET value: %s", self._host, fields["VOLUME_SET"])

        # --- Playing mode: station ---
        playing = fields.get("PLAYING")
        if playing == "STATION":
            try:
                sid = int(fields.get("ID", 0))
                name = fields.get("NAME", "")
                if (
                    self.station_id != sid
                    or self.station_name != name
                    or self.input_source is not None
                ):
                    self.input_source = None
                    self.station_id = sid
                    self.station_name = name
                    self.media_image_url = None  # clear immediately; callback follows
                    changed = True
                    self._schedule_artwork_lookup()  # Tier 2 trigger
            except (ValueError, TypeError):
                _LOGGER.warning("[%s] Invalid station ID: %s", self._host, fields.get("ID"))

        # --- Playing mode: input source (UPnP / AUX) ---
        # Device reports "PLAYING:UPNP" and "PLAYING:AUX_IDCOCK" / "AUX/IDOCK".
        elif playing == "UPNP" and self.input_source != "UPnP":
            self._enter_input_source("UPnP")
            changed = True
        elif playing and playing.startswith("AUX") and self.input_source != "AUX":
            self._enter_input_source("AUX")
            changed = True

        if playing is not None or "MODE" in fields:
            self._playing_mode_known = True

        # --- Playing mode: stopped ---
        if fields.get("MODE") == "PLAYING STOPPED":
            if (
                self.station_id is not None
                or self.station_name is not None
                or self.input_source is not None
            ):
                self.input_source = None
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
            self.mac_address = fields.get("MAC")
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
            _LOGGER.debug("[%s] Title update: '%s' → '%s'", self._host, self.media_title, title)
            self.media_title = title
            self._notify_callbacks()
            self._schedule_artwork_lookup()  # Tier 1 if "Artist - Title", else Tier 2 logo

    def set_media_image(self, url: str | None) -> None:
        """Update artwork URL and notify callbacks if changed."""
        if self.media_image_url != url:
            _LOGGER.debug("[%s] Artwork URL: %s", self._host, url or "cleared")
            self.media_image_url = url
            self._notify_callbacks()

    def handle_notification(self, event: str) -> None:
        """React to a raw NOTIFICATION event forwarded by the UDP listener."""
        _LOGGER.debug("[%s] Coordinator handling notification: %s", self._host, event)
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

    def _enter_input_source(self, name: str) -> None:
        """Switch to a non-station source (UPnP/AUX): clear station + now-playing, stop ICY."""
        _LOGGER.debug("[%s] Input source: %s", self._host, name)
        self.input_source = name
        self.station_id = None
        self.station_name = None
        self.media_title = None
        self.media_image_url = None
        if self._icy_fetcher is not None:
            self._icy_fetcher.stop()
        self.stop_artwork()

    def _on_station_changed(self) -> None:
        """Station is changing – stop ICY fetch, cancel artwork, clear stale title."""
        _LOGGER.debug("[%s] Station changed: stopping ICY, clearing title + artwork", self._host)
        if self._icy_fetcher is not None:
            self._icy_fetcher.stop()
        self.stop_artwork()
        self.media_image_url = None  # cleared; set_media_title(None) triggers callback
        self.set_media_title(None)

    def _on_url_is_playing(self) -> None:
        """Stream is stable – start ICY fetch for the current station."""
        url = self._get_current_stream_url()
        if url and self._icy_fetcher is not None:
            _LOGGER.debug("[%s] URL is playing: starting ICY fetch for %s", self._host, url)
            self._icy_fetcher.start(url)

    def _on_power_off(self) -> None:
        """Device switched off – stop ICY fetch, cancel artwork, clear title."""
        _LOGGER.debug("[%s] Power off: stopping ICY, clearing state", self._host)
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
        _LOGGER.debug(
            "[%s] Artwork lookup scheduled (gen=%d, title='%s')",
            self._host, self._artwork_generation, self.media_title,
        )
        self._artwork_task = self._hass.async_create_task(
            self._async_artwork_lookup(self._artwork_generation)
        )

    async def _async_artwork_lookup(self, generation: int) -> None:
        """Fetch artwork (Tier 1 then Tier 2) and update media_image_url."""
        try:
            url: str | None = None
            title = self.media_title

            # Tier 1: music artwork when exactly one known separator is present
            # Supported: "Artist - Title"  or  "Title / Artist" (not both)
            has_dash = bool(title and " - " in title)
            has_slash = bool(title and " / " in title)

            if has_dash and not has_slash:
                artist, _, song = title.partition(" - ")
                artist, song = artist.strip(), song.strip()
            elif has_slash and not has_dash:
                raw_song, _, raw_artist = title.partition(" / ")
                song, artist = raw_song.strip(), raw_artist.strip()
            else:
                artist = song = None

            if artist and song:
                _LOGGER.debug(
                    "[%s] Artwork Tier 1: looking up '%s' by '%s'",
                    self._host, song, artist,
                )
                url = await self._artwork_client.fetch_music_artwork(artist, song)
                if url is None:
                    _LOGGER.debug(
                        "[%s] Artwork Tier 1: no result, falling back to station logo",
                        self._host,
                    )
            else:
                _LOGGER.debug(
                    "[%s] Artwork: no unambiguous separator in '%s', using station logo",
                    self._host, title,
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

    # ------------------------------------------------------------------
    # Startup queries
    # ------------------------------------------------------------------

    async def _send_paced(self, parameters: list[str]) -> None:
        """Send GET queries one at a time, QUERY_SPACING apart.

        Sending them back to back loses all but the first — see
        async_run_startup_queries().
        """
        for index, parameter in enumerate(parameters):
            if index:
                await asyncio.sleep(QUERY_SPACING)
            await self._client.send_get(parameter)

    def _pending_startup_queries(self) -> list[str]:
        """Return the startup queries whose answer has not arrived yet."""
        pending = []
        if self.serial_number is None:
            pending.append("INFO_BLOCK")
        if not self.station_list:
            pending.append("ALL_STATION_INFO")
        if self.power is None:
            pending.append("POWER_STATUS")
        if self.volume is None:
            pending.append("VOLUME")
        if not self._playing_mode_known:
            pending.append("PLAYING_MODE")
        return pending

    async def async_run_startup_queries(self) -> None:
        """Ask the device for its initial state, pacing and repeating requests.

        The radio answers only the first query of a burst and silently drops
        the rest; UDP has no retransmission, so a dropped query is lost for
        good.  Until both power and volume have arrived the coordinator is not
        ready and every entity stays unavailable, so the queries are spaced out
        and whatever is still missing is asked again a few times.  Anything
        still unanswered after that is left to the fallback poll.
        """
        for attempt, delay in enumerate((0, *STARTUP_RETRY_DELAYS)):
            if delay:
                await asyncio.sleep(delay)

            pending = self._pending_startup_queries()
            if not pending:
                if attempt:
                    _LOGGER.debug(
                        "[%s] Startup state complete after pass %d",
                        self._host,
                        attempt,
                    )
                return

            _LOGGER.debug(
                "[%s] Startup queries, pass %d: %s",
                self._host,
                attempt + 1,
                ", ".join(pending),
            )
            await self._send_paced(pending)

        _LOGGER.debug(
            "[%s] Startup queries exhausted, still missing: %s",
            self._host,
            ", ".join(self._pending_startup_queries()) or "nothing",
        )

    # ------------------------------------------------------------------
    # Reachability
    # ------------------------------------------------------------------

    def _mark_reachable(self) -> None:
        """Recover from 'unavailable': mark reachable, notify, resume ICY."""
        if self._reachable:
            return
        _LOGGER.debug("[%s] Device reachable again", self._host)
        self._reachable = True
        self._notify_callbacks()
        self.start_icy_if_playing()

    def _set_unavailable(self) -> None:
        """Device stopped answering: mark unavailable, stop ICY/artwork, clear now-playing."""
        if not self._reachable:
            return
        _LOGGER.debug("[%s] Device unreachable – marking unavailable", self._host)
        self._reachable = False
        if self._icy_fetcher is not None:
            self._icy_fetcher.stop()
        self.stop_artwork()
        self.media_title = None
        self.media_image_url = None
        self._notify_callbacks()

    async def _async_poll(self, _now=None) -> None:
        """Periodic fallback poll: verify reachability, then refresh state.

        An HTTP request confirms the device is reachable (UDP is fire-and-forget
        and cannot). On failure the device is marked unavailable; on success the
        usual UDP status queries run.
        """
        if self._reachability_client is not None:
            if not await self._reachability_client.async_is_reachable():
                _LOGGER.debug("[%s] Fallback poll: device not reachable", self._host)
                self._set_unavailable()
                return
            self._mark_reachable()

        _LOGGER.debug("[%s] Fallback poll: refreshing device state", self._host)
        await self._send_paced(["POWER_STATUS", "VOLUME", "PLAYING_MODE"])
