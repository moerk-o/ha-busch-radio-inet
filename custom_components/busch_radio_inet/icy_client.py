"""ICY stream metadata client for Busch-Radio iNet – Mode A (interval-based).

Connects briefly to an Icecast/Shoutcast stream, reads the first metadata
block to extract the current StreamTitle, then disconnects.

The IcyIntervalScheduler wraps IcyClient to repeat the fetch automatically
on a configurable interval, triggered by URL_IS_PLAYING notifications.
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import timedelta

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

_LOGGER = logging.getLogger(__name__)

_ICY_CONNECT_TIMEOUT = 10  # seconds


def _parse_stream_title(meta_text: str) -> str | None:
    """Extract StreamTitle value from an ICY metadata string.

    ICY metadata format: 'StreamTitle=Artist - Song;StreamUrl=...;'
    Returns the title string, or None if not found or empty.
    """
    for part in meta_text.split(";"):
        part = part.strip()
        if part.startswith("StreamTitle="):
            title = part[len("StreamTitle="):].strip("'")
            return title or None
    return None


class IcyClient:
    """Fetches a single ICY metadata block from a stream URL.

    Makes a brief HTTP connection with the 'Icy-MetaData: 1' header,
    skips the first audio chunk, reads and parses the metadata block,
    then closes the connection.
    """

    async def fetch_title(self, url: str) -> str | None:
        """Connect to the stream, read the first ICY metadata block, disconnect.

        Returns the StreamTitle string, or None if ICY is not supported or
        on any connection/timeout error.
        """
        try:
            timeout = aiohttp.ClientTimeout(total=_ICY_CONNECT_TIMEOUT)
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers={"Icy-MetaData": "1"},
                    timeout=timeout,
                ) as response:
                    metaint_str = response.headers.get("icy-metaint")
                    if not metaint_str:
                        _LOGGER.debug(
                            "Stream %s does not support ICY metadata", url
                        )
                        return None
                    metaint = int(metaint_str)
                    return await self._read_first_block(response.content, metaint)
        except asyncio.TimeoutError:
            _LOGGER.warning("ICY fetch timed out for %s", url)
            return None
        except Exception as exc:
            _LOGGER.warning("ICY fetch failed for %s: %s", url, exc)
            return None

    async def _read_first_block(
        self, stream: aiohttp.StreamReader, metaint: int
    ) -> str | None:
        """Skip metaint audio bytes, read and parse the first metadata block."""
        await stream.readexactly(metaint)
        length_byte = await stream.readexactly(1)
        meta_length = length_byte[0] * 16
        if meta_length == 0:
            return None
        meta_bytes = await stream.readexactly(meta_length)
        meta_text = meta_bytes.decode("utf-8", errors="replace")
        return _parse_stream_title(meta_text)


class IcyIntervalScheduler:
    """Mode A: fetches ICY metadata on a fixed interval.

    On start(url): fetches immediately, then repeats every interval_seconds.
    On stop(): cancels the timer and any running fetch task.
    Restarting (via a new start() call) cancels the previous cycle first.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        fetcher: IcyClient,
        on_title: Callable[[str | None], None],
        interval_seconds: int = 60,
    ) -> None:
        self._hass = hass
        self._fetcher = fetcher
        self._on_title = on_title
        self._interval = interval_seconds
        self._url: str | None = None
        self._cancel_timer: Callable | None = None
        self._fetch_task: asyncio.Task | None = None

    def start(self, url: str) -> None:
        """Cancel any running cycle, start an immediate fetch, then repeat."""
        self.stop()
        self._url = url
        self._fetch_task = self._hass.loop.create_task(self._do_fetch())
        self._cancel_timer = async_track_time_interval(
            self._hass,
            self._async_interval_fetch,
            timedelta(seconds=self._interval),
        )

    def stop(self) -> None:
        """Cancel the interval timer and any running fetch task."""
        if self._cancel_timer is not None:
            self._cancel_timer()
            self._cancel_timer = None
        if self._fetch_task and not self._fetch_task.done():
            self._fetch_task.cancel()
        self._fetch_task = None
        self._url = None

    async def _async_interval_fetch(self, _now=None) -> None:
        """Timer callback: start a new fetch if no fetch is currently running."""
        if self._fetch_task and not self._fetch_task.done():
            return
        self._fetch_task = self._hass.loop.create_task(self._do_fetch())

    async def _do_fetch(self) -> None:
        if not self._url:
            return
        title = await self._fetcher.fetch_title(self._url)
        self._on_title(title)
