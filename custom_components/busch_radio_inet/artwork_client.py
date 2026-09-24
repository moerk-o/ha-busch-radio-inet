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
import unicodedata
from urllib.parse import quote as urlquote

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

# MusicBrainz rate-limit: shared across all instances / all radios
_mb_last_request: float = 0.0
_MB_MIN_INTERVAL: float = 1.5  # seconds between MB requests (limit is 1/s, we use 1.5s buffer)

_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=8)


# Shortest artist name that may be accepted as a substring of the other side.
# Below this, an accidental overlap is more likely than a real match, so only an
# exact match counts — which keeps short real names like "U2" or "AIR" working.
_MIN_SUBSTRING_LENGTH = 4


def _normalize(text: str) -> str:
    """Reduce a name to comparable characters.

    Case, accents, spacing and punctuation differ constantly between what a
    station announces and what a music database stores ("JAY-Z" / "Jay Z",
    "Beyoncé" / "Beyonce"), and none of those differences mean anything.
    """
    decomposed = unicodedata.normalize("NFKD", text).casefold()
    return "".join(c for c in decomposed if c.isalnum())


def artist_matches(wanted: str, found: str) -> bool:
    """Return True if a lookup result plausibly belongs to the artist asked for.

    Substring in either direction, because a station may announce more than the
    database credits ("Justin Bieber feat. Ludacris" vs "Justin Bieber") or less
    ("Sting" vs "Sting & Shaggy").

    This is what keeps non-song stream text from producing artwork: a search for
    "traffic info" still returns something with a high relevance score, but the
    credited artist has nothing in common with it (issue #4).
    """
    a, b = _normalize(wanted), _normalize(found)
    if not a or not b:
        return False
    if a == b:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    return len(shorter) >= _MIN_SUBSTRING_LENGTH and shorter in longer


def _credited_artist(recording: dict) -> str:
    """Join a MusicBrainz artist-credit into one comparable string."""
    parts = []
    for credit in recording.get("artist-credit", []):
        if isinstance(credit, dict):
            name = credit.get("name") or credit.get("artist", {}).get("name", "")
            if name:
                parts.append(name)
    return " ".join(parts)


def _best_release_id(releases: list) -> str | None:
    """Return the most suitable release ID from a MusicBrainz releases list.

    Preference: Official Album > any Official release > first release.
    """
    official_album: str | None = None
    official_any: str | None = None

    for release in releases:
        rid = release.get("id")
        if not rid:
            continue
        is_official = release.get("status", "") == "Official"
        primary_type = release.get("release-group", {}).get("primary-type", "")
        if is_official and primary_type == "Album" and official_album is None:
            official_album = rid
        elif is_official and official_any is None:
            official_any = rid

    return official_album or official_any or releases[0].get("id")


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
            _LOGGER.debug("Music artwork cache hit for '%s – %s': %s", artist, title, self._music_cache[cache_key] or "not found")
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
            _LOGGER.debug("Station logo cache hit for '%s': %s", station_name or stream_url, self._logo_cache[cache_key] or "not found")
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
            _LOGGER.debug("iTunes: %d result(s) for artist='%s' title='%s'", len(results), artist, title)
            for item in results:
                item_artist = item.get("artistName", "")
                if not artist_matches(artist, item_artist):
                    _LOGGER.debug("iTunes: skipping artistName='%s' (no match for '%s')", item_artist, artist)
                    continue
                artwork = item.get("artworkUrl100", "")
                if artwork:
                    _LOGGER.debug("iTunes: matched artistName='%s'", item_artist)
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
                "&fmt=json&limit=5"
            )
            response = await self._mb_throttled_get(session, mb_url)
            if response.status != 200:
                return None
            data = await response.json(content_type=None)

            recordings = data.get("recordings", [])
            if not recordings:
                return None

            # The score is a relevance value, not a promise that the result has
            # anything to do with the query — nonsense text scores high too.  So
            # the credited artist has to match as well, and a non-matching top
            # hit must not hide a correct one behind it (issue #4).
            release_id = None
            for recording in recordings:
                score = recording.get("score", 0)
                credited = _credited_artist(recording)
                if score < 85:
                    _LOGGER.debug(
                        "MusicBrainz: skipping '%s' (score %s below threshold 85)",
                        credited, score,
                    )
                    continue
                if not artist_matches(artist, credited):
                    _LOGGER.debug(
                        "MusicBrainz: skipping artist-credit='%s' (no match for '%s')",
                        credited, artist,
                    )
                    continue
                releases = recording.get("releases", [])
                if not releases:
                    continue
                release_id = _best_release_id(releases)
                if release_id:
                    _LOGGER.debug(
                        "MusicBrainz: matched artist-credit='%s' (score %s), "
                        "%d release(s), selected %s",
                        credited, score, len(releases), release_id,
                    )
                    break

            if not release_id:
                _LOGGER.debug(
                    "MusicBrainz: no usable match for '%s – %s' in %d result(s)",
                    artist, title, len(recordings),
                )
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
                        _LOGGER.debug("MusicBrainz/CAA: redirect → %s", location)
                        return location
                    _LOGGER.debug("MusicBrainz/CAA: redirect status %d but no Location header for release %s", caa_response.status, release_id)
                else:
                    _LOGGER.debug("MusicBrainz/CAA: no artwork for release %s (status %d)", release_id, caa_response.status)
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
                    _LOGGER.debug("radio-browser URL lookup: found favicon for %s", stream_url)
                    return favicon
            _LOGGER.debug("radio-browser URL lookup: no favicon found for %s", stream_url)
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
                    _LOGGER.debug("radio-browser name lookup: found favicon for '%s'", station_name)
                    return favicon
            _LOGGER.debug("radio-browser name lookup: no favicon found for '%s'", station_name)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _LOGGER.debug(
                "radio-browser name lookup failed for '%s': %s", station_name, exc
            )
        return None
