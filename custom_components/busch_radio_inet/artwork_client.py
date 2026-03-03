"""Artwork lookup client for Busch-Radio iNet.

Two-tier strategy, no API keys required:

Tier 1 – Music artwork (when ICY metadata contains "Artist - Title"):
  1. iTunes Search API  (primary, fast, broad mainstream coverage)
  2. MusicBrainz + Cover Art Archive  (fallback, CC0, strong for classical/niche)

Tier 2 – Station logo (always as final fallback):
  1. radio-browser.info URL lookup  (exact stream URL match)
  2. radio-browser.info name lookup  (fuzzy, sorted by popularity)

Results are cached in-memory for the lifetime of the HA session.
MusicBrainz rate-limit (1 req/s) is enforced via a module-level timestamp
shared across all ArtworkClient instances (all radios in the same HA process).
"""

import asyncio
import logging
import time
from urllib.parse import quote as urlquote

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

# MusicBrainz rate-limit: shared across all instances / all radios
_mb_last_request: float = 0.0
_MB_MIN_INTERVAL: float = 1.5  # seconds between MB requests (limit is 1/s, we use 1.5s buffer)

_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=8)


class ArtworkClient:
    """Fetches album artwork and station logos from public, key-free APIs."""

    def __init__(self, hass: HomeAssistant, version: str) -> None:
        self._hass = hass
        self._user_agent = f"busch-radio-inet-ha/{version} (home-assistant-integration)"
        self._music_cache: dict[str, str | None] = {}  # "artist|title" → url or None
        self._logo_cache: dict[str, str | None] = {}   # stream_url or name → url or None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def fetch_music_artwork(self, artist: str, title: str) -> str | None:
        """Return an artwork URL for the given artist/title, or None.

        Tries iTunes first, then MusicBrainz + Cover Art Archive.
        Results (including None) are cached by "artist|title" key.
        """
        cache_key = f"{artist}|{title}"
        if cache_key in self._music_cache:
            return self._music_cache[cache_key]

        url = await self._fetch_itunes(artist, title)

        if url is None:
            url = await self._fetch_musicbrainz(artist, title)

        self._music_cache[cache_key] = url
        _LOGGER.debug(
            "Music artwork for '%s – %s': %s",
            artist,
            title,
            url or "not found",
        )
        return url

    async def fetch_station_logo(
        self, stream_url: str | None, station_name: str
    ) -> str | None:
        """Return a logo URL for the given station, or None.

        Tries radio-browser.info URL lookup first, then name lookup.
        Results (including None) are cached by stream_url (or station_name as fallback).
        """
        cache_key = stream_url or station_name
        if not cache_key:
            return None
        if cache_key in self._logo_cache:
            return self._logo_cache[cache_key]

        url: str | None = None

        if stream_url:
            url = await self._fetch_radiobrowser_by_url(stream_url)

        if url is None and station_name:
            url = await self._fetch_radiobrowser_by_name(station_name)

        self._logo_cache[cache_key] = url
        _LOGGER.debug(
            "Station logo for '%s': %s",
            station_name or stream_url,
            url or "not found",
        )
        return url

    # ------------------------------------------------------------------
    # Tier 1 – iTunes
    # ------------------------------------------------------------------

    async def _fetch_itunes(self, artist: str, title: str) -> str | None:
        """Query iTunes Search API for album artwork."""
        try:
            session = async_get_clientsession(self._hass)
            term = urlquote(f"{artist} {title}")
            url = f"https://itunes.apple.com/search?term={term}&entity=song&limit=5"
            async with session.get(url, timeout=_REQUEST_TIMEOUT) as response:
                if response.status != 200:
                    return None
                data = await response.json(content_type=None)
            results = data.get("results", [])
            for item in results:
                artwork = item.get("artworkUrl100", "")
                if artwork:
                    # Replace 100x100 thumbnail with 600x600 version
                    return artwork.replace("100x100bb", "600x600bb")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _LOGGER.debug("iTunes lookup failed for '%s – %s': %s", artist, title, exc)
        return None

    # ------------------------------------------------------------------
    # Tier 1 – MusicBrainz + Cover Art Archive (fallback)
    # ------------------------------------------------------------------

    async def _fetch_musicbrainz(self, artist: str, title: str) -> str | None:
        """Query MusicBrainz for a release, then fetch artwork from Cover Art Archive."""
        try:
            session = async_get_clientsession(self._hass)

            # Step 1: find a recording with a linked release
            mb_url = (
                "https://musicbrainz.org/ws/2/recording/"
                f"?query=artist:{urlquote(artist)}+recording:{urlquote(title)}"
                "&fmt=json&limit=1"
            )
            response = await self._mb_throttled_get(session, mb_url)
            if response.status != 200:
                return None
            data = await response.json(content_type=None)

            recordings = data.get("recordings", [])
            if not recordings:
                return None
            releases = recordings[0].get("releases", [])
            if not releases:
                return None
            release_id = releases[0].get("id")
            if not release_id:
                return None

            # Step 2: Cover Art Archive – follow redirect to get the image URL
            caa_url = f"https://coverartarchive.org/release/{release_id}/front"
            async with session.get(
                caa_url,
                headers={"User-Agent": self._user_agent},
                timeout=_REQUEST_TIMEOUT,
                allow_redirects=False,
            ) as caa_response:
                if caa_response.status in (301, 302, 307, 308):
                    location = caa_response.headers.get("Location")
                    if location:
                        return location
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _LOGGER.debug(
                "MusicBrainz/CAA lookup failed for '%s – %s': %s", artist, title, exc
            )
        return None

    async def _mb_throttled_get(self, session, url: str):
        """Rate-limited GET for MusicBrainz (max 1 req/1.5s, shared across all instances)."""
        global _mb_last_request
        wait = _MB_MIN_INTERVAL - (time.monotonic() - _mb_last_request)
        if wait > 0:
            # Cooperative sleep – asyncio.CancelledError propagates here if task is cancelled
            await asyncio.sleep(wait)
        _mb_last_request = time.monotonic()
        return await session.get(
            url,
            headers={"User-Agent": self._user_agent},
            timeout=_REQUEST_TIMEOUT,
        )

    # ------------------------------------------------------------------
    # Tier 2 – radio-browser.info
    # ------------------------------------------------------------------

    async def _fetch_radiobrowser_by_url(self, stream_url: str) -> str | None:
        """Look up station favicon by exact stream URL."""
        try:
            session = async_get_clientsession(self._hass)
            api_url = (
                "https://de1.api.radio-browser.info/json/stations/byurl"
                f"?url={urlquote(stream_url)}"
            )
            async with session.get(
                api_url,
                headers={"User-Agent": self._user_agent},
                timeout=_REQUEST_TIMEOUT,
            ) as response:
                if response.status != 200:
                    return None
                stations = await response.json(content_type=None)
            for station in stations:
                favicon = station.get("favicon", "").strip()
                if favicon:
                    return favicon
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _LOGGER.debug("radio-browser URL lookup failed for %s: %s", stream_url, exc)
        return None

    async def _fetch_radiobrowser_by_name(self, station_name: str) -> str | None:
        """Look up station favicon by name (no country filter, sorted by votes)."""
        try:
            session = async_get_clientsession(self._hass)
            api_url = (
                "https://de1.api.radio-browser.info/json/stations/search"
                f"?name={urlquote(station_name)}"
                "&hidebroken=true&order=votes&reverse=true&limit=1"
            )
            async with session.get(
                api_url,
                headers={"User-Agent": self._user_agent},
                timeout=_REQUEST_TIMEOUT,
            ) as response:
                if response.status != 200:
                    return None
                stations = await response.json(content_type=None)
            for station in stations:
                favicon = station.get("favicon", "").strip()
                if favicon:
                    return favicon
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _LOGGER.debug(
                "radio-browser name lookup failed for '%s': %s", station_name, exc
            )
        return None
