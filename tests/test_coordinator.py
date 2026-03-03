"""Tests for BuschRadioCoordinator."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.busch_radio_inet.coordinator import BuschRadioCoordinator


def make_coordinator(hass=None, client=None):
    if hass is None:
        hass = MagicMock()
    if client is None:
        client = MagicMock()
        client.send_get = AsyncMock()
    return BuschRadioCoordinator(hass, client), hass, client


# ===========================================================================
# Initial state
# ===========================================================================


def test_initial_state_all_none():
    coord, _, _ = make_coordinator()
    assert coord.power is None
    assert coord.volume is None
    assert coord.muted is False
    assert coord.station_id is None
    assert coord.station_name is None
    assert coord.station_list == []
    assert coord.device_name is None
    assert coord.sw_version is None
    assert coord.serial_number is None


def test_is_ready_false_before_data():
    coord, _, _ = make_coordinator()
    assert coord.is_ready is False


def test_is_ready_false_with_only_power():
    coord, _, _ = make_coordinator()
    coord.power = True
    assert coord.is_ready is False


def test_is_ready_false_with_only_volume():
    coord, _, _ = make_coordinator()
    coord.volume = 10
    assert coord.is_ready is False


def test_is_ready_true_when_power_and_volume_set():
    coord, _, _ = make_coordinator()
    coord.power = True
    coord.volume = 10
    assert coord.is_ready is True


# ===========================================================================
# handle_packet – power
# ===========================================================================


def test_handle_packet_power_on():
    coord, _, _ = make_coordinator()
    coord.handle_packet({"POWER": "ON", "RESPONSE": "ACK"})
    assert coord.power is True


def test_handle_packet_power_off():
    coord, _, _ = make_coordinator()
    coord.handle_packet({"POWER": "OFF", "RESPONSE": "ACK"})
    assert coord.power is False


def test_handle_packet_set_radio_on_ack():
    coord, _, _ = make_coordinator()
    coord.handle_packet({"COMMAND": "SET", "_parameter": "RADIO_ON", "RESPONSE": "ACK"})
    assert coord.power is True


def test_handle_packet_set_radio_off_ack():
    coord, _, _ = make_coordinator()
    coord.power = True
    coord.handle_packet({"COMMAND": "SET", "_parameter": "RADIO_OFF", "RESPONSE": "ACK"})
    assert coord.power is False


def test_handle_packet_nack_ignored():
    coord, _, _ = make_coordinator()
    coord.power = True
    coord.handle_packet({"COMMAND": "SET", "_parameter": "RADIO_OFF", "RESPONSE": "NACK"})
    assert coord.power is True  # unchanged


# ===========================================================================
# handle_packet – volume
# ===========================================================================


def test_handle_packet_volume():
    coord, _, _ = make_coordinator()
    coord.handle_packet({"VOLUME_SET": "18", "RESPONSE": "ACK"})
    assert coord.volume == 18


def test_handle_packet_volume_zero():
    coord, _, _ = make_coordinator()
    coord.handle_packet({"VOLUME_SET": "0", "RESPONSE": "ACK"})
    assert coord.volume == 0


def test_handle_packet_volume_max():
    coord, _, _ = make_coordinator()
    coord.handle_packet({"VOLUME_SET": "31", "RESPONSE": "ACK"})
    assert coord.volume == 31


def test_handle_packet_invalid_volume_does_not_raise():
    coord, _, _ = make_coordinator()
    coord.handle_packet({"VOLUME_SET": "not_a_number"})
    assert coord.volume is None


# ===========================================================================
# handle_packet – playing mode
# ===========================================================================


def test_handle_packet_playing_station():
    coord, _, _ = make_coordinator()
    coord.handle_packet({
        "PLAYING": "STATION",
        "ID": "2",
        "NAME": "NDR 90.3",
        "URL": "http://ndr.example.com",
        "RESPONSE": "ACK",
    })
    assert coord.station_id == 2
    assert coord.station_name == "NDR 90.3"


def test_handle_packet_playing_stopped():
    coord, _, _ = make_coordinator()
    coord.station_id = 2
    coord.station_name = "NDR 90.3"
    coord.handle_packet({"MODE": "PLAYING STOPPED", "RESPONSE": "ACK"})
    assert coord.station_id is None
    assert coord.station_name is None


def test_handle_packet_invalid_station_id_does_not_raise():
    coord, _, _ = make_coordinator()
    coord.handle_packet({"PLAYING": "STATION", "ID": "bad", "NAME": "Test"})
    assert coord.station_id is None


# ===========================================================================
# handle_packet – station list
# ===========================================================================


def test_handle_packet_station_list():
    coord, _, _ = make_coordinator()
    stations = [
        {"id": 1, "name": "WDR 2", "url": "http://wdr2.example.com"},
        {"id": 2, "name": "NDR 90.3", "url": "http://ndr.example.com"},
    ]
    coord.handle_packet({"_stations": stations})
    assert coord.station_list == stations


def test_handle_packet_empty_station_list():
    coord, _, _ = make_coordinator()
    coord.handle_packet({"_stations": []})
    assert coord.station_list == []


# ===========================================================================
# handle_packet – device info
# ===========================================================================


def test_handle_packet_info_block():
    coord, _, _ = make_coordinator()
    coord.handle_packet({
        "SERNO": "78C40E33745C",
        "SW-VERSION": "03.12",
        "NAME": "RADIO-INET3745C",
        "IPADDR": "192.168.1.179",
        "RESPONSE": "ACK",
    })
    assert coord.serial_number == "78C40E33745C"
    assert coord.sw_version == "03.12"
    assert coord.device_name == "RADIO-INET3745C"


# ===========================================================================
# Callbacks
# ===========================================================================


def test_callback_called_on_change():
    coord, _, _ = make_coordinator()
    cb = MagicMock()
    coord.register_callback(cb)
    coord.handle_packet({"POWER": "ON"})
    cb.assert_called_once()


def test_callback_not_called_when_nothing_changes():
    coord, _, _ = make_coordinator()
    coord.power = True
    cb = MagicMock()
    coord.register_callback(cb)
    coord.handle_packet({"POWER": "ON"})  # Same value
    cb.assert_not_called()


def test_callback_not_called_on_nack():
    coord, _, _ = make_coordinator()
    cb = MagicMock()
    coord.register_callback(cb)
    coord.handle_packet({"RESPONSE": "NACK"})
    cb.assert_not_called()


def test_multiple_callbacks_all_called():
    coord, _, _ = make_coordinator()
    cb1, cb2 = MagicMock(), MagicMock()
    coord.register_callback(cb1)
    coord.register_callback(cb2)
    coord.handle_packet({"POWER": "ON"})
    cb1.assert_called_once()
    cb2.assert_called_once()


def test_unregister_callback():
    coord, _, _ = make_coordinator()
    cb = MagicMock()
    coord.register_callback(cb)
    coord.unregister_callback(cb)
    coord.handle_packet({"POWER": "ON"})
    cb.assert_not_called()


# ===========================================================================
# set_muted
# ===========================================================================


def test_set_muted_true():
    coord, _, _ = make_coordinator()
    cb = MagicMock()
    coord.register_callback(cb)
    coord.set_muted(True)
    assert coord.muted is True
    cb.assert_called_once()


def test_set_muted_false():
    coord, _, _ = make_coordinator()
    coord.muted = True
    cb = MagicMock()
    coord.register_callback(cb)
    coord.set_muted(False)
    assert coord.muted is False
    cb.assert_called_once()


def test_set_muted_no_change_no_callback():
    coord, _, _ = make_coordinator()
    cb = MagicMock()
    coord.register_callback(cb)
    coord.set_muted(False)  # Already False
    cb.assert_not_called()


# ===========================================================================
# Polling
# ===========================================================================


def test_start_polling_calls_async_track_time_interval():
    coord, hass, _ = make_coordinator()
    mock_cancel = MagicMock()
    with patch(
        "custom_components.busch_radio_inet.coordinator.async_track_time_interval",
        return_value=mock_cancel,
    ) as mock_track:
        coord.start_polling()
        mock_track.assert_called_once()
        assert coord._cancel_poll is mock_cancel


def test_stop_polling_cancels_subscription():
    coord, hass, _ = make_coordinator()
    mock_cancel = MagicMock()
    with patch(
        "custom_components.busch_radio_inet.coordinator.async_track_time_interval",
        return_value=mock_cancel,
    ):
        coord.start_polling()
        coord.stop_polling()
        mock_cancel.assert_called_once()
        assert coord._cancel_poll is None


def test_stop_polling_when_not_started_is_safe():
    coord, _, _ = make_coordinator()
    coord.stop_polling()  # Must not raise


async def test_async_poll_sends_three_gets():
    coord, _, client = make_coordinator()
    await coord._async_poll()
    assert client.send_get.call_count == 3
    calls = [c[0][0] for c in client.send_get.call_args_list]
    assert "POWER_STATUS" in calls
    assert "VOLUME" in calls
    assert "PLAYING_MODE" in calls


# ===========================================================================
# playing_stopped when already cleared (no callback expected)
# ===========================================================================


def test_playing_stopped_when_already_none_no_callback():
    coord, _, _ = make_coordinator()
    cb = MagicMock()
    coord.register_callback(cb)
    coord.handle_packet({"MODE": "PLAYING STOPPED"})  # station_id already None
    cb.assert_not_called()
