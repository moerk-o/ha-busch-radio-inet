"""Tests for IcyClient, IcyIntervalScheduler, IcyPersistentConnection."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from custom_components.busch_radio_inet.icy_client import (
    IcyClient,
    IcyIntervalScheduler,
    IcyPersistentConnection,
    _parse_stream_title,
)


# ===========================================================================
# _parse_stream_title
# ===========================================================================


def test_parse_stream_title_basic():
    assert _parse_stream_title("StreamTitle='Artist - Song';") == "Artist - Song"


def test_parse_stream_title_with_stream_url():
    meta = "StreamTitle='NDR - Morgenshow';StreamUrl='http://example.com';"
    assert _parse_stream_title(meta) == "NDR - Morgenshow"


def test_parse_stream_title_empty_title_returns_none():
    assert _parse_stream_title("StreamTitle='';") is None


def test_parse_stream_title_no_stream_title_returns_none():
    assert _parse_stream_title("StreamUrl='http://example.com';") is None


def test_parse_stream_title_strips_single_quotes():
    assert _parse_stream_title("StreamTitle='Hello World';") == "Hello World"


def test_parse_stream_title_empty_meta():
    assert _parse_stream_title("") is None


def test_parse_stream_title_multipart_preserves_title():
    meta = "StreamTitle='A - B - C';"
    assert _parse_stream_title(meta) == "A - B - C"


# ===========================================================================
# IcyClient.fetch_title
# ===========================================================================


def _make_stream_reader(audio_bytes: bytes, meta_bytes: bytes) -> MagicMock:
    """Build a mock aiohttp.StreamReader with readexactly side effects."""
    reader = MagicMock()
    calls = [audio_bytes, meta_bytes[:1], meta_bytes[1:]]
    reader.readexactly = AsyncMock(side_effect=calls)
    return reader


@pytest.mark.asyncio
async def test_fetch_title_success():
    hass = MagicMock()
    client = IcyClient(hass)

    title_bytes = b"StreamTitle='Artist - Song';" + b"\x00" * 2
    # length = ceil(len / 16) = 2 blocks = 32 bytes
    meta_length = 2  # 2 * 16 = 32 bytes
    meta_content = (b"StreamTitle='Artist - Song';" + b"\x00" * (meta_length * 16 - len(b"StreamTitle='Artist - Song';")))

    mock_stream = MagicMock()
    mock_stream.readexactly = AsyncMock(side_effect=[
        b"\x00" * 8192,           # skip metaint audio bytes
        bytes([meta_length]),     # length byte
        meta_content,             # metadata
    ])

    mock_resp = MagicMock()
    mock_resp.headers = {"icy-metaint": "8192"}
    mock_resp.content = mock_stream

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=mock_resp),
        __aexit__=AsyncMock(return_value=False),
    ))

    with patch(
        "custom_components.busch_radio_inet.icy_client.async_get_clientsession",
        return_value=mock_session,
    ):
        result = await client.fetch_title("http://stream.example.com")

    assert result == "Artist - Song"


@pytest.mark.asyncio
async def test_fetch_title_no_icy_metaint_header():
    hass = MagicMock()
    client = IcyClient(hass)

    mock_resp = MagicMock()
    mock_resp.headers = {}  # No icy-metaint
    mock_resp.content = MagicMock()

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=mock_resp),
        __aexit__=AsyncMock(return_value=False),
    ))

    with patch(
        "custom_components.busch_radio_inet.icy_client.async_get_clientsession",
        return_value=mock_session,
    ):
        result = await client.fetch_title("http://stream.example.com")

    assert result is None


@pytest.mark.asyncio
async def test_fetch_title_zero_meta_length_returns_none():
    hass = MagicMock()
    client = IcyClient(hass)

    mock_stream = MagicMock()
    mock_stream.readexactly = AsyncMock(side_effect=[
        b"\x00" * 4096,  # audio skip
        bytes([0]),       # length byte = 0 → no metadata
    ])

    mock_resp = MagicMock()
    mock_resp.headers = {"icy-metaint": "4096"}
    mock_resp.content = mock_stream

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=mock_resp),
        __aexit__=AsyncMock(return_value=False),
    ))

    with patch(
        "custom_components.busch_radio_inet.icy_client.async_get_clientsession",
        return_value=mock_session,
    ):
        result = await client.fetch_title("http://stream.example.com")

    assert result is None


@pytest.mark.asyncio
async def test_fetch_title_connection_error_returns_none():
    hass = MagicMock()
    client = IcyClient(hass)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(side_effect=Exception("connection refused")),
        __aexit__=AsyncMock(return_value=False),
    ))

    with patch(
        "custom_components.busch_radio_inet.icy_client.async_get_clientsession",
        return_value=mock_session,
    ):
        result = await client.fetch_title("http://stream.example.com")

    assert result is None


@pytest.mark.asyncio
async def test_fetch_title_timeout_returns_none():
    hass = MagicMock()
    client = IcyClient(hass)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(side_effect=asyncio.TimeoutError()),
        __aexit__=AsyncMock(return_value=False),
    ))

    with patch(
        "custom_components.busch_radio_inet.icy_client.async_get_clientsession",
        return_value=mock_session,
    ):
        result = await client.fetch_title("http://stream.example.com")

    assert result is None


# ===========================================================================
# IcyIntervalScheduler
# ===========================================================================


def make_scheduler(interval=60):
    hass = MagicMock()
    hass.loop = MagicMock()
    hass.loop.create_task = MagicMock(return_value=MagicMock(done=MagicMock(return_value=True)))
    fetcher = MagicMock()
    fetcher.fetch_title = AsyncMock(return_value="Artist - Song")
    on_title = MagicMock()
    scheduler = IcyIntervalScheduler(hass, fetcher, on_title, interval)
    return scheduler, hass, fetcher, on_title


def test_start_creates_fetch_task():
    scheduler, hass, _, _ = make_scheduler()
    cancel_fn = MagicMock()
    with patch(
        "custom_components.busch_radio_inet.icy_client.async_track_time_interval",
        return_value=cancel_fn,
    ):
        scheduler.start("http://stream.example.com")
    hass.loop.create_task.assert_called_once()


def test_start_registers_timer():
    scheduler, _, _, _ = make_scheduler()
    cancel_fn = MagicMock()
    with patch(
        "custom_components.busch_radio_inet.icy_client.async_track_time_interval",
        return_value=cancel_fn,
    ) as mock_track:
        scheduler.start("http://stream.example.com")
    mock_track.assert_called_once()


def test_stop_cancels_timer():
    scheduler, _, _, _ = make_scheduler()
    cancel_fn = MagicMock()
    with patch(
        "custom_components.busch_radio_inet.icy_client.async_track_time_interval",
        return_value=cancel_fn,
    ):
        scheduler.start("http://stream.example.com")
        scheduler.stop()
    cancel_fn.assert_called_once()


def test_stop_before_start_is_safe():
    scheduler, _, _, _ = make_scheduler()
    scheduler.stop()  # Must not raise


def test_start_twice_cancels_previous():
    scheduler, hass, _, _ = make_scheduler()
    cancel_fn1 = MagicMock()
    cancel_fn2 = MagicMock()
    with patch(
        "custom_components.busch_radio_inet.icy_client.async_track_time_interval",
        side_effect=[cancel_fn1, cancel_fn2],
    ):
        scheduler.start("http://stream1.example.com")
        scheduler.start("http://stream2.example.com")
    cancel_fn1.assert_called_once()


@pytest.mark.asyncio
async def test_do_fetch_calls_on_title():
    scheduler, _, fetcher, on_title = make_scheduler()
    fetcher.fetch_title.return_value = "NDR - Morning"
    scheduler._url = "http://stream.example.com"
    await scheduler._do_fetch()
    on_title.assert_called_once_with("NDR - Morning")


@pytest.mark.asyncio
async def test_do_fetch_no_url_does_nothing():
    scheduler, _, fetcher, on_title = make_scheduler()
    scheduler._url = None
    await scheduler._do_fetch()
    fetcher.fetch_title.assert_not_awaited()
    on_title.assert_not_called()


@pytest.mark.asyncio
async def test_interval_fetch_skips_if_task_running():
    scheduler, hass, _, _ = make_scheduler()
    # Simulate a running task
    running_task = MagicMock()
    running_task.done.return_value = False
    scheduler._fetch_task = running_task
    await scheduler._async_interval_fetch()
    # create_task should NOT be called since existing task is still running
    hass.loop.create_task.assert_not_called()


# ===========================================================================
# IcyPersistentConnection
# ===========================================================================


def make_persistent():
    hass = MagicMock()
    hass.loop = MagicMock()
    hass.loop.create_task = MagicMock(return_value=MagicMock(done=MagicMock(return_value=True)))
    on_title = MagicMock()
    conn = IcyPersistentConnection(hass, on_title)
    return conn, hass, on_title


def test_start_creates_task():
    conn, hass, _ = make_persistent()
    conn.start("http://stream.example.com")
    hass.loop.create_task.assert_called_once()


def test_stop_cancels_task():
    conn, hass, _ = make_persistent()
    mock_task = MagicMock()
    mock_task.done.return_value = False
    hass.loop.create_task.return_value = mock_task
    conn.start("http://stream.example.com")
    conn.stop()
    mock_task.cancel.assert_called_once()


def test_stop_clears_current_title():
    conn, _, _ = make_persistent()
    conn._current_title = "Some Title"
    conn.stop()
    assert conn._current_title is None


def test_stop_before_start_is_safe():
    conn, _, _ = make_persistent()
    conn.stop()  # Must not raise


def test_start_twice_cancels_previous():
    conn, hass, _ = make_persistent()
    task1 = MagicMock()
    task1.done.return_value = False
    task2 = MagicMock()
    task2.done.return_value = True
    hass.loop.create_task.side_effect = [task1, task2]
    conn.start("http://stream1.example.com")
    conn.start("http://stream2.example.com")
    task1.cancel.assert_called_once()


@pytest.mark.asyncio
async def test_run_no_metaint_calls_on_title_none():
    conn, _, on_title = make_persistent()

    mock_resp = MagicMock()
    mock_resp.headers = {}  # No icy-metaint

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=mock_resp),
        __aexit__=AsyncMock(return_value=False),
    ))

    with patch(
        "custom_components.busch_radio_inet.icy_client.async_get_clientsession",
        return_value=mock_session,
    ):
        await conn._run("http://stream.example.com")

    on_title.assert_called_once_with(None)


@pytest.mark.asyncio
async def test_run_exception_calls_on_title_none():
    conn, _, on_title = make_persistent()

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(side_effect=Exception("connection failed")),
        __aexit__=AsyncMock(return_value=False),
    ))

    with patch(
        "custom_components.busch_radio_inet.icy_client.async_get_clientsession",
        return_value=mock_session,
    ):
        await conn._run("http://stream.example.com")

    on_title.assert_called_once_with(None)


@pytest.mark.asyncio
async def test_run_cancelled_error_silent():
    """CancelledError from stop() must not call on_title."""
    conn, _, on_title = make_persistent()

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(side_effect=asyncio.CancelledError()),
        __aexit__=AsyncMock(return_value=False),
    ))

    with patch(
        "custom_components.busch_radio_inet.icy_client.async_get_clientsession",
        return_value=mock_session,
    ):
        await conn._run("http://stream.example.com")

    on_title.assert_not_called()


@pytest.mark.asyncio
async def test_read_loop_notifies_on_title_change():
    """_read_loop calls on_title when StreamTitle changes."""
    conn, _, on_title = make_persistent()

    metaint = 16
    meta_text1 = b"StreamTitle='Track 1';" + b"\x00" * (16 - len(b"StreamTitle='Track 1';"))
    meta_text2 = b"StreamTitle='Track 2';" + b"\x00" * (16 - len(b"StreamTitle='Track 2';"))

    stream = MagicMock()
    # First block: audio + meta with Track 1
    # Second block: audio + meta with Track 2
    # Third block: raise to break loop
    stream.readexactly = AsyncMock(side_effect=[
        b"\x00" * metaint,        # audio skip 1
        bytes([1]),                # meta length (1 * 16 = 16 bytes)
        meta_text1,                # meta content
        b"\x00" * metaint,        # audio skip 2
        bytes([1]),                # meta length
        meta_text2,                # meta content
        Exception("end of stream"),  # break loop
    ])

    with pytest.raises(Exception, match="end of stream"):
        await conn._read_loop(stream, metaint)

    assert on_title.call_count == 2
    calls = [c[0][0] for c in on_title.call_args_list]
    assert calls[0] == "Track 1"
    assert calls[1] == "Track 2"


@pytest.mark.asyncio
async def test_read_loop_no_callback_for_same_title():
    """_read_loop does NOT call on_title if title hasn't changed."""
    conn, _, on_title = make_persistent()

    metaint = 16
    meta_text = b"StreamTitle='Same Track';" + b"\x00" * (16 - len(b"StreamTitle='Same Track';"))

    stream = MagicMock()
    stream.readexactly = AsyncMock(side_effect=[
        b"\x00" * metaint,
        bytes([1]),
        meta_text,
        b"\x00" * metaint,
        bytes([1]),
        meta_text,
        Exception("stop"),
    ])

    with pytest.raises(Exception, match="stop"):
        await conn._read_loop(stream, metaint)

    on_title.assert_called_once_with("Same Track")
