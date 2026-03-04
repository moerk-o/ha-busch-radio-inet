"""Select entities for Busch-Radio iNet HTTP settings."""

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .http_coordinator import HttpSettingsCoordinator


class _HttpSettingsSelect(CoordinatorEntity[HttpSettingsCoordinator], SelectEntity):
    """Base class for all HTTP settings select entities."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True

    # Subclasses must define these
    _VALUE_TO_OPTION: dict[str, str] = {}
    _OPTION_TO_VALUE: dict[str, str] = {}

    def __init__(
        self,
        coordinator: HttpSettingsCoordinator,
        entry: ConfigEntry,
        key: str,
        name: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._key = key
        self._attr_name = name
        self._attr_unique_id = f"{entry.unique_id}_http_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry.unique_id)})

    @property
    def current_option(self) -> str | None:
        val = self.coordinator.data.get(self._key)
        return self._VALUE_TO_OPTION.get(val)

    @property
    def options(self) -> list[str]:
        return list(self._VALUE_TO_OPTION.values())

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set({self._key: self._OPTION_TO_VALUE[option]})


class BacklightSelect(_HttpSettingsSelect):
    """LCD backlight mode."""

    _VALUE_TO_OPTION = {"0": "Off", "1": "On", "2": "Auto"}
    _OPTION_TO_VALUE = {v: k for k, v in _VALUE_TO_OPTION.items()}

    def __init__(self, coordinator: HttpSettingsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "bl", "Backlight")


class DisplayModeSelect(_HttpSettingsSelect):
    """LCD display mode (normal / inverted)."""

    _VALUE_TO_OPTION = {"0": "Normal", "1": "Inverted"}
    _OPTION_TO_VALUE = {v: k for k, v in _VALUE_TO_OPTION.items()}

    def __init__(self, coordinator: HttpSettingsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "dm", "Display Mode")


class AudioModeSelect(_HttpSettingsSelect):
    """Audio output mode (mono / stereo)."""

    _VALUE_TO_OPTION = {"0": "Mono", "1": "Stereo"}
    _OPTION_TO_VALUE = {v: k for k, v in _VALUE_TO_OPTION.items()}

    def __init__(self, coordinator: HttpSettingsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "ms", "Audio Mode")


class SoundModeSelect(_HttpSettingsSelect):
    """Sound equalizer preset."""

    _VALUE_TO_OPTION = {
        "0": "Rock",
        "1": "Jazz",
        "2": "Classic",
        "3": "Electro",
        "4": "Speech",
    }
    _OPTION_TO_VALUE = {v: k for k, v in _VALUE_TO_OPTION.items()}

    def __init__(self, coordinator: HttpSettingsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "sm", "Sound Mode")


class LanguageSelect(_HttpSettingsSelect):
    """Device display language."""

    _VALUE_TO_OPTION = {
        "de": "Deutsch",
        "en": "English",
        "fr": "Français",
        "nl": "Nederlands",
        "es": "Español",
        "sv": "Svenska",
        "no": "Norsk",
        "fi": "Suomi",
        "it": "Italiano",
        "pl": "Polski",
        "ru": "Русский",
    }
    _OPTION_TO_VALUE = {v: k for k, v in _VALUE_TO_OPTION.items()}

    def __init__(self, coordinator: HttpSettingsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "ln", "Language")


class TimeSourceSelect(_HttpSettingsSelect):
    """Time synchronisation source (Internet / Manual)."""

    _VALUE_TO_OPTION = {"0": "Internet", "1": "Manual"}
    _OPTION_TO_VALUE = {v: k for k, v in _VALUE_TO_OPTION.items()}

    def __init__(self, coordinator: HttpSettingsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "zs", "Time Source")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up select entities for HTTP settings."""
    coordinator: HttpSettingsCoordinator = hass.data[DOMAIN][entry.entry_id][
        "http_coordinator"
    ]
    async_add_entities(
        [
            BacklightSelect(coordinator, entry),
            DisplayModeSelect(coordinator, entry),
            AudioModeSelect(coordinator, entry),
            SoundModeSelect(coordinator, entry),
            LanguageSelect(coordinator, entry),
            TimeSourceSelect(coordinator, entry),
        ]
    )
