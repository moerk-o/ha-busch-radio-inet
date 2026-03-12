"""Tests for HttpSettingsClient and parse_radio_cfg."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiohttp import ClientResponseError, RequestInfo
from yarl import URL

from custom_components.busch_radio_inet.http_client import (
    HttpSettingsClient,
    parse_radio_cfg,
)


# ===========================================================================
# parse_radio_cfg
# ===========================================================================


def test_parse_basic_fields():
    text = "&bb=100\n&co=80\n"
    result = parse_radio_cfg(text)
    assert result["bb"] == "100"
    assert result["co"] == "80"


def test_parse_ignores_section_headers():
    text = "[general]\n&bb=50\n[system]\n&sp=1\n"
    result = parse_radio_cfg(text)
    assert "bb" in result
    assert "sp" in result
    assert "[general]" not in result


def test_parse_empty_value():
    text = "&aw=\n"
    result = parse_radio_cfg(text)
    assert result["aw"] == ""


def test_parse_strips_leading_ampersand():
    text = "&hr=14\n"
    result = parse_radio_cfg(text)
    assert result["hr"] == "14"


def test_parse_without_leading_ampersand():
    text = "bb=100\n"
    result = parse_radio_cfg(text)
    assert result["bb"] == "100"


def test_parse_ignores_blank_lines():
    text = "\n&bb=10\n\n&co=20\n\n"
    result = parse_radio_cfg(text)
    assert result == {"bb": "10", "co": "20"}


def test_parse_full_sample():
    text = (
        "[general]\n"
        "&bb=100\n"
        "&co=80\n"
        "&bl=2\n"
        "&dm=0\n"
        "&aw=\n"
        "&sz=1\n"
        "[system]\n"
        "&sw=0\n"
        "&sp=1\n"
    )
    result = parse_radio_cfg(text)
    assert result["bb"] == "100"
    assert result["co"] == "80"
    assert result["bl"] == "2"
    assert result["aw"] == ""
    assert result["sz"] == "1"
    assert result["sw"] == "0"
    assert result["sp"] == "1"


def test_parse_empty_string():
    assert parse_radio_cfg("") == {}


def test_parse_only_section_headers():
    text = "[general]\n[system]\n"
    assert parse_radio_cfg(text) == {}


def test_parse_strips_whitespace_around_key_value():
    text = "& bb = 42 \n"
    result = parse_radio_cfg(text)
    # After stripping & we get " bb = 42 ", partition gives key=" bb ", value=" 42 "
    # strip() is applied → should work
    assert result["bb"] == "42"


# ===========================================================================
# HttpSettingsClient.async_get_config
# ===========================================================================


def _make_client(host="192.168.1.179"):
    hass = MagicMock()
    return HttpSettingsClient(hass, host), hass


def _make_mock_response(text="&bb=100\n", status=200):
    resp = AsyncMock()
    resp.status = status
    resp.text = AsyncMock(return_value=text)
    resp.raise_for_status = MagicMock()
    return resp


@pytest.mark.asyncio
async def test_async_get_config_returns_parsed_dict():
    client, hass = _make_client()
    mock_resp = _make_mock_response("&bb=100\n&co=80\n")
    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=mock_resp),
        __aexit__=AsyncMock(return_value=False),
    ))
    with patch(
        "custom_components.busch_radio_inet.http_client.async_get_clientsession",
        return_value=mock_session,
    ):
        result = await client.async_get_config()
    assert result["bb"] == "100"
    assert result["co"] == "80"


@pytest.mark.asyncio
async def test_async_get_config_uses_latin1_encoding():
    client, hass = _make_client()
    mock_resp = _make_mock_response()
    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=mock_resp),
        __aexit__=AsyncMock(return_value=False),
    ))
    with patch(
        "custom_components.busch_radio_inet.http_client.async_get_clientsession",
        return_value=mock_session,
    ):
        await client.async_get_config()
    mock_resp.text.assert_awaited_once_with(encoding="latin-1")


@pytest.mark.asyncio
async def test_async_get_config_calls_raise_for_status():
    client, hass = _make_client()
    mock_resp = _make_mock_response()
    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=mock_resp),
        __aexit__=AsyncMock(return_value=False),
    ))
    with patch(
        "custom_components.busch_radio_inet.http_client.async_get_clientsession",
        return_value=mock_session,
    ):
        await client.async_get_config()
    mock_resp.raise_for_status.assert_called_once()


# ===========================================================================
# HttpSettingsClient.async_post_general
# ===========================================================================


@pytest.mark.asyncio
async def test_async_post_general_removes_blocked_fields():
    client, hass = _make_client()
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.raise_for_status = MagicMock()
    captured_data = {}

    def fake_post(url, data, timeout):
        captured_data.update(data)
        return AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(return_value=False),
        )

    mock_session = MagicMock()
    mock_session.post = fake_post
    with patch(
        "custom_components.busch_radio_inet.http_client.async_get_clientsession",
        return_value=mock_session,
    ):
        await client.async_post_general({"bb": "100", "sw": "1", "sp": "0"})

    assert "sw" not in captured_data
    assert "sp" not in captured_data
    assert captured_data["bb"] == "100"


@pytest.mark.asyncio
async def test_async_post_general_checkbox_on():
    """Checkbox field with value '1' stays '1'."""
    client, hass = _make_client()
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.raise_for_status = MagicMock()
    captured_data = {}

    def fake_post(url, data, timeout):
        captured_data.update(data)
        return AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(return_value=False),
        )

    mock_session = MagicMock()
    mock_session.post = fake_post
    with patch(
        "custom_components.busch_radio_inet.http_client.async_get_clientsession",
        return_value=mock_session,
    ):
        await client.async_post_general({"aw": "1"})

    assert captured_data["aw"] == "1"


@pytest.mark.asyncio
async def test_async_post_general_checkbox_off_when_missing():
    """Checkbox field not in input → sent as '' (off)."""
    client, hass = _make_client()
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.raise_for_status = MagicMock()
    captured_data = {}

    def fake_post(url, data, timeout):
        captured_data.update(data)
        return AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(return_value=False),
        )

    mock_session = MagicMock()
    mock_session.post = fake_post
    with patch(
        "custom_components.busch_radio_inet.http_client.async_get_clientsession",
        return_value=mock_session,
    ):
        await client.async_post_general({"bb": "80"})

    for cb in ("aw", "sz", "ea", "et", "es"):
        assert captured_data[cb] == "", f"Expected '' for checkbox {cb}"


@pytest.mark.asyncio
async def test_async_post_general_checkbox_off_explicit():
    """Checkbox field with '' value → stays ''."""
    client, hass = _make_client()
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.raise_for_status = MagicMock()
    captured_data = {}

    def fake_post(url, data, timeout):
        captured_data.update(data)
        return AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(return_value=False),
        )

    mock_session = MagicMock()
    mock_session.post = fake_post
    with patch(
        "custom_components.busch_radio_inet.http_client.async_get_clientsession",
        return_value=mock_session,
    ):
        await client.async_post_general({"aw": ""})

    assert captured_data["aw"] == ""


@pytest.mark.asyncio
async def test_async_post_general_calls_raise_for_status():
    client, hass = _make_client()
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.raise_for_status = MagicMock()

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=mock_resp),
        __aexit__=AsyncMock(return_value=False),
    ))
    with patch(
        "custom_components.busch_radio_inet.http_client.async_get_clientsession",
        return_value=mock_session,
    ):
        await client.async_post_general({"bb": "100"})
    mock_resp.raise_for_status.assert_called_once()


@pytest.mark.asyncio
async def test_async_post_general_url_uses_host():
    client, hass = _make_client(host="10.0.0.5")
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.raise_for_status = MagicMock()
    posted_url = []

    def fake_post(url, data, timeout):
        posted_url.append(url)
        return AsyncMock(
            __aenter__=AsyncMock(return_value=mock_resp),
            __aexit__=AsyncMock(return_value=False),
        )

    mock_session = MagicMock()
    mock_session.post = fake_post
    with patch(
        "custom_components.busch_radio_inet.http_client.async_get_clientsession",
        return_value=mock_session,
    ):
        await client.async_post_general({"bb": "100"})

    assert posted_url[0] == "http://10.0.0.5/en/general.cgi"
