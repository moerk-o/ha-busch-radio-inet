"""Tests for config entry setup and unload."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from custom_components.busch_radio_inet.const import DOMAIN

DEVICE_ANSWER = {"SERNO": "78C40E33745C", "POWER": "OFF", "VOLUME_SET": "10"}


def _make_listener(has_devices=False):
    listener = MagicMock()
    listener.start = AsyncMock()
    listener.has_devices = has_devices
    return listener


def _patch_setup(listener, client):
    """Patch the UDP pieces used by async_setup_entry."""
    return (
        patch(
            "custom_components.busch_radio_inet.SharedUDPListener",
            return_value=listener,
        ),
        patch(
            "custom_components.busch_radio_inet.BuschRadioUDPClient",
            return_value=client,
        ),
        patch("custom_components.busch_radio_inet.coordinator.PROBE_TIMEOUT", 0.01),
        patch("custom_components.busch_radio_inet.coordinator.PROBE_RETRY_DELAY", 0),
    )


@pytest.mark.real_setup_probe
async def test_setup_fails_when_the_device_stays_silent(
    hass: HomeAssistant, mock_config_entry
) -> None:
    """A silent radio must surface as a setup error, not as mute entities."""
    mock_config_entry.add_to_hass(hass)
    listener = _make_listener()
    client = MagicMock()
    client.send_get = AsyncMock()  # nothing ever answers

    a, b, c, d = _patch_setup(listener, client)
    with a, b, c, d:
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


@pytest.mark.real_setup_probe
async def test_failed_setup_releases_the_shared_listener(
    hass: HomeAssistant, mock_config_entry, device_host
) -> None:
    """Home Assistant retries the setup – a failed attempt must leave no trace."""
    mock_config_entry.add_to_hass(hass)
    listener = _make_listener()
    client = MagicMock()
    client.send_get = AsyncMock()

    a, b, c, d = _patch_setup(listener, client)
    with a, b, c, d:
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    listener.unregister.assert_called_once_with(device_host)
    listener.stop.assert_called_once()
    assert "shared_listener" not in hass.data.get(DOMAIN, {})


@pytest.mark.real_setup_probe
async def test_failed_setup_keeps_a_listener_that_still_has_devices(
    hass: HomeAssistant, mock_config_entry, device_host
) -> None:
    """A second radio's socket must survive the first one failing to set up."""
    mock_config_entry.add_to_hass(hass)
    listener = _make_listener(has_devices=True)
    client = MagicMock()
    client.send_get = AsyncMock()

    a, b, c, d = _patch_setup(listener, client)
    with a, b, c, d:
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    listener.unregister.assert_called_once_with(device_host)
    listener.stop.assert_not_called()


@pytest.mark.real_setup_probe
async def test_setup_succeeds_once_the_device_answers(
    hass: HomeAssistant, mock_config_entry
) -> None:
    mock_config_entry.add_to_hass(hass)
    listener = _make_listener()
    captured: dict = {}

    def fake_register(host, on_packet=None, client=None, on_notification=None):
        captured["on_packet"] = on_packet
        return MagicMock()

    listener.register = fake_register

    client = MagicMock()

    async def answer(parameter):
        on_packet = captured.get("on_packet")
        if on_packet is not None:
            on_packet(dict(DEVICE_ANSWER))

    client.send_get = AsyncMock(side_effect=answer)

    a, b, c, d = _patch_setup(listener, client)
    with a, b, c, d:
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
