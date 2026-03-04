"""Sensor entities for Busch-Radio iNet (diagnostic, read-only)."""

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BuschRadioCoordinator
from .http_coordinator import HttpSettingsCoordinator


# ---------------------------------------------------------------------------
# UDP-based sensor (always available, no HTTP required)
# ---------------------------------------------------------------------------

class BuschRadioEnergyModeSensor(SensorEntity):
    """Diagnostic sensor showing the device energy mode (PREMIUM / ECO).

    Data comes from GET POWER_STATUS via UDP – no HTTP polling required.
    Exposed together with HTTP settings entities for logical grouping.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_name = "Energy Mode"
    _attr_icon = "mdi:lightning-bolt-circle"

    def __init__(self, coordinator: BuschRadioCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._entry = entry
        self._attr_unique_id = f"{entry.unique_id}_energy_mode"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry.unique_id)})

    @property
    def native_value(self) -> str | None:
        return self._coordinator.energy_mode

    async def async_added_to_hass(self) -> None:
        """Register callback so coordinator can push state updates."""
        self._coordinator.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister callback when entity is removed."""
        self._coordinator.unregister_callback(self.async_write_ha_state)


# ---------------------------------------------------------------------------
# HTTP-based sensors (read from /radio.cfg via HttpSettingsCoordinator)
# ---------------------------------------------------------------------------

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
    def available(self) -> bool:
        return super().available and self.coordinator.data is not None

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


# ---------------------------------------------------------------------------
# Platform setup
# ---------------------------------------------------------------------------

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up all diagnostic sensor entities.

    Always registers BuschRadioEnergyModeSensor (UDP data).
    Also registers HTTP diagnostic sensors (sw, sp) via http_coordinator.
    The sensor platform is only loaded when expose_http_settings is True,
    so all three sensors appear and disappear together.
    """
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: BuschRadioCoordinator = data["coordinator"]
    http_coordinator: HttpSettingsCoordinator = data["http_coordinator"]

    async_add_entities(
        [
            BuschRadioEnergyModeSensor(coordinator, entry),
            SwitchInputSensor(http_coordinator, entry),
            MainsVoltageSensor(http_coordinator, entry),
        ]
    )
