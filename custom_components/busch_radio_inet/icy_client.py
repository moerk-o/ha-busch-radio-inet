"""ICY stream metadata client for Busch-Radio iNet.

Two fetch strategies are provided:

Mode A – IcyIntervalScheduler (interval-based):
  Connects briefly every N seconds, reads the first metadata block, disconnects.

Mode B – IcyPersistentConnection (persistent/live):
  Holds the HTTP connection open permanently, monitors every metadata block,
  and notifies immediately when StreamTitle changes.

Both implement the IcyFetcher protocol (start/stop interface).
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import timedelta
from typing import Protocol

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval

_LOGGER = logging.getLogger(__name__)

_ICY_CONNECT_TIMEOUT = 10  # seconds


class IcyFetcher(Protocol):
    """Common interface for ICY fetch strategies (Mode A and B)."""

    def start(self, url: str) -> None:
        """Start fetching metadata from the given stream URL."""
        ...

    def stop(self) -> None:
        """Stop fetching and cancel any running timer or connection."""
        ...


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

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    async def fetch_title(self, url: str) -> str | None:
        """Connect to the stream, read the first ICY metadata block, disconnect.

        Returns the StreamTitle string, or None if ICY is not supported or
        on any connection/timeout error.
        """
        try:
            timeout = aiohttp.ClientTimeout(total=_ICY_CONNECT_TIMEOUT)
            session = async_get_clientsession(self._hass)
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


class IcyPersistentConnection:
    """Mode B: holds the stream connection open and monitors every metadata block.

    Notifies via on_title() immediately when StreamTitle changes.
    Network usage: ~16 KB/s per stream (128 kbps). CPU: minimal (asyncio).

    On stream disconnect or error: notifies with None and waits for the next
    start() call (triggered by the next URL_IS_PLAYING notification).
    """

    def __init__(
        self,
        hass: HomeAssistant,
        on_title: Callable[[str | None], None],
    ) -> None:
        self._hass = hass
        self._on_title = on_title
        self._task: asyncio.Task | None = None
        self._current_title: str | None = None

    def start(self, url: str) -> None:
        """Cancel any running connection and open a new one to the given URL."""
        self.stop()
        self._current_title = None
        self._task = self._hass.loop.create_task(self._run(url))

    def stop(self) -> None:
        """Cancel the streaming task (closes the HTTP connection)."""
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        self._current_title = None

    async def _run(self, url: str) -> None:
        """Main stream loop: connect, read audio/metadata until cancelled."""
        try:
            session = async_get_clientsession(self._hass)
            async with session.get(
                url,
                headers={"Icy-MetaData": "1"},
                timeout=aiohttp.ClientTimeout(connect=_ICY_CONNECT_TIMEOUT),
            ) as response:
                    metaint_str = response.headers.get("icy-metaint")
                    if not metaint_str:
                        _LOGGER.debug(
                            "Stream %s does not support ICY metadata", url
                        )
                        self._on_title(None)
                        return
                    metaint = int(metaint_str)
                    await self._read_loop(response.content, metaint)
        except asyncio.CancelledError:
            pass  # Normal path: stop() was called
        except Exception as exc:
            _LOGGER.warning("ICY persistent connection failed: %s", exc)
            self._on_title(None)
            # No automatic retry – next URL_IS_PLAYING event will call start()

    async def _read_loop(
        self, stream: aiohttp.StreamReader, metaint: int
    ) -> None:
        """Continuously read audio bytes and check every metadata block."""
        while True:
            await stream.readexactly(metaint)
            length_byte = await stream.readexactly(1)
            meta_length = length_byte[0] * 16
            if meta_length > 0:
                meta_bytes = await stream.readexactly(meta_length)
                meta_text = meta_bytes.decode("utf-8", errors="replace")
                title = _parse_stream_title(meta_text)
                if title != self._current_title:
                    self._current_title = title
                    self._on_title(title)
