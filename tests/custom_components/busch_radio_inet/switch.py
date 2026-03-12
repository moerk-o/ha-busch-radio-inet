"""Switch entities for Busch-Radio iNet HTTP settings."""

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .http_coordinator import HttpSettingsCoordinator


class _HttpSettingsSwitch(CoordinatorEntity[HttpSettingsCoordinator], SwitchEntity):
    """Base class for all HTTP settings switch entities (checkbox fields).

    Checkbox semantics: "1" = on, "" (empty string) = off.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True

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
    def available(self) -> bool:
        return super().available and self.coordinator.data is not None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry.unique_id)})

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.get(self._key) == "1"

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set({self._key: "1"})

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set({self._key: ""})


class AudioWorldSwitch(_HttpSettingsSwitch):
    """Audio World (exact function unknown, exposed as-is)."""

    def __init__(self, coordinator: HttpSettingsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "aw", "Audio World")


class DaylightSavingSwitch(_HttpSettingsSwitch):
    """Daylight saving time active."""

    def __init__(self, coordinator: HttpSettingsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "sz", "Daylight Saving")


class AlarmSwitch(_HttpSettingsSwitch):
    """Alarm enabled."""

    def __init__(self, coordinator: HttpSettingsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "ea", "Alarm")


class ShortTimerSwitch(_HttpSettingsSwitch):
    """Short timer active."""

    def __init__(self, coordinator: HttpSettingsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "et", "Short Timer")


class SleepTimerSwitch(_HttpSettingsSwitch):
    """Sleep timer active."""

    def __init__(self, coordinator: HttpSettingsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "es", "Sleep Timer")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switch entities for HTTP settings."""
    coordinator: HttpSettingsCoordinator = hass.data[DOMAIN][entry.entry_id][
        "http_coordinator"
    ]
    async_add_entities(
        [
            AudioWorldSwitch(coordinator, entry),
            DaylightSavingSwitch(coordinator, entry),
            AlarmSwitch(coordinator, entry),
            ShortTimerSwitch(coordinator, entry),
            SleepTimerSwitch(coordinator, entry),
        ]
    )
