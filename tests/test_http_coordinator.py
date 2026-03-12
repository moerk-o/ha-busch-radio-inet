"""Tests for HttpSettingsCoordinator."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from homeassistant.exceptions import HomeAssistantError

from custom_components.busch_radio_inet.http_coordinator import HttpSettingsCoordinator


def make_coordinator(poll_interval=60):
    hass = MagicMock()
    hass.bus = MagicMock()
    client = MagicMock()
    client.async_get_config = AsyncMock(return_value={"bb": "100", "co": "80"})
    client.async_post_general = AsyncMock()
    coord = HttpSettingsCoordinator(hass, client, poll_interval)
    return coord, hass, client


# ===========================================================================
# _async_update_data
# ===========================================================================


@pytest.mark.asyncio
async def test_update_data_returns_parsed_config():
    coord, _, client = make_coordinator()
    result = await coord._async_update_data()
    assert result == {"bb": "100", "co": "80"}
    client.async_get_config.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_data_raises_update_failed_on_error():
    from homeassistant.helpers.update_coordinator import UpdateFailed

    coord, _, client = make_coordinator()
    client.async_get_config.side_effect = Exception("connection refused")
    with pytest.raises(UpdateFailed, match="Cannot read /radio.cfg"):
        await coord._async_update_data()


# ===========================================================================
# async_set
# ===========================================================================


@pytest.mark.asyncio
async def test_async_set_read_modify_write():
    coord, _, client = make_coordinator()
    client.async_get_config.return_value = {"bb": "100", "co": "80", "bl": "2"}

    with patch.object(coord, "async_refresh", new_callable=AsyncMock):
        await coord.async_set({"bb": "50"})

    # The posted dict should have the original fields with bb overwritten
    posted = client.async_post_general.call_args[0][0]
    assert posted["bb"] == "50"
    assert posted["co"] == "80"
    assert posted["bl"] == "2"


@pytest.mark.asyncio
async def test_async_set_calls_async_refresh():
    coord, _, client = make_coordinator()

    refresh_called = False

    async def fake_refresh():
        nonlocal refresh_called
        refresh_called = True

    with patch.object(coord, "async_refresh", new=fake_refresh):
        await coord.async_set({"bb": "50"})

    assert refresh_called


@pytest.mark.asyncio
async def test_async_set_raises_homeassistant_error_on_get_failure():
    coord, _, client = make_coordinator()
    client.async_get_config.side_effect = Exception("network error")

    with pytest.raises(HomeAssistantError, match="Failed to write settings"):
        await coord.async_set({"bb": "50"})


@pytest.mark.asyncio
async def test_async_set_raises_homeassistant_error_on_post_failure():
    coord, _, client = make_coordinator()
    client.async_post_general.side_effect = Exception("post failed")

    with pytest.raises(HomeAssistantError, match="Failed to write settings"):
        await coord.async_set({"bb": "50"})


@pytest.mark.asyncio
async def test_async_set_multi_field_atomic():
    """Two fields written together in a single call."""
    coord, _, client = make_coordinator()
    client.async_get_config.return_value = {"hr": "10", "mi": "30", "zs": "0"}

    with patch.object(coord, "async_refresh", new_callable=AsyncMock):
        await coord.async_set({"hr": "14", "mi": "25"})

    posted = client.async_post_general.call_args[0][0]
    assert posted["hr"] == "14"
    assert posted["mi"] == "25"
    assert posted["zs"] == "0"  # unchanged


@pytest.mark.asyncio
async def test_async_set_refresh_not_called_on_error():
    coord, _, client = make_coordinator()
    client.async_get_config.side_effect = Exception("fail")

    refresh_called = False

    async def fake_refresh():
        nonlocal refresh_called
        refresh_called = True

    with patch.object(coord, "async_refresh", new=fake_refresh):
        with pytest.raises(HomeAssistantError):
            await coord.async_set({"bb": "50"})

    assert not refresh_called
