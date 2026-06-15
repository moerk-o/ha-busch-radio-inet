"""Tests for BuschRadioCoordinator."""

import asyncio

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
    assert coord.mac_address is None


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
        "MAC": "78:C4:0E:33:74:5C",
        "RESPONSE": "ACK",
    })
    assert coord.serial_number == "78C40E33745C"
    assert coord.sw_version == "03.12"
    assert coord.device_name == "RADIO-INET3745C"
    assert coord.mac_address == "78:C4:0E:33:74:5C"


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


# ===========================================================================
# handle_packet – energy mode
# ===========================================================================


def test_handle_packet_energy_mode():
    coord, _, _ = make_coordinator()
    cb = MagicMock()
    coord.register_callback(cb)
    coord.handle_packet({"ENERGY_MODE": "ECO"})
    assert coord.energy_mode == "ECO"
    cb.assert_called_once()


def test_handle_packet_energy_mode_no_change_no_callback():
    coord, _, _ = make_coordinator()
    coord.energy_mode = "PREMIUM"
    cb = MagicMock()
    coord.register_callback(cb)
    coord.handle_packet({"ENERGY_MODE": "PREMIUM"})
    cb.assert_not_called()


# ===========================================================================
# set_media_title / set_media_image
# ===========================================================================


def test_set_media_title_updates_and_notifies():
    # No artwork client attached -> _schedule_artwork_lookup returns early.
    coord, _, _ = make_coordinator()
    cb = MagicMock()
    coord.register_callback(cb)
    coord.set_media_title("Queen - Bohemian Rhapsody")
    assert coord.media_title == "Queen - Bohemian Rhapsody"
    cb.assert_called_once()


def test_set_media_title_no_change_no_callback():
    coord, _, _ = make_coordinator()
    coord.media_title = "Same"
    cb = MagicMock()
    coord.register_callback(cb)
    coord.set_media_title("Same")
    cb.assert_not_called()


def test_set_media_image_updates_and_notifies():
    coord, _, _ = make_coordinator()
    cb = MagicMock()
    coord.register_callback(cb)
    coord.set_media_image("http://img.example/cover.jpg")
    assert coord.media_image_url == "http://img.example/cover.jpg"
    cb.assert_called_once()


def test_set_media_image_no_change_no_callback():
    coord, _, _ = make_coordinator()
    coord.media_image_url = "http://img.example/cover.jpg"
    cb = MagicMock()
    coord.register_callback(cb)
    coord.set_media_image("http://img.example/cover.jpg")
    cb.assert_not_called()


# ===========================================================================
# ICY fetcher attach / stop
# ===========================================================================


def test_set_and_stop_icy_fetcher():
    coord, _, _ = make_coordinator()
    fetcher = MagicMock()
    coord.set_icy_fetcher(fetcher)
    coord.stop_icy()
    fetcher.stop.assert_called_once()


def test_stop_icy_without_fetcher_is_safe():
    coord, _, _ = make_coordinator()
    coord.stop_icy()  # must not raise


# ===========================================================================
# Artwork task cancellation
# ===========================================================================


def test_stop_artwork_cancels_task():
    coord, _, _ = make_coordinator()
    task = MagicMock()
    coord._artwork_task = task
    coord.stop_artwork()
    task.cancel.assert_called_once()
    assert coord._artwork_task is None


def test_stop_artwork_without_task_is_safe():
    coord, _, _ = make_coordinator()
    coord.stop_artwork()  # must not raise


# ===========================================================================
# start_icy_if_playing
# ===========================================================================


def test_start_icy_if_playing_starts_when_playing():
    coord, _, _ = make_coordinator()
    fetcher = MagicMock()
    coord.set_icy_fetcher(fetcher)
    coord.power = True
    coord.station_id = 2
    coord.station_list = [{"id": 2, "name": "NDR", "url": "http://ndr.example"}]
    coord.start_icy_if_playing()
    fetcher.start.assert_called_once_with("http://ndr.example")


def test_start_icy_if_playing_does_nothing_when_off():
    coord, _, _ = make_coordinator()
    fetcher = MagicMock()
    coord.set_icy_fetcher(fetcher)
    coord.power = False
    coord.station_id = 2
    coord.start_icy_if_playing()
    fetcher.start.assert_not_called()


# ===========================================================================
# handle_notification dispatch
# ===========================================================================


def test_handle_notification_station_changed_stops_fetcher():
    coord, _, _ = make_coordinator()
    fetcher = MagicMock()
    coord.set_icy_fetcher(fetcher)
    coord.handle_notification("STATION_CHANGED")
    fetcher.stop.assert_called_once()


def test_handle_notification_url_is_playing_starts_fetcher():
    coord, _, _ = make_coordinator()
    fetcher = MagicMock()
    coord.set_icy_fetcher(fetcher)
    coord.station_id = 2
    coord.station_list = [{"id": 2, "name": "NDR", "url": "http://ndr.example"}]
    coord.handle_notification("URL_IS_PLAYING")
    fetcher.start.assert_called_once_with("http://ndr.example")


def test_handle_notification_url_is_playing_unknown_station_does_not_start():
    coord, _, _ = make_coordinator()
    fetcher = MagicMock()
    coord.set_icy_fetcher(fetcher)
    coord.station_id = 99  # not present in the station list
    coord.station_list = [{"id": 2, "name": "NDR", "url": "http://ndr.example"}]
    coord.handle_notification("URL_IS_PLAYING")
    fetcher.start.assert_not_called()


def test_handle_notification_power_off_stops_fetcher_and_clears():
    coord, _, _ = make_coordinator()
    fetcher = MagicMock()
    coord.set_icy_fetcher(fetcher)
    coord.media_title = "Queen - X"
    coord.media_image_url = "http://img"
    coord.handle_notification("POWER_OFF")
    fetcher.stop.assert_called_once()
    assert coord.media_title is None
    assert coord.media_image_url is None


def test_handle_notification_unknown_event_is_ignored():
    coord, _, _ = make_coordinator()
    coord.handle_notification("SOMETHING_ELSE")  # must not raise


# ===========================================================================
# _schedule_artwork_lookup
# ===========================================================================


def test_schedule_artwork_lookup_cancels_previous_and_bumps_generation():
    coord, hass, _ = make_coordinator()
    coord.set_artwork_client(MagicMock())
    old_task = MagicMock()
    coord._artwork_task = old_task

    created = []

    def fake_create_task(coro):
        coro.close()  # avoid "coroutine was never awaited" warning
        new_task = MagicMock()
        created.append(new_task)
        return new_task

    hass.async_create_task = MagicMock(side_effect=fake_create_task)

    gen_before = coord._artwork_generation
    coord._schedule_artwork_lookup()

    old_task.cancel.assert_called_once()
    assert coord._artwork_generation == gen_before + 1
    assert coord._artwork_task is created[0]


def test_schedule_artwork_lookup_without_client_is_noop():
    coord, hass, _ = make_coordinator()
    hass.async_create_task = MagicMock()
    coord._schedule_artwork_lookup()  # no artwork client
    hass.async_create_task.assert_not_called()


# ===========================================================================
# _async_artwork_lookup (Tier 1 music + Tier 2 station logo)
# ===========================================================================


def _artwork_coord(title=None, station=("NDR", 2, "http://ndr.example")):
    """Build a coordinator with an attached artwork client mock."""
    coord, _, _ = make_coordinator()
    client = MagicMock()
    client.fetch_music_artwork = AsyncMock(return_value=None)
    client.fetch_station_logo = AsyncMock(return_value=None)
    coord.set_artwork_client(client)
    coord.media_title = title
    name, sid, url = station
    coord.station_name = name
    coord.station_id = sid
    coord.station_list = [{"id": sid, "name": name, "url": url}]
    coord._artwork_generation = 1
    return coord, client


async def test_artwork_lookup_tier1_dash_hit():
    coord, client = _artwork_coord(title="Queen - Bohemian Rhapsody")
    client.fetch_music_artwork.return_value = "http://art/cover.jpg"
    await coord._async_artwork_lookup(1)
    client.fetch_music_artwork.assert_awaited_once_with("Queen", "Bohemian Rhapsody")
    client.fetch_station_logo.assert_not_awaited()
    assert coord.media_image_url == "http://art/cover.jpg"


async def test_artwork_lookup_tier1_slash_hit():
    coord, client = _artwork_coord(title="Bohemian Rhapsody / Queen")
    client.fetch_music_artwork.return_value = "http://art/cover.jpg"
    await coord._async_artwork_lookup(1)
    client.fetch_music_artwork.assert_awaited_once_with("Queen", "Bohemian Rhapsody")
    assert coord.media_image_url == "http://art/cover.jpg"


async def test_artwork_lookup_tier1_miss_falls_back_to_station_logo():
    coord, client = _artwork_coord(title="Queen - Bohemian Rhapsody")
    client.fetch_music_artwork.return_value = None
    client.fetch_station_logo.return_value = "http://logo.png"
    await coord._async_artwork_lookup(1)
    client.fetch_station_logo.assert_awaited_once_with("http://ndr.example", "NDR")
    assert coord.media_image_url == "http://logo.png"


async def test_artwork_lookup_no_separator_uses_station_logo():
    coord, client = _artwork_coord(title="Just A Plain Title")
    client.fetch_station_logo.return_value = "http://logo.png"
    await coord._async_artwork_lookup(1)
    client.fetch_music_artwork.assert_not_awaited()
    client.fetch_station_logo.assert_awaited_once()
    assert coord.media_image_url == "http://logo.png"


async def test_artwork_lookup_ambiguous_separators_uses_station_logo():
    # Both " - " and " / " present -> ambiguous -> Tier 1 skipped.
    coord, client = _artwork_coord(title="A - B / C")
    client.fetch_station_logo.return_value = "http://logo.png"
    await coord._async_artwork_lookup(1)
    client.fetch_music_artwork.assert_not_awaited()
    assert coord.media_image_url == "http://logo.png"


async def test_artwork_lookup_stale_generation_does_not_write():
    coord, client = _artwork_coord(title="Queen - X")
    client.fetch_music_artwork.return_value = "http://art/cover.jpg"
    coord._artwork_generation = 10  # current generation
    await coord._async_artwork_lookup(9)  # stale -> result discarded
    assert coord.media_image_url is None


async def test_artwork_lookup_cancelled_is_swallowed():
    coord, client = _artwork_coord(title="Queen - X")
    client.fetch_music_artwork.side_effect = asyncio.CancelledError
    await coord._async_artwork_lookup(1)  # must not raise
    assert coord.media_image_url is None


async def test_artwork_lookup_logo_without_station_id():
    # station_id is falsy -> _get_current_stream_url returns None.
    coord, client = _artwork_coord(title="Just A Title", station=("NDR", None, ""))
    client.fetch_station_logo.return_value = None
    await coord._async_artwork_lookup(1)
    client.fetch_station_logo.assert_awaited_once_with(None, "NDR")
    assert coord.media_image_url is None
