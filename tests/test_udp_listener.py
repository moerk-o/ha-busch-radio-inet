"""Tests for SharedUDPListener and parse_packet."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.busch_radio_inet.udp_listener import (
    SharedUDPListener,
    _UDPProtocol,
    parse_packet,
)


# ===========================================================================
# parse_packet – unit tests (pure function, no async needed)
# ===========================================================================


class TestParsePacket:
    """Tests for the parse_packet helper."""

    def test_power_status_on(self):
        msg = "COMMAND:GET\r\nPOWER_STATUS\r\nID:HA\r\nPOWER:ON\r\nENERGY_MODE:PREMIUM\r\nRESPONSE:ACK\r\n"
        fields = parse_packet(msg)
        assert fields["COMMAND"] == "GET"
        assert fields["_parameter"] == "POWER_STATUS"
        assert fields["POWER"] == "ON"
        assert fields["ENERGY_MODE"] == "PREMIUM"
        assert fields["RESPONSE"] == "ACK"

    def test_power_status_off(self):
        msg = "COMMAND:GET\r\nPOWER_STATUS\r\nID:HA\r\nPOWER:OFF\r\nRESPONSE:ACK\r\n"
        fields = parse_packet(msg)
        assert fields["POWER"] == "OFF"

    def test_volume_response(self):
        msg = "COMMAND:GET\r\nVOLUME\r\nID:HA\r\nVOLUME_SET:18\r\nRESPONSE:ACK\r\n"
        fields = parse_packet(msg)
        assert fields["VOLUME_SET"] == "18"
        assert fields["_parameter"] == "VOLUME"

    def test_playing_mode_active(self):
        msg = (
            "COMMAND:GET\r\nPLAYING_MODE\r\nID:HA\r\n"
            "PLAYING:STATION\r\nID:2\r\nNAME:NDR 90.3\r\n"
            "URL:http://stream.example.com\r\nRESPONSE:ACK\r\n"
        )
        fields = parse_packet(msg)
        assert fields["PLAYING"] == "STATION"
        assert fields["ID"] == "2"
        assert fields["NAME"] == "NDR 90.3"
        assert fields["URL"] == "http://stream.example.com"

    def test_playing_mode_stopped(self):
        msg = "COMMAND:GET\r\nPLAYING_MODE\r\nID:HA\r\nMODE:PLAYING STOPPED\r\nRESPONSE:ACK\r\n"
        fields = parse_packet(msg)
        assert fields["MODE"] == "PLAYING STOPPED"

    def test_info_block(self):
        msg = (
            "COMMAND:GET\r\nINFO_BLOCK\r\nID:HA\r\n"
            "NAME:RADIO-INET3745C\r\nIPADDR:192.168.1.179\r\n"
            "MAC:78:C4:0E:33:74:5C\r\nSERNO:78C40E33745C\r\n"
            "SW-VERSION:03.12\r\nWLAN STRENGTH:75\r\nSSID:MyWLAN\r\n"
            "RESPONSE:ACK\r\n"
        )
        fields = parse_packet(msg)
        assert fields["SERNO"] == "78C40E33745C"
        assert fields["SW-VERSION"] == "03.12"
        assert fields["NAME"] == "RADIO-INET3745C"
        assert fields["IPADDR"] == "192.168.1.179"

    def test_notification_station_changed(self):
        msg = (
            "COMMAND:NOTIFICATION\r\nIP:192.168.1.179\r\n"
            "NAME:RADIO-INET3745C\r\nEVENT:STATION_CHANGED\r\nRESPONSE:ACK\r\n"
        )
        fields = parse_packet(msg)
        assert fields["COMMAND"] == "NOTIFICATION"
        assert fields["EVENT"] == "STATION_CHANGED"

    def test_notification_volume_changed(self):
        msg = "COMMAND:NOTIFICATION\r\nIP:192.168.1.179\r\nEVENT:VOLUME_CHANGED\r\nRESPONSE:ACK\r\n"
        fields = parse_packet(msg)
        assert fields["EVENT"] == "VOLUME_CHANGED"

    def test_notification_power_on(self):
        msg = "COMMAND:NOTIFICATION\r\nIP:192.168.1.179\r\nEVENT:POWER_ON\r\nRESPONSE:ACK\r\n"
        fields = parse_packet(msg)
        assert fields["EVENT"] == "POWER_ON"

    def test_notification_power_off(self):
        msg = "COMMAND:NOTIFICATION\r\nIP:192.168.1.179\r\nEVENT:POWER_OFF\r\nRESPONSE:ACK\r\n"
        fields = parse_packet(msg)
        assert fields["EVENT"] == "POWER_OFF"

    def test_notification_url_is_playing(self):
        msg = "COMMAND:NOTIFICATION\r\nIP:192.168.1.179\r\nEVENT:URL_IS_PLAYING\r\nRESPONSE:ACK\r\n"
        fields = parse_packet(msg)
        assert fields["EVENT"] == "URL_IS_PLAYING"

    def test_id_ha_echo_is_skipped(self):
        """ID:HA (command echo) must not shadow the station ID:2 in PLAYING_MODE."""
        msg = (
            "COMMAND:GET\r\nPLAYING_MODE\r\nID:HA\r\n"
            "PLAYING:STATION\r\nID:2\r\nNAME:NDR 90.3\r\n"
            "URL:http://stream.example.com\r\nRESPONSE:ACK\r\n"
        )
        fields = parse_packet(msg)
        assert fields["ID"] == "2"  # Must not be ['HA', '2']
        assert "HA" not in fields.get("ID", "")

    def test_set_radio_on_ack(self):
        msg = "COMMAND:SET\r\nRADIO_ON\r\nID:HA\r\nRESPONSE:ACK\r\n"
        fields = parse_packet(msg)
        assert fields["COMMAND"] == "SET"
        assert fields["_parameter"] == "RADIO_ON"
        assert fields["RESPONSE"] == "ACK"

    def test_set_radio_off_nack(self):
        msg = "COMMAND:SET\r\nRADIO_OFF\r\nID:HA\r\nRESPONSE:NACK\r\n"
        fields = parse_packet(msg)
        assert fields["_parameter"] == "RADIO_OFF"
        assert fields["RESPONSE"] == "NACK"

    def test_play_station_ack(self):
        msg = "COMMAND:PLAY\r\nSTATION:3\r\nID:HA\r\nRESPONSE:ACK\r\n"
        fields = parse_packet(msg)
        assert fields["STATION"] == "3"
        assert fields["RESPONSE"] == "ACK"

    def test_all_station_info_multiple_channels(self):
        msg = (
            "COMMAND:GET\r\nALL_STATION_INFO\r\nID:HA\r\n"
            "CHANNEL:1\r\nNAME:WDR 2\r\nURL:http://wdr2.example.com\r\n"
            "CHANNEL:2\r\nNAME:NDR 90.3\r\nURL:http://ndr.example.com\r\n"
            "CHANNEL:3\r\nNAME:\r\nURL:\r\n"
            "CHANNEL:4\r\nNAME:\r\nURL:\r\n"
            "CHANNEL:5\r\nNAME:\r\nURL:\r\n"
            "CHANNEL:6\r\nNAME:\r\nURL:\r\n"
            "CHANNEL:7\r\nNAME:\r\nURL:\r\n"
            "CHANNEL:8\r\nNAME:\r\nURL:\r\n"
            "RESPONSE:ACK\r\n"
        )
        fields = parse_packet(msg)
        stations = fields["_stations"]
        assert len(stations) == 2  # Empty slots filtered
        assert stations[0] == {"id": 1, "name": "WDR 2", "url": "http://wdr2.example.com"}
        assert stations[1] == {"id": 2, "name": "NDR 90.3", "url": "http://ndr.example.com"}

    def test_all_station_info_single_channel(self):
        """Single filled station (CHANNEL is a string, not list)."""
        msg = (
            "COMMAND:GET\r\nALL_STATION_INFO\r\nID:HA\r\n"
            "CHANNEL:1\r\nNAME:Rock Radio\r\nURL:http://rock.example.com\r\n"
            "RESPONSE:ACK\r\n"
        )
        fields = parse_packet(msg)
        assert fields["_stations"] == [
            {"id": 1, "name": "Rock Radio", "url": "http://rock.example.com"}
        ]

    def test_all_station_info_all_empty(self):
        """All stations empty – _stations must be an empty list."""
        msg = (
            "COMMAND:GET\r\nALL_STATION_INFO\r\nID:HA\r\n"
            + "".join(
                f"CHANNEL:{i}\r\nNAME:\r\nURL:\r\n" for i in range(1, 9)
            )
            + "RESPONSE:ACK\r\n"
        )
        fields = parse_packet(msg)
        assert fields["_stations"] == []

    def test_empty_lines_ignored(self):
        msg = "\r\nCOMMAND:GET\r\n\r\nVOLUME\r\n\r\nVOLUME_SET:5\r\nRESPONSE:ACK\r\n\r\n"
        fields = parse_packet(msg)
        assert fields["VOLUME_SET"] == "5"

    def test_only_first_parameter_line_captured(self):
        """Only the first non-colon line becomes _parameter."""
        msg = "COMMAND:GET\r\nFIRST\r\nSECOND\r\nRESPONSE:ACK\r\n"
        fields = parse_packet(msg)
        assert fields["_parameter"] == "FIRST"


# ===========================================================================
# Helpers
# ===========================================================================

HOST1 = "192.168.1.10"
HOST2 = "192.168.1.20"


def make_listener():
    return SharedUDPListener(port=4242)


def make_client():
    client = MagicMock()
    client.send_get = AsyncMock()
    return client


def _start_listener_with_mock(listener):
    """Patch socket + loop so listener.start() succeeds without real networking."""
    mock_transport = MagicMock()
    mock_loop = MagicMock()
    mock_loop.create_datagram_endpoint = AsyncMock(
        return_value=(mock_transport, MagicMock())
    )
    mock_sock = MagicMock()
    return mock_transport, mock_loop, mock_sock


# ===========================================================================
# SharedUDPListener – lifecycle tests
# ===========================================================================


async def test_listener_start_binds_to_port():
    listener = make_listener()
    mock_transport, mock_loop, mock_sock = _start_listener_with_mock(listener)
    with patch(
        "custom_components.busch_radio_inet.udp_listener.asyncio.get_running_loop",
        return_value=mock_loop,
    ), patch(
        "custom_components.busch_radio_inet.udp_listener._socket.socket",
        return_value=mock_sock,
    ):
        await listener.start()

    mock_loop.create_datagram_endpoint.assert_called_once()
    mock_sock.bind.assert_called_once_with(("0.0.0.0", 4242))


async def test_listener_stop_closes_transport():
    listener = make_listener()
    mock_transport, mock_loop, mock_sock = _start_listener_with_mock(listener)
    with patch(
        "custom_components.busch_radio_inet.udp_listener.asyncio.get_running_loop",
        return_value=mock_loop,
    ), patch(
        "custom_components.busch_radio_inet.udp_listener._socket.socket",
        return_value=mock_sock,
    ):
        await listener.start()

    listener.stop()
    mock_transport.close.assert_called_once()


async def test_listener_stop_when_not_started_is_safe():
    listener = make_listener()
    listener.stop()  # Should not raise


# ===========================================================================
# SharedUDPListener – device registration
# ===========================================================================


def test_has_devices_false_when_empty():
    listener = make_listener()
    assert not listener.has_devices


def test_has_devices_true_after_register():
    listener = make_listener()
    listener.register(HOST1, MagicMock(), make_client())
    assert listener.has_devices


def test_has_devices_false_after_unregister_last():
    listener = make_listener()
    listener.register(HOST1, MagicMock(), make_client())
    listener.unregister(HOST1)
    assert not listener.has_devices


def test_unregister_unknown_host_is_safe():
    listener = make_listener()
    listener.unregister("10.0.0.99")  # Should not raise


def test_two_devices_registered_independently():
    listener = make_listener()
    listener.register(HOST1, MagicMock(), make_client())
    listener.register(HOST2, MagicMock(), make_client())
    assert listener.has_devices
    listener.unregister(HOST1)
    assert listener.has_devices  # HOST2 still registered
    listener.unregister(HOST2)
    assert not listener.has_devices


# ===========================================================================
# SharedUDPListener – packet routing
# ===========================================================================


async def test_response_packet_routed_to_correct_device():
    """A GET response from HOST1 must reach only HOST1's on_packet callback."""
    listener = make_listener()
    on_packet1 = MagicMock()
    on_packet2 = MagicMock()
    listener.register(HOST1, on_packet1, make_client())
    listener.register(HOST2, on_packet2, make_client())

    msg = "COMMAND:GET\r\nPOWER_STATUS\r\nID:HA\r\nPOWER:ON\r\nRESPONSE:ACK\r\n"
    listener._handle_datagram(msg, (HOST1, 4244))

    on_packet1.assert_called_once()
    on_packet2.assert_not_called()
    assert on_packet1.call_args[0][0]["POWER"] == "ON"


async def test_response_packet_from_host2_goes_to_host2_only():
    listener = make_listener()
    on_packet1 = MagicMock()
    on_packet2 = MagicMock()
    listener.register(HOST1, on_packet1, make_client())
    listener.register(HOST2, on_packet2, make_client())

    msg = "COMMAND:GET\r\nVOLUME\r\nID:HA\r\nVOLUME_SET:10\r\nRESPONSE:ACK\r\n"
    listener._handle_datagram(msg, (HOST2, 4244))

    on_packet2.assert_called_once()
    on_packet1.assert_not_called()


async def test_packet_from_unknown_ip_is_ignored():
    listener = make_listener()
    on_packet = MagicMock()
    listener.register(HOST1, on_packet, make_client())

    msg = "COMMAND:GET\r\nPOWER_STATUS\r\nID:HA\r\nPOWER:ON\r\nRESPONSE:ACK\r\n"
    listener._handle_datagram(msg, ("10.0.0.99", 4244))  # Unknown IP

    on_packet.assert_not_called()


async def test_notification_routed_to_correct_device():
    """A NOTIFICATION from HOST2 triggers HOST2's client and on_notification."""
    listener = make_listener()
    client1 = make_client()
    client2 = make_client()
    on_notif1 = MagicMock()
    on_notif2 = MagicMock()
    listener.register(HOST1, MagicMock(), client1, on_notif1)
    listener.register(HOST2, MagicMock(), client2, on_notif2)

    msg = f"COMMAND:NOTIFICATION\r\nIP:{HOST2}\r\nEVENT:VOLUME_CHANGED\r\nRESPONSE:ACK\r\n"
    listener._handle_datagram(msg, (HOST2, 4244))
    await asyncio.sleep(0)

    client2.send_get.assert_called_once_with("VOLUME")
    on_notif2.assert_called_once_with("VOLUME_CHANGED")
    client1.send_get.assert_not_called()
    on_notif1.assert_not_called()


# ===========================================================================
# SharedUDPListener – notification follow-up GETs
# ===========================================================================


async def test_notification_volume_changed_sends_get_volume():
    listener = make_listener()
    client = make_client()
    listener.register(HOST1, MagicMock(), client)

    msg = f"COMMAND:NOTIFICATION\r\nIP:{HOST1}\r\nEVENT:VOLUME_CHANGED\r\nRESPONSE:ACK\r\n"
    listener._handle_datagram(msg, (HOST1, 4244))
    await asyncio.sleep(0)

    client.send_get.assert_called_once_with("VOLUME")


async def test_notification_station_changed_sends_get_playing_mode():
    listener = make_listener()
    client = make_client()
    listener.register(HOST1, MagicMock(), client)

    msg = f"COMMAND:NOTIFICATION\r\nIP:{HOST1}\r\nEVENT:STATION_CHANGED\r\nRESPONSE:ACK\r\n"
    listener._handle_datagram(msg, (HOST1, 4244))
    await asyncio.sleep(0)

    client.send_get.assert_called_once_with("PLAYING_MODE")


async def test_notification_url_is_playing_sends_get_playing_mode():
    listener = make_listener()
    client = make_client()
    listener.register(HOST1, MagicMock(), client)

    msg = f"COMMAND:NOTIFICATION\r\nIP:{HOST1}\r\nEVENT:URL_IS_PLAYING\r\nRESPONSE:ACK\r\n"
    listener._handle_datagram(msg, (HOST1, 4244))
    await asyncio.sleep(0)

    client.send_get.assert_called_once_with("PLAYING_MODE")


async def test_notification_power_on_sends_get_power_status():
    listener = make_listener()
    client = make_client()
    listener.register(HOST1, MagicMock(), client)

    msg = f"COMMAND:NOTIFICATION\r\nIP:{HOST1}\r\nEVENT:POWER_ON\r\nRESPONSE:ACK\r\n"
    listener._handle_datagram(msg, (HOST1, 4244))
    await asyncio.sleep(0)

    client.send_get.assert_called_once_with("POWER_STATUS")


async def test_notification_power_off_sends_get_power_status():
    listener = make_listener()
    client = make_client()
    listener.register(HOST1, MagicMock(), client)

    msg = f"COMMAND:NOTIFICATION\r\nIP:{HOST1}\r\nEVENT:POWER_OFF\r\nRESPONSE:ACK\r\n"
    listener._handle_datagram(msg, (HOST1, 4244))
    await asyncio.sleep(0)

    client.send_get.assert_called_once_with("POWER_STATUS")


async def test_notification_unknown_event_does_not_raise():
    listener = make_listener()
    client = make_client()
    listener.register(HOST1, MagicMock(), client)

    msg = f"COMMAND:NOTIFICATION\r\nIP:{HOST1}\r\nEVENT:UNKNOWN_EVENT\r\nRESPONSE:ACK\r\n"
    listener._handle_datagram(msg, (HOST1, 4244))
    await asyncio.sleep(0)

    client.send_get.assert_not_called()


async def test_notification_does_not_call_on_packet():
    on_packet = MagicMock()
    client = make_client()
    listener = make_listener()
    listener.register(HOST1, on_packet, client)

    msg = f"COMMAND:NOTIFICATION\r\nIP:{HOST1}\r\nEVENT:VOLUME_CHANGED\r\nRESPONSE:ACK\r\n"
    listener._handle_datagram(msg, (HOST1, 4244))
    await asyncio.sleep(0)

    on_packet.assert_not_called()


# ===========================================================================
# _UDPProtocol – low-level protocol tests
# ===========================================================================


async def test_invalid_utf8_datagram_does_not_raise():
    handler = MagicMock()
    protocol = _UDPProtocol(handler)
    protocol.datagram_received(b"\xff\xfe invalid utf-8", ("192.168.1.1", 4242))
    # No exception should propagate


async def test_protocol_error_received_does_not_raise():
    protocol = _UDPProtocol(MagicMock())
    protocol.error_received(OSError("test error"))


async def test_protocol_connection_lost_with_exc_does_not_raise():
    protocol = _UDPProtocol(MagicMock())
    protocol.connection_lost(OSError("test"))


async def test_protocol_connection_lost_without_exc_does_not_raise():
    protocol = _UDPProtocol(MagicMock())
    protocol.connection_lost(None)
