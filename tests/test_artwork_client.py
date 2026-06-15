"""Tests for ArtworkClient (iTunes, MusicBrainz, radio-browser)."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import custom_components.busch_radio_inet.artwork_client as artwork_module
from custom_components.busch_radio_inet.artwork_client import ArtworkClient, _best_release_id


def make_client():
    hass = MagicMock()
    return ArtworkClient(hass, "0.5.1"), hass


def _make_response(status=200, json_data=None):
    resp = AsyncMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data or {})
    resp.headers = {}
    return resp


def _mock_session(*responses):
    """Return a mock session whose get() yields the given responses in order."""
    session = MagicMock()
    session.get = MagicMock(side_effect=[
        AsyncMock(
            __aenter__=AsyncMock(return_value=r),
            __aexit__=AsyncMock(return_value=False),
        )
        for r in responses
    ])
    return session


# ===========================================================================
# fetch_music_artwork – iTunes hit
# ===========================================================================


@pytest.mark.asyncio
async def test_fetch_music_artwork_itunes_hit():
    client, _ = make_client()
    itunes_data = {
        "results": [{"artistName": "Artist", "artworkUrl100": "https://example.com/100x100bb.jpg"}]
    }
    session = _mock_session(_make_response(200, itunes_data))
    with patch(
        "custom_components.busch_radio_inet.artwork_client.async_get_clientsession",
        return_value=session,
    ):
        result = await client.fetch_music_artwork("Artist", "Song")
    assert result == "https://example.com/600x600bb.jpg"


@pytest.mark.asyncio
async def test_fetch_music_artwork_itunes_replaces_thumbnail_size():
    client, _ = make_client()
    itunes_data = {
        "results": [{"artistName": "A", "artworkUrl100": "https://mzstatic.com/image/100x100bb/cover.jpg"}]
    }
    session = _mock_session(_make_response(200, itunes_data))
    with patch(
        "custom_components.busch_radio_inet.artwork_client.async_get_clientsession",
        return_value=session,
    ):
        result = await client.fetch_music_artwork("A", "B")
    assert "600x600bb" in result


@pytest.mark.asyncio
async def test_fetch_music_artwork_itunes_empty_results():
    """iTunes returns empty → falls back to MusicBrainz → returns None."""
    client, _ = make_client()
    itunes_data = {"results": []}
    session_itunes = _make_response(200, itunes_data)

    # MusicBrainz returns no recordings
    mb_data = {"recordings": []}
    session_mb = _make_response(200, mb_data)

    session = _mock_session(session_itunes, session_mb)
    with patch(
        "custom_components.busch_radio_inet.artwork_client.async_get_clientsession",
        return_value=session,
    ), patch.object(
        artwork_module, "_mb_last_request", 0.0
    ), patch(
        "custom_components.busch_radio_inet.artwork_client.asyncio.sleep",
        new_callable=AsyncMock,
    ):
        result = await client.fetch_music_artwork("Unknown", "Track")
    assert result is None


@pytest.mark.asyncio
async def test_fetch_music_artwork_itunes_non_200():
    """iTunes HTTP error → falls back to MusicBrainz → None (no recordings)."""
    client, _ = make_client()
    itunes_resp = _make_response(500)
    mb_resp = _make_response(200, {"recordings": []})

    session = _mock_session(itunes_resp, mb_resp)
    with patch(
        "custom_components.busch_radio_inet.artwork_client.async_get_clientsession",
        return_value=session,
    ), patch(
        "custom_components.busch_radio_inet.artwork_client.asyncio.sleep",
        new_callable=AsyncMock,
    ):
        result = await client.fetch_music_artwork("A", "B")
    assert result is None


@pytest.mark.asyncio
async def test_fetch_music_artwork_cached():
    client, _ = make_client()
    client._music_cache["Artist|Song"] = "https://cached.example.com/art.jpg"
    # Should return immediately without any HTTP call
    result = await client.fetch_music_artwork("Artist", "Song")
    assert result == "https://cached.example.com/art.jpg"


@pytest.mark.asyncio
async def test_fetch_music_artwork_caches_none():
    client, _ = make_client()
    itunes_data = {"results": []}
    mb_data = {"recordings": []}
    session = _mock_session(
        _make_response(200, itunes_data),
        _make_response(200, mb_data),
    )
    with patch(
        "custom_components.busch_radio_inet.artwork_client.async_get_clientsession",
        return_value=session,
    ), patch(
        "custom_components.busch_radio_inet.artwork_client.asyncio.sleep",
        new_callable=AsyncMock,
    ):
        result = await client.fetch_music_artwork("X", "Y")
    assert result is None
    assert "X|Y" in client._music_cache
    assert client._music_cache["X|Y"] is None


@pytest.mark.asyncio
async def test_fetch_music_artwork_exception_returns_none():
    client, _ = make_client()
    session = MagicMock()
    session.get = MagicMock(side_effect=Exception("network error"))
    with patch(
        "custom_components.busch_radio_inet.artwork_client.async_get_clientsession",
        return_value=session,
    ):
        result = await client.fetch_music_artwork("A", "B")
    # iTunes fails → MusicBrainz also fails (no mock) → None
    assert result is None


# ===========================================================================
# fetch_music_artwork – MusicBrainz hit (Cover Art Archive)
# ===========================================================================


@pytest.mark.asyncio
async def test_fetch_music_artwork_musicbrainz_caa_hit():
    """_fetch_musicbrainz: MB recording found → CAA redirect → artwork URL.

    _mb_throttled_get uses `await session.get(...)` (not async with), so the
    MB mock must be a coroutine, not a context-manager mock.
    """
    client, _ = make_client()
    mb_data = {
        "recordings": [{
            "score": 100,
            "releases": [{"id": "release-uuid-123"}]
        }]
    }
    mb_resp = _make_response(200, mb_data)

    caa_resp = MagicMock()
    caa_resp.status = 307
    caa_resp.headers = {"Location": "https://archive.org/cover.jpg"}

    session = MagicMock()

    async def mb_coro(*args, **kwargs):
        return mb_resp

    session.get = MagicMock(side_effect=[
        mb_coro(),  # MB throttled get: awaited directly
        AsyncMock(  # CAA: async with
            __aenter__=AsyncMock(return_value=caa_resp),
            __aexit__=AsyncMock(return_value=False),
        ),
    ])

    with patch.object(client, "_fetch_itunes", new=AsyncMock(return_value=None)), \
         patch(
             "custom_components.busch_radio_inet.artwork_client.async_get_clientsession",
             return_value=session,
         ), patch(
             "custom_components.busch_radio_inet.artwork_client.asyncio.sleep",
             new_callable=AsyncMock,
         ):
        result = await client.fetch_music_artwork("Artist", "Song")

    assert result == "https://archive.org/cover.jpg"


@pytest.mark.asyncio
async def test_fetch_music_artwork_musicbrainz_no_releases():
    client, _ = make_client()
    itunes_data = {"results": []}
    mb_data = {
        "recordings": [{"releases": []}]  # No releases
    }
    session = _mock_session(
        _make_response(200, itunes_data),
        _make_response(200, mb_data),
    )
    with patch(
        "custom_components.busch_radio_inet.artwork_client.async_get_clientsession",
        return_value=session,
    ), patch(
        "custom_components.busch_radio_inet.artwork_client.asyncio.sleep",
        new_callable=AsyncMock,
    ):
        result = await client.fetch_music_artwork("Classical", "Piece")
    assert result is None


# ===========================================================================
# fetch_station_logo – radio-browser URL match
# ===========================================================================


@pytest.mark.asyncio
async def test_fetch_station_logo_url_match():
    client, _ = make_client()
    rb_data = [{"favicon": "https://logo.example.com/station.png"}]
    session = _mock_session(_make_response(200, rb_data))
    with patch(
        "custom_components.busch_radio_inet.artwork_client.async_get_clientsession",
        return_value=session,
    ):
        result = await client.fetch_station_logo("http://stream.example.com", "My Station")
    assert result == "https://logo.example.com/station.png"


@pytest.mark.asyncio
async def test_fetch_station_logo_url_no_favicon_falls_back_to_name():
    client, _ = make_client()
    # URL lookup returns empty favicon → name lookup returns logo
    rb_url_data = [{"favicon": ""}]
    rb_name_data = [{"favicon": "https://logo.example.com/by_name.png"}]
    session = _mock_session(
        _make_response(200, rb_url_data),
        _make_response(200, rb_name_data),
    )
    with patch(
        "custom_components.busch_radio_inet.artwork_client.async_get_clientsession",
        return_value=session,
    ):
        result = await client.fetch_station_logo("http://stream.example.com", "My Station")
    assert result == "https://logo.example.com/by_name.png"


@pytest.mark.asyncio
async def test_fetch_station_logo_no_url_uses_name():
    client, _ = make_client()
    rb_data = [{"favicon": "https://logo.example.com/name.png"}]
    session = _mock_session(_make_response(200, rb_data))
    with patch(
        "custom_components.busch_radio_inet.artwork_client.async_get_clientsession",
        return_value=session,
    ):
        result = await client.fetch_station_logo(None, "My Station")
    assert result == "https://logo.example.com/name.png"


@pytest.mark.asyncio
async def test_fetch_station_logo_empty_cache_key_returns_none():
    client, _ = make_client()
    result = await client.fetch_station_logo(None, "")
    assert result is None


@pytest.mark.asyncio
async def test_fetch_station_logo_cached():
    client, _ = make_client()
    client._logo_cache["http://stream.example.com"] = "https://cached.example.com/logo.png"
    result = await client.fetch_station_logo("http://stream.example.com", "Station")
    assert result == "https://cached.example.com/logo.png"


@pytest.mark.asyncio
async def test_fetch_station_logo_caches_none():
    client, _ = make_client()
    rb_data: list = []
    session = _mock_session(
        _make_response(200, rb_data),  # URL lookup: empty list
        _make_response(200, rb_data),  # Name lookup: empty list
    )
    with patch(
        "custom_components.busch_radio_inet.artwork_client.async_get_clientsession",
        return_value=session,
    ):
        result = await client.fetch_station_logo("http://stream.example.com", "Station")
    assert result is None
    assert "http://stream.example.com" in client._logo_cache
    assert client._logo_cache["http://stream.example.com"] is None


@pytest.mark.asyncio
async def test_fetch_station_logo_exception_returns_none():
    client, _ = make_client()
    session = MagicMock()
    session.get = MagicMock(side_effect=Exception("network error"))
    with patch(
        "custom_components.busch_radio_inet.artwork_client.async_get_clientsession",
        return_value=session,
    ):
        result = await client.fetch_station_logo("http://stream.example.com", "Station")
    assert result is None


@pytest.mark.asyncio
async def test_fetch_station_logo_non_200_url_lookup():
    """URL lookup returns HTTP 500 → falls back to name lookup."""
    client, _ = make_client()
    rb_name_data = [{"favicon": "https://logo.example.com/fallback.png"}]
    session = _mock_session(
        _make_response(500),          # URL lookup fails
        _make_response(200, rb_name_data),  # Name lookup succeeds
    )
    with patch(
        "custom_components.busch_radio_inet.artwork_client.async_get_clientsession",
        return_value=session,
    ):
        result = await client.fetch_station_logo("http://stream.example.com", "Station")
    assert result == "https://logo.example.com/fallback.png"


# ===========================================================================
# _mb_throttled_get – rate limiting
# ===========================================================================


@pytest.mark.asyncio
async def test_mb_throttled_get_enforces_wait():
    client, _ = make_client()
    # Set last request to "now" so wait is needed
    artwork_module._mb_last_request = __import__("time").monotonic()

    sleep_called_with = []

    async def fake_sleep(t):
        sleep_called_with.append(t)

    # session.get must be an AsyncMock so that `await session.get(...)` works.
    # _mb_throttled_get does `return await session.get(...)` – the call returns a
    # coroutine (from AsyncMock), and awaiting it yields the return_value.
    session = MagicMock()
    session.get = AsyncMock(return_value=MagicMock())

    with patch(
        "custom_components.busch_radio_inet.artwork_client.asyncio.sleep",
        side_effect=fake_sleep,
    ):
        await client._mb_throttled_get(session, "https://musicbrainz.org/ws/2/recording/")

    assert len(sleep_called_with) == 1
    assert sleep_called_with[0] > 0


# ===========================================================================
# _fetch_itunes – artist match filter
# ===========================================================================


@pytest.mark.asyncio
async def test_itunes_skips_result_when_artist_does_not_match():
    """First result has wrong artist → skipped; second result matches → returned."""
    client, _ = make_client()
    itunes_data = {
        "results": [
            {"artistName": "Nils Frahm", "artworkUrl100": "https://wrong.com/100x100bb.jpg"},
            {"artistName": "George Ezra", "artworkUrl100": "https://correct.com/100x100bb.jpg"},
        ]
    }
    session = _mock_session(_make_response(200, itunes_data))
    with patch(
        "custom_components.busch_radio_inet.artwork_client.async_get_clientsession",
        return_value=session,
    ):
        result = await client.fetch_music_artwork("George Ezra", "Shotgun")
    assert result == "https://correct.com/600x600bb.jpg"


@pytest.mark.asyncio
async def test_itunes_returns_none_when_no_artist_matches():
    """All results have a different artist → falls through to MusicBrainz → None."""
    client, _ = make_client()
    itunes_data = {
        "results": [
            {"artistName": "Nils Frahm", "artworkUrl100": "https://wrong.com/100x100bb.jpg"},
            {"artistName": "Erased Tapes", "artworkUrl100": "https://wrong2.com/100x100bb.jpg"},
        ]
    }
    mb_data = {"recordings": []}
    session = _mock_session(_make_response(200, itunes_data), _make_response(200, mb_data))
    with patch(
        "custom_components.busch_radio_inet.artwork_client.async_get_clientsession",
        return_value=session,
    ), patch(
        "custom_components.busch_radio_inet.artwork_client.asyncio.sleep",
        new_callable=AsyncMock,
    ):
        result = await client.fetch_music_artwork("George Ezra", "Shotgun")
    assert result is None


@pytest.mark.asyncio
async def test_itunes_artist_match_is_case_insensitive():
    """Artist match must be case-insensitive."""
    client, _ = make_client()
    itunes_data = {
        "results": [{"artistName": "ADELE", "artworkUrl100": "https://adele.com/100x100bb.jpg"}]
    }
    session = _mock_session(_make_response(200, itunes_data))
    with patch(
        "custom_components.busch_radio_inet.artwork_client.async_get_clientsession",
        return_value=session,
    ):
        result = await client.fetch_music_artwork("Adele", "Hello")
    assert result == "https://adele.com/600x600bb.jpg"


# ===========================================================================
# _fetch_musicbrainz – score threshold
# ===========================================================================


@pytest.mark.asyncio
async def test_musicbrainz_low_score_returns_none():
    """Recording with score < 85 must be rejected."""
    client, _ = make_client()
    mb_data = {
        "recordings": [{
            "score": 60,
            "releases": [{"id": "some-release"}]
        }]
    }
    with patch.object(client, "_fetch_itunes", new=AsyncMock(return_value=None)), \
         patch.object(client, "_mb_throttled_get", new=AsyncMock(
             return_value=_make_response(200, mb_data)
         )), \
         patch(
             "custom_components.busch_radio_inet.artwork_client.async_get_clientsession",
             return_value=MagicMock(),
         ):
        result = await client.fetch_music_artwork("Artist", "Song")
    assert result is None


@pytest.mark.asyncio
async def test_musicbrainz_score_exactly_85_is_accepted():
    """Score of exactly 85 must be accepted (boundary)."""
    client, _ = make_client()
    mb_data = {
        "recordings": [{
            "score": 85,
            "releases": [{"id": "release-uuid-85"}]
        }]
    }
    caa_resp = MagicMock()
    caa_resp.status = 307
    caa_resp.headers = {"Location": "https://archive.org/cover85.jpg"}

    session = MagicMock()
    session.get = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=caa_resp),
        __aexit__=AsyncMock(return_value=False),
    ))

    with patch.object(client, "_fetch_itunes", new=AsyncMock(return_value=None)), \
         patch.object(client, "_mb_throttled_get", new=AsyncMock(
             return_value=_make_response(200, mb_data)
         )), \
         patch(
             "custom_components.busch_radio_inet.artwork_client.async_get_clientsession",
             return_value=session,
         ):
        result = await client.fetch_music_artwork("Artist", "Song")
    assert result == "https://archive.org/cover85.jpg"


# ===========================================================================
# _best_release_id – release selection
# ===========================================================================


def test_best_release_id_prefers_official_album():
    releases = [
        {"id": "comp-id", "status": "Official", "release-group": {"primary-type": "Compilation"}},
        {"id": "album-id", "status": "Official", "release-group": {"primary-type": "Album"}},
    ]
    assert _best_release_id(releases) == "album-id"


def test_best_release_id_falls_back_to_official_non_album():
    releases = [
        {"id": "single-id", "status": "Official", "release-group": {"primary-type": "Single"}},
        {"id": "promo-id", "status": "Promotion", "release-group": {"primary-type": "Album"}},
    ]
    assert _best_release_id(releases) == "single-id"


def test_best_release_id_falls_back_to_first_when_nothing_official():
    releases = [
        {"id": "first-id", "status": "Bootleg", "release-group": {"primary-type": "Album"}},
        {"id": "second-id", "status": "Bootleg", "release-group": {"primary-type": "Album"}},
    ]
    assert _best_release_id(releases) == "first-id"


def test_best_release_id_returns_none_when_releases_empty():
    assert _best_release_id([{}]) is None


def test_best_release_id_handles_missing_release_group():
    releases = [{"id": "bare-id", "status": "Official"}]
    assert _best_release_id(releases) == "bare-id"


# ===========================================================================
# _mb_throttled_get – rate limiting
# ===========================================================================


@pytest.mark.asyncio
async def test_mb_throttled_get_no_wait_when_interval_passed():
    client, _ = make_client()
    # Set last request to long ago
    artwork_module._mb_last_request = 0.0

    sleep_called = []

    async def fake_sleep(t):
        sleep_called.append(t)

    session = MagicMock()
    session.get = AsyncMock(return_value=MagicMock())

    with patch(
        "custom_components.busch_radio_inet.artwork_client.asyncio.sleep",
        side_effect=fake_sleep,
    ):
        await client._mb_throttled_get(session, "https://musicbrainz.org/ws/2/recording/")

    assert len(sleep_called) == 0


_SESSION_PATCH = "custom_components.busch_radio_inet.artwork_client.async_get_clientsession"


# ===========================================================================
# _fetch_itunes – cancellation
# ===========================================================================


@pytest.mark.asyncio
async def test_itunes_cancelled_propagates():
    client, _ = make_client()
    session = MagicMock()
    session.get = MagicMock(side_effect=asyncio.CancelledError)
    with patch(_SESSION_PATCH, return_value=session):
        with pytest.raises(asyncio.CancelledError):
            await client._fetch_itunes("Artist", "Song")


# ===========================================================================
# _fetch_musicbrainz – error/empty branches and cancellation
# ===========================================================================


@pytest.mark.asyncio
async def test_musicbrainz_non_200_returns_none():
    client, _ = make_client()
    with patch.object(client, "_fetch_itunes", new=AsyncMock(return_value=None)), \
         patch.object(client, "_mb_throttled_get", new=AsyncMock(return_value=_make_response(500))), \
         patch(_SESSION_PATCH, return_value=MagicMock()):
        assert await client.fetch_music_artwork("A", "B") is None


@pytest.mark.asyncio
async def test_musicbrainz_no_recordings_returns_none():
    client, _ = make_client()
    mb = _make_response(200, {"recordings": []})
    with patch.object(client, "_fetch_itunes", new=AsyncMock(return_value=None)), \
         patch.object(client, "_mb_throttled_get", new=AsyncMock(return_value=mb)), \
         patch(_SESSION_PATCH, return_value=MagicMock()):
        assert await client.fetch_music_artwork("A", "B") is None


@pytest.mark.asyncio
async def test_musicbrainz_no_releases_returns_none():
    client, _ = make_client()
    mb = _make_response(200, {"recordings": [{"score": 100, "releases": []}]})
    with patch.object(client, "_fetch_itunes", new=AsyncMock(return_value=None)), \
         patch.object(client, "_mb_throttled_get", new=AsyncMock(return_value=mb)), \
         patch(_SESSION_PATCH, return_value=MagicMock()):
        assert await client.fetch_music_artwork("A", "B") is None


@pytest.mark.asyncio
async def test_musicbrainz_no_release_id_returns_none():
    client, _ = make_client()
    # A release without an "id" -> _best_release_id returns None.
    mb = _make_response(200, {"recordings": [{"score": 100, "releases": [{}]}]})
    with patch.object(client, "_fetch_itunes", new=AsyncMock(return_value=None)), \
         patch.object(client, "_mb_throttled_get", new=AsyncMock(return_value=mb)), \
         patch(_SESSION_PATCH, return_value=MagicMock()):
        assert await client.fetch_music_artwork("A", "B") is None


@pytest.mark.asyncio
async def test_musicbrainz_caa_redirect_without_location_returns_none():
    client, _ = make_client()
    mb = _make_response(200, {"recordings": [{"score": 100, "releases": [{"id": "rel-1"}]}]})
    caa = MagicMock()
    caa.status = 307
    caa.headers = {}  # redirect status but no Location header
    session = _mock_session(caa)
    with patch.object(client, "_fetch_itunes", new=AsyncMock(return_value=None)), \
         patch.object(client, "_mb_throttled_get", new=AsyncMock(return_value=mb)), \
         patch(_SESSION_PATCH, return_value=session):
        assert await client.fetch_music_artwork("A", "B") is None


@pytest.mark.asyncio
async def test_musicbrainz_caa_non_redirect_status_returns_none():
    client, _ = make_client()
    mb = _make_response(200, {"recordings": [{"score": 100, "releases": [{"id": "rel-1"}]}]})
    caa = MagicMock()
    caa.status = 404  # no artwork available
    caa.headers = {}
    session = _mock_session(caa)
    with patch.object(client, "_fetch_itunes", new=AsyncMock(return_value=None)), \
         patch.object(client, "_mb_throttled_get", new=AsyncMock(return_value=mb)), \
         patch(_SESSION_PATCH, return_value=session):
        assert await client.fetch_music_artwork("A", "B") is None


@pytest.mark.asyncio
async def test_musicbrainz_cancelled_propagates():
    client, _ = make_client()
    with patch.object(client, "_mb_throttled_get", new=AsyncMock(side_effect=asyncio.CancelledError)), \
         patch(_SESSION_PATCH, return_value=MagicMock()):
        with pytest.raises(asyncio.CancelledError):
            await client._fetch_musicbrainz("A", "B")


# ===========================================================================
# radio-browser – cancellation and name-lookup branches
# ===========================================================================


@pytest.mark.asyncio
async def test_radiobrowser_by_url_cancelled_propagates():
    client, _ = make_client()
    session = MagicMock()
    session.get = MagicMock(side_effect=asyncio.CancelledError)
    with patch(_SESSION_PATCH, return_value=session):
        with pytest.raises(asyncio.CancelledError):
            await client._fetch_radiobrowser_by_url("http://stream.example.com")


@pytest.mark.asyncio
async def test_radiobrowser_by_name_non_200_returns_none():
    client, _ = make_client()
    session = _mock_session(_make_response(500))
    with patch(_SESSION_PATCH, return_value=session):
        assert await client._fetch_radiobrowser_by_name("Station") is None


@pytest.mark.asyncio
async def test_radiobrowser_by_name_cancelled_propagates():
    client, _ = make_client()
    session = MagicMock()
    session.get = MagicMock(side_effect=asyncio.CancelledError)
    with patch(_SESSION_PATCH, return_value=session):
        with pytest.raises(asyncio.CancelledError):
            await client._fetch_radiobrowser_by_name("Station")
