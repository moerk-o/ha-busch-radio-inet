"""Tests for BuschRadioUDPClient."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.busch_radio_inet.udp_client import BuschRadioUDPClient


HOST = "192.168.1.179"
PORT = 4244


def make_client() -> BuschRadioUDPClient:
    return BuschRadioUDPClient(HOST, PORT)


def mock_loop_with_transport(transport: MagicMock):
    """Return a mock event loop whose create_datagram_endpoint returns the given transport."""
    mock_loop = MagicMock()
    mock_loop.create_datagram_endpoint = AsyncMock(return_value=(transport, MagicMock()))
    return mock_loop


# ---------------------------------------------------------------------------
# send_raw
# ---------------------------------------------------------------------------


async def test_send_raw_sends_encoded_message():
    client = make_client()
    transport = MagicMock()
    with patch(
        "custom_components.busch_radio_inet.udp_client.asyncio.get_running_loop",
        return_value=mock_loop_with_transport(transport),
    ):
        await client.send_raw("hello")

    transport.sendto.assert_called_once_with(b"hello")
    transport.close.assert_called_once()


async def test_send_raw_closes_transport_on_oserror():
    client = make_client()
    mock_loop = MagicMock()
    mock_loop.create_datagram_endpoint = AsyncMock(side_effect=OSError("no route"))
    with patch(
        "custom_components.busch_radio_inet.udp_client.asyncio.get_running_loop",
        return_value=mock_loop,
    ):
        # Must not raise
        await client.send_raw("hello")


async def test_send_raw_closes_transport_even_after_sendto_error():
    """Transport must be closed even if sendto raises."""
    client = make_client()
    transport = MagicMock()
    transport.sendto.side_effect = OSError("send failed")
    with patch(
        "custom_components.busch_radio_inet.udp_client.asyncio.get_running_loop",
        return_value=mock_loop_with_transport(transport),
    ):
        # Should not propagate the error
        await client.send_raw("hello")

    transport.close.assert_called_once()


# ---------------------------------------------------------------------------
# send_get
# ---------------------------------------------------------------------------


async def test_send_get_formats_command_correctly():
    client = make_client()
    transport = MagicMock()
    with patch(
        "custom_components.busch_radio_inet.udp_client.asyncio.get_running_loop",
        return_value=mock_loop_with_transport(transport),
    ):
        await client.send_get("POWER_STATUS")

    transport.sendto.assert_called_once_with(
        b"COMMAND:GET\r\nPOWER_STATUS\r\nID:HA\r\n\r\n"
    )


async def test_send_get_volume():
    client = make_client()
    transport = MagicMock()
    with patch(
        "custom_components.busch_radio_inet.udp_client.asyncio.get_running_loop",
        return_value=mock_loop_with_transport(transport),
    ):
        await client.send_get("VOLUME")

    transport.sendto.assert_called_once_with(b"COMMAND:GET\r\nVOLUME\r\nID:HA\r\n\r\n")


async def test_send_get_all_station_info():
    client = make_client()
    transport = MagicMock()
    with patch(
        "custom_components.busch_radio_inet.udp_client.asyncio.get_running_loop",
        return_value=mock_loop_with_transport(transport),
    ):
        await client.send_get("ALL_STATION_INFO")

    transport.sendto.assert_called_once_with(
        b"COMMAND:GET\r\nALL_STATION_INFO\r\nID:HA\r\n\r\n"
    )


# ---------------------------------------------------------------------------
# send_set
# ---------------------------------------------------------------------------


async def test_send_set_formats_command_correctly():
    client = make_client()
    transport = MagicMock()
    with patch(
        "custom_components.busch_radio_inet.udp_client.asyncio.get_running_loop",
        return_value=mock_loop_with_transport(transport),
    ):
        await client.send_set("RADIO_ON")

    transport.sendto.assert_called_once_with(
        b"COMMAND:SET\r\nRADIO_ON\r\nID:HA\r\n\r\n"
    )


async def test_send_set_volume_absolute():
    client = make_client()
    transport = MagicMock()
    with patch(
        "custom_components.busch_radio_inet.udp_client.asyncio.get_running_loop",
        return_value=mock_loop_with_transport(transport),
    ):
        await client.send_set("VOLUME_ABSOLUTE:15")

    transport.sendto.assert_called_once_with(
        b"COMMAND:SET\r\nVOLUME_ABSOLUTE:15\r\nID:HA\r\n\r\n"
    )


async def test_send_set_volume_mute():
    client = make_client()
    transport = MagicMock()
    with patch(
        "custom_components.busch_radio_inet.udp_client.asyncio.get_running_loop",
        return_value=mock_loop_with_transport(transport),
    ):
        await client.send_set("VOLUME_MUTE")

    transport.sendto.assert_called_once_with(
        b"COMMAND:SET\r\nVOLUME_MUTE\r\nID:HA\r\n\r\n"
    )


# ---------------------------------------------------------------------------
# send_play
# ---------------------------------------------------------------------------


async def test_send_play_formats_command_correctly():
    client = make_client()
    transport = MagicMock()
    with patch(
        "custom_components.busch_radio_inet.udp_client.asyncio.get_running_loop",
        return_value=mock_loop_with_transport(transport),
    ):
        await client.send_play("STATION:3")

    transport.sendto.assert_called_once_with(
        b"COMMAND:PLAY\r\nSTATION:3\r\nID:HA\r\n\r\n"
    )


async def test_send_play_station_1():
    client = make_client()
    transport = MagicMock()
    with patch(
        "custom_components.busch_radio_inet.udp_client.asyncio.get_running_loop",
        return_value=mock_loop_with_transport(transport),
    ):
        await client.send_play("STATION:1")

    transport.sendto.assert_called_once_with(
        b"COMMAND:PLAY\r\nSTATION:1\r\nID:HA\r\n\r\n"
    )


# ---------------------------------------------------------------------------
# Uses correct host/port
# ---------------------------------------------------------------------------


async def test_uses_configured_host_and_port():
    client = BuschRadioUDPClient("10.0.0.5", 9999)
    transport = MagicMock()
    mock_loop = MagicMock()
    mock_loop.create_datagram_endpoint = AsyncMock(return_value=(transport, MagicMock()))

    with patch(
        "custom_components.busch_radio_inet.udp_client.asyncio.get_running_loop",
        return_value=mock_loop,
    ):
        await client.send_get("POWER_STATUS")

    mock_loop.create_datagram_endpoint.assert_called_once()
    _, kwargs = mock_loop.create_datagram_endpoint.call_args
    assert kwargs["remote_addr"] == ("10.0.0.5", 9999)
