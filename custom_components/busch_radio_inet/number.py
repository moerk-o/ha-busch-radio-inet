"""Number entities for Busch-Radio iNet HTTP settings."""

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .http_coordinator import HttpSettingsCoordinator


class _HttpSettingsNumber(CoordinatorEntity[HttpSettingsCoordinator], NumberEntity):
    """Base class for all HTTP settings number entities."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX

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
    def native_value(self) -> float | None:
        val = self.coordinator.data.get(self._key)
        if val is None:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set({self._key: str(int(value))})


class BrightnessNumber(_HttpSettingsNumber):
    """LCD backlight brightness (0–100 %)."""

    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "%"

    def __init__(self, coordinator: HttpSettingsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "bb", "Brightness")


class ContrastNumber(_HttpSettingsNumber):
    """LCD contrast (0–100 %)."""

    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "%"

    def __init__(self, coordinator: HttpSettingsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "co", "Contrast")


class TimezoneNumber(_HttpSettingsNumber):
    """Timezone offset (-12..+12 h, integers only).

    Note: Half-hour offsets (e.g. India +5.5, Australia +9.5) are not supported
    by the device – it only accepts integer values for the 'tz' field.
    """

    _attr_native_min_value = -12
    _attr_native_max_value = 12
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "h"

    def __init__(self, coordinator: HttpSettingsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "tz", "Timezone")


class ShortTimerDurationNumber(_HttpSettingsNumber):
    """Short timer duration (minutes)."""

    _attr_native_min_value = 0
    _attr_native_max_value = 120
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "min"

    def __init__(self, coordinator: HttpSettingsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "st", "Short Timer Duration")


class SleepTimerDurationNumber(_HttpSettingsNumber):
    """Sleep timer duration (minutes)."""

    _attr_native_min_value = 0
    _attr_native_max_value = 120
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "min"

    def __init__(self, coordinator: HttpSettingsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "ss", "Sleep Timer Duration")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up number entities for HTTP settings."""
    coordinator: HttpSettingsCoordinator = hass.data[DOMAIN][entry.entry_id][
        "http_coordinator"
    ]
    async_add_entities(
        [
            BrightnessNumber(coordinator, entry),
            ContrastNumber(coordinator, entry),
            TimezoneNumber(coordinator, entry),
            ShortTimerDurationNumber(coordinator, entry),
            SleepTimerDurationNumber(coordinator, entry),
        ]
    )
