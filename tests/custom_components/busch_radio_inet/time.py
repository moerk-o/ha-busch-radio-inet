"""Time entities for Busch-Radio iNet HTTP settings."""

from datetime import time as dt_time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .http_coordinator import HttpSettingsCoordinator


class _HttpSettingsTime(CoordinatorEntity[HttpSettingsCoordinator], TimeEntity):
    """Base class for time entities that combine two device fields (hour + minute)."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HttpSettingsCoordinator,
        entry: ConfigEntry,
        hour_key: str,
        minute_key: str,
        name: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._hour_key = hour_key
        self._minute_key = minute_key
        self._attr_name = name
        self._attr_unique_id = f"{entry.unique_id}_http_{hour_key}_{minute_key}"

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data is not None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry.unique_id)})

    @property
    def native_value(self) -> dt_time | None:
        data = self.coordinator.data
        try:
            hour = int(data.get(self._hour_key, 0))
            minute = int(data.get(self._minute_key, 0))
            return dt_time(hour, minute)
        except (ValueError, TypeError):
            return None

    async def async_set_value(self, value: dt_time) -> None:
        await self.coordinator.async_set(
            {
                self._hour_key: str(value.hour),
                self._minute_key: str(value.minute),
            }
        )


class LocalTimeTime(_HttpSettingsTime):
    """Local device time (only meaningful when Time Source = Manual).

    The device ignores this value when Internet time sync is active (zs=0).
    """

    def __init__(self, coordinator: HttpSettingsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "hr", "mi", "Local Time")


class AlarmTimeTime(_HttpSettingsTime):
    """Alarm time (hour + minute)."""

    def __init__(self, coordinator: HttpSettingsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "ah", "am", "Alarm Time")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up time entities for HTTP settings."""
    coordinator: HttpSettingsCoordinator = hass.data[DOMAIN][entry.entry_id][
        "http_coordinator"
    ]
    async_add_entities(
        [
            LocalTimeTime(coordinator, entry),
            AlarmTimeTime(coordinator, entry),
        ]
    )
