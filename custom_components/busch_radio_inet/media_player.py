"""Media player entity for Busch-Radio iNet."""

import logging
from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_NAME,
    DOMAIN,
    MANUFACTURER,
    MAX_VOLUME,
    MODEL,
)

_LOGGER = logging.getLogger(__name__)

SUPPORTED_FEATURES = (
    MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.SELECT_SOURCE
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Busch-Radio iNet media player from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    client = data["client"]

    async_add_entities(
        [BuschRadioMediaPlayer(coordinator, client, entry)],
        update_before_add=False,
    )


class BuschRadioMediaPlayer(MediaPlayerEntity):
    """Representation of a Busch-Radio iNet device as a media_player entity."""

    _attr_has_entity_name = True
    _attr_name = None  # Uses device name as entity name

    def __init__(self, coordinator, client, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._client = client
        self._entry = entry
        self._attr_unique_id = entry.unique_id
        self._attr_supported_features = SUPPORTED_FEATURES

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_added_to_hass(self) -> None:
        """Register callback so coordinator can push state updates."""
        self._coordinator.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister callback when entity is removed."""
        self._coordinator.unregister_callback(self.async_write_ha_state)

    # ------------------------------------------------------------------
    # Device info
    # ------------------------------------------------------------------

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.unique_id)},
            name=self._entry.data[CONF_NAME],
            manufacturer=MANUFACTURER,
            model=MODEL,
            sw_version=self._coordinator.sw_version,
        )

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """Entity is available once we have received power and volume state."""
        return self._coordinator.is_ready

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def state(self) -> MediaPlayerState | None:
        if not self._coordinator.is_ready:
            return None
        if not self._coordinator.power:
            return MediaPlayerState.OFF
        if self._coordinator.station_name:
            return MediaPlayerState.PLAYING
        return MediaPlayerState.IDLE

    # ------------------------------------------------------------------
    # Volume
    # ------------------------------------------------------------------

    @property
    def volume_level(self) -> float | None:
        if self._coordinator.volume is None:
            return None
        return self._coordinator.volume / MAX_VOLUME

    @property
    def is_volume_muted(self) -> bool:
        return self._coordinator.muted

    # ------------------------------------------------------------------
    # Source / station
    # ------------------------------------------------------------------

    @property
    def source(self) -> str | None:
        return self._coordinator.station_name

    @property
    def source_list(self) -> list[str]:
        return [s["name"] for s in self._coordinator.station_list]

    # ------------------------------------------------------------------
    # Media title / artist
    # ------------------------------------------------------------------

    @property
    def media_title(self) -> str | None:
        """Song title from ICY metadata, falling back to station name."""
        return self._coordinator.media_title or self._coordinator.station_name

    @property
    def media_artist(self) -> str | None:
        """Artist parsed from ICY StreamTitle when format is 'Artist - Title'."""
        title = self._coordinator.media_title
        if title and " - " in title:
            return title.split(" - ", 1)[0]
        return None

    @property
    def media_image_url(self) -> str | None:
        return self._coordinator.media_image_url

    @property
    def media_image_remotely_accessible(self) -> bool:
        return True

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def async_turn_on(self) -> None:
        await self._client.send_set("RADIO_ON")

    async def async_turn_off(self) -> None:
        await self._client.send_set("RADIO_OFF")

    async def async_set_volume_level(self, volume: float) -> None:
        raw = round(volume * MAX_VOLUME)
        raw = max(0, min(MAX_VOLUME, raw))
        await self._client.send_set(f"VOLUME_ABSOLUTE:{raw}")

    async def async_volume_up(self) -> None:
        await self._client.send_set("VOLUME_INC")

    async def async_volume_down(self) -> None:
        await self._client.send_set("VOLUME_DEC")

    async def async_mute_volume(self, mute: bool) -> None:
        if mute:
            await self._client.send_set("VOLUME_MUTE")
        else:
            await self._client.send_set("VOLUME_UNMUTE")
        self._coordinator.set_muted(mute)

    async def async_select_source(self, source: str) -> None:
        """Select a station by name."""
        for station in self._coordinator.station_list:
            if station["name"] == source:
                await self._client.send_play(f"STATION:{station['id']}")
                return
        _LOGGER.warning("Source '%s' not found in station list", source)
