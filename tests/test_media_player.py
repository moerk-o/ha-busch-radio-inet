"""Tests for BuschRadioMediaPlayer."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.media_player import (
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.core import HomeAssistant

from custom_components.busch_radio_inet.coordinator import BuschRadioCoordinator
from custom_components.busch_radio_inet.media_player import (
    BuschRadioMediaPlayer,
    SUPPORTED_FEATURES,
)
from custom_components.busch_radio_inet.const import DOMAIN, MAX_VOLUME


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def make_entry(serial="78C40E33745C", name="Busch-Radio iNet"):
    entry = MagicMock()
    entry.unique_id = serial
    entry.data = {"name": name, "host": "192.168.1.179", "port": 4244}
    entry.entry_id = "test_entry_id"
    return entry


def make_coordinator(**kwargs):
    coord = MagicMock(spec=BuschRadioCoordinator)
    coord.power = kwargs.get("power", None)
    coord.volume = kwargs.get("volume", None)
    coord.muted = kwargs.get("muted", False)
    coord.station_id = kwargs.get("station_id", None)
    coord.station_name = kwargs.get("station_name", None)
    coord.station_list = kwargs.get("station_list", [])
    coord.sw_version = kwargs.get("sw_version", "03.12")
    coord.serial_number = kwargs.get("serial_number", "78C40E33745C")
    coord.is_ready = kwargs.get("is_ready", True)
    coord.media_title = kwargs.get("media_title", None)
    coord.media_image_url = kwargs.get("media_image_url", None)
    coord.register_callback = MagicMock()
    coord.unregister_callback = MagicMock()
    coord.set_muted = MagicMock()
    return coord


def make_client():
    client = MagicMock()
    client.send_set = AsyncMock()
    client.send_play = AsyncMock()
    return client


def make_player(**coord_kwargs):
    coord = make_coordinator(**coord_kwargs)
    client = make_client()
    entry = make_entry()
    player = BuschRadioMediaPlayer(coord, client, entry)
    return player, coord, client


STATION_LIST = [
    {"id": 1, "name": "WDR 2", "url": "http://wdr2.example.com"},
    {"id": 2, "name": "NDR 90.3", "url": "http://ndr.example.com"},
    {"id": 3, "name": "Rock Radio", "url": "http://rock.example.com"},
]


# ===========================================================================
# Supported features
# ===========================================================================


def test_supported_features_includes_required_flags():
    assert SUPPORTED_FEATURES & MediaPlayerEntityFeature.TURN_ON
    assert SUPPORTED_FEATURES & MediaPlayerEntityFeature.TURN_OFF
    assert SUPPORTED_FEATURES & MediaPlayerEntityFeature.VOLUME_SET
    assert SUPPORTED_FEATURES & MediaPlayerEntityFeature.VOLUME_STEP
    assert SUPPORTED_FEATURES & MediaPlayerEntityFeature.VOLUME_MUTE
    assert SUPPORTED_FEATURES & MediaPlayerEntityFeature.SELECT_SOURCE


def test_supported_features_excludes_play_pause():
    assert not (SUPPORTED_FEATURES & MediaPlayerEntityFeature.PLAY)
    assert not (SUPPORTED_FEATURES & MediaPlayerEntityFeature.PAUSE)


# ===========================================================================
# Availability
# ===========================================================================


def test_available_when_coordinator_is_ready():
    player, _, _ = make_player(is_ready=True)
    assert player.available is True


def test_not_available_when_coordinator_not_ready():
    player, _, _ = make_player(is_ready=False)
    assert player.available is False


# ===========================================================================
# State
# ===========================================================================


def test_state_idle_when_power_true_no_station():
    player, _, _ = make_player(power=True, volume=10, is_ready=True)
    assert player.state == MediaPlayerState.IDLE


def test_state_playing_when_power_true_with_station():
    player, _, _ = make_player(power=True, station_name="NDR 90.3", is_ready=True)
    assert player.state == MediaPlayerState.PLAYING


def test_state_off_when_power_false():
    player, _, _ = make_player(power=False, volume=10, is_ready=True)
    assert player.state == MediaPlayerState.OFF


def test_state_none_when_not_ready():
    player, _, _ = make_player(is_ready=False)
    assert player.state is None


# ===========================================================================
# Volume
# ===========================================================================


def test_volume_level_converts_raw_to_float():
    player, _, _ = make_player(volume=0)
    assert player.volume_level == pytest.approx(0.0)

    player, _, _ = make_player(volume=MAX_VOLUME)
    assert player.volume_level == pytest.approx(1.0)

    player, _, _ = make_player(volume=15)
    assert player.volume_level == pytest.approx(15 / MAX_VOLUME)


def test_volume_level_none_when_volume_not_set():
    player, coord, _ = make_player()
    coord.volume = None
    assert player.volume_level is None


def test_is_volume_muted_false_by_default():
    player, _, _ = make_player(muted=False)
    assert player.is_volume_muted is False


def test_is_volume_muted_true_when_muted():
    player, _, _ = make_player(muted=True)
    assert player.is_volume_muted is True


# ===========================================================================
# Source / station
# ===========================================================================


def test_source_returns_station_name():
    player, _, _ = make_player(station_name="NDR 90.3")
    assert player.source == "NDR 90.3"


def test_source_none_when_not_playing():
    player, coord, _ = make_player()
    coord.station_name = None
    assert player.source is None


def test_source_list_returns_names():
    player, _, _ = make_player(station_list=STATION_LIST)
    assert player.source_list == ["WDR 2", "NDR 90.3", "Rock Radio"]


def test_source_list_empty_when_no_stations():
    player, _, _ = make_player(station_list=[])
    assert player.source_list == []


def test_media_title_returns_station_name():
    player, _, _ = make_player(station_name="Rock Radio")
    assert player.media_title == "Rock Radio"


def test_media_title_none_when_not_playing():
    player, coord, _ = make_player()
    coord.station_name = None
    assert player.media_title is None


# ===========================================================================
# Device info
# ===========================================================================


def test_device_info_contains_correct_identifiers():
    player, coord, _ = make_player()
    coord.sw_version = "03.12"
    info = player.device_info
    assert (DOMAIN, "78C40E33745C") in info["identifiers"]


def test_device_info_contains_manufacturer():
    player, _, _ = make_player()
    info = player.device_info
    assert "Busch-Jäger" in info["manufacturer"]


def test_device_info_contains_model():
    player, _, _ = make_player()
    info = player.device_info
    assert info["model"] == "8216 U"


def test_device_info_contains_sw_version():
    player, coord, _ = make_player()
    coord.sw_version = "03.12"
    info = player.device_info
    assert info["sw_version"] == "03.12"


# ===========================================================================
# async_added_to_hass / async_will_remove_from_hass
# ===========================================================================


async def test_added_to_hass_registers_callback():
    player, coord, _ = make_player()
    await player.async_added_to_hass()
    coord.register_callback.assert_called_once_with(player.async_write_ha_state)


async def test_will_remove_from_hass_unregisters_callback():
    player, coord, _ = make_player()
    await player.async_will_remove_from_hass()
    coord.unregister_callback.assert_called_once_with(player.async_write_ha_state)


# ===========================================================================
# Commands – turn on/off
# ===========================================================================


async def test_turn_on_sends_radio_on():
    player, _, client = make_player()
    await player.async_turn_on()
    client.send_set.assert_called_once_with("RADIO_ON")


async def test_turn_off_sends_radio_off():
    player, _, client = make_player()
    await player.async_turn_off()
    client.send_set.assert_called_once_with("RADIO_OFF")


# ===========================================================================
# Commands – volume
# ===========================================================================


async def test_set_volume_level_converts_and_sends():
    player, _, client = make_player()
    await player.async_set_volume_level(0.5)
    raw = round(0.5 * MAX_VOLUME)
    client.send_set.assert_called_once_with(f"VOLUME_ABSOLUTE:{raw}")


async def test_set_volume_level_zero():
    player, _, client = make_player()
    await player.async_set_volume_level(0.0)
    client.send_set.assert_called_once_with("VOLUME_ABSOLUTE:0")


async def test_set_volume_level_max():
    player, _, client = make_player()
    await player.async_set_volume_level(1.0)
    client.send_set.assert_called_once_with(f"VOLUME_ABSOLUTE:{MAX_VOLUME}")


async def test_set_volume_level_clamped_below_zero():
    player, _, client = make_player()
    await player.async_set_volume_level(-0.5)
    client.send_set.assert_called_once_with("VOLUME_ABSOLUTE:0")


async def test_set_volume_level_clamped_above_one():
    player, _, client = make_player()
    await player.async_set_volume_level(1.5)
    client.send_set.assert_called_once_with(f"VOLUME_ABSOLUTE:{MAX_VOLUME}")


async def test_volume_up_sends_volume_inc():
    player, _, client = make_player()
    await player.async_volume_up()
    client.send_set.assert_called_once_with("VOLUME_INC")


async def test_volume_down_sends_volume_dec():
    player, _, client = make_player()
    await player.async_volume_down()
    client.send_set.assert_called_once_with("VOLUME_DEC")


async def test_mute_volume_true_sends_volume_mute():
    player, coord, client = make_player()
    await player.async_mute_volume(True)
    client.send_set.assert_called_once_with("VOLUME_MUTE")
    coord.set_muted.assert_called_once_with(True)


async def test_mute_volume_false_sends_volume_unmute():
    player, coord, client = make_player()
    await player.async_mute_volume(False)
    client.send_set.assert_called_once_with("VOLUME_UNMUTE")
    coord.set_muted.assert_called_once_with(False)


# ===========================================================================
# Commands – select source
# ===========================================================================


async def test_select_source_sends_play_for_matching_station():
    player, coord, client = make_player(station_list=STATION_LIST)
    await player.async_select_source("NDR 90.3")
    client.send_play.assert_called_once_with("STATION:2")


async def test_select_source_first_station():
    player, coord, client = make_player(station_list=STATION_LIST)
    await player.async_select_source("WDR 2")
    client.send_play.assert_called_once_with("STATION:1")


async def test_select_source_unknown_name_does_not_send():
    player, coord, client = make_player(station_list=STATION_LIST)
    await player.async_select_source("Unknown Station")
    client.send_play.assert_not_called()


async def test_select_source_empty_station_list_does_not_crash():
    player, _, client = make_player(station_list=[])
    await player.async_select_source("WDR 2")
    client.send_play.assert_not_called()


# ===========================================================================
# Full integration test via hass (setup + entity creation)
# ===========================================================================


async def test_media_player_loads_via_hass(
    hass: HomeAssistant, mock_config_entry
) -> None:
    """The integration sets up cleanly and creates exactly one media_player."""
    with patch(
        "custom_components.busch_radio_inet.BuschRadioUDPListener"
    ) as mock_listener_cls, patch(
        "custom_components.busch_radio_inet.BuschRadioUDPClient"
    ) as mock_client_cls, patch(
        "custom_components.busch_radio_inet.coordinator.async_track_time_interval",
        return_value=MagicMock(),
    ), patch(
        "custom_components.busch_radio_inet.ArtworkClient"
    ):
        mock_listener = MagicMock()
        mock_listener.start = AsyncMock()
        mock_listener_cls.return_value = mock_listener

        mock_client = MagicMock()
        mock_client.send_get = AsyncMock()
        mock_client_cls.return_value = mock_client

        mock_config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    states = hass.states.async_all("media_player")
    assert len(states) == 1


async def test_media_player_unloads_cleanly(
    hass: HomeAssistant, mock_config_entry
) -> None:
    with patch(
        "custom_components.busch_radio_inet.BuschRadioUDPListener"
    ) as mock_listener_cls, patch(
        "custom_components.busch_radio_inet.BuschRadioUDPClient"
    ) as mock_client_cls, patch(
        "custom_components.busch_radio_inet.coordinator.async_track_time_interval",
        return_value=MagicMock(),
    ), patch(
        "custom_components.busch_radio_inet.ArtworkClient"
    ):
        mock_listener = MagicMock()
        mock_listener.start = AsyncMock()
        mock_listener.stop = MagicMock()
        mock_listener_cls.return_value = mock_listener

        mock_client = MagicMock()
        mock_client.send_get = AsyncMock()
        mock_client_cls.return_value = mock_client

        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    mock_listener.stop.assert_called_once()


async def test_media_player_raises_config_entry_not_ready_on_port_in_use(
    hass: HomeAssistant, mock_config_entry
) -> None:
    """If port 4242 is in use, ConfigEntryNotReady must be raised."""
    with patch(
        "custom_components.busch_radio_inet.BuschRadioUDPListener"
    ) as mock_listener_cls, patch(
        "custom_components.busch_radio_inet.BuschRadioUDPClient"
    ) as mock_client_cls, patch(
        "custom_components.busch_radio_inet.ArtworkClient"
    ):
        mock_listener = MagicMock()
        mock_listener.start = AsyncMock(side_effect=OSError("address in use"))
        mock_listener_cls.return_value = mock_listener

        mock_client = MagicMock()
        mock_client.send_get = AsyncMock()
        mock_client_cls.return_value = mock_client

        mock_config_entry.add_to_hass(hass)
        result = await hass.config_entries.async_setup(mock_config_entry.entry_id)

    assert result is False
