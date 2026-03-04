"""Sensor entities for Busch-Radio iNet HTTP settings (read-only diagnostics)."""

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .http_coordinator import HttpSettingsCoordinator


class _HttpSettingsSensor(CoordinatorEntity[HttpSettingsCoordinator], SensorEntity):
    """Base class for read-only HTTP settings sensor entities."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True

    _VALUE_TO_STATE: dict[str, str] = {}

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
    def native_value(self) -> str | None:
        raw = self.coordinator.data.get(self._key)
        if raw is None:
            return None
        return self._VALUE_TO_STATE.get(raw, raw)


class SwitchInputSensor(_HttpSettingsSensor):
    """Switch input function (sw): Switch / Button / Automatic."""

    _VALUE_TO_STATE = {"0": "Switch", "1": "Button", "2": "Automatic"}

    def __init__(self, coordinator: HttpSettingsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "sw", "Switch Input")


class MainsVoltageSensor(_HttpSettingsSensor):
    """Mains voltage setting (sp): 110V / 230V."""

    _VALUE_TO_STATE = {"0": "110V", "1": "230V"}

    def __init__(self, coordinator: HttpSettingsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "sp", "Mains Voltage")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up diagnostic sensor entities for HTTP settings."""
    coordinator: HttpSettingsCoordinator = hass.data[DOMAIN][entry.entry_id][
        "http_coordinator"
    ]
    async_add_entities(
        [
            SwitchInputSensor(coordinator, entry),
            MainsVoltageSensor(coordinator, entry),
        ]
    )
