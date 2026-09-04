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
    def available(self) -> bool:
        return self._coordinator.available

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
    """Raw 'sw' field from /radio.cfg.

    The device reports a value (observed: '4') that does not match the
    originally assumed 0/1/2 encoding, so no value mapping is applied — the raw
    value is shown. Meaning unconfirmed, therefore disabled by default.
    """

    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: HttpSettingsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "sw", "Switch Input")


class MainsVoltageSensor(_HttpSettingsSensor):
    """Raw 'sp' field from /radio.cfg.

    The device reports a value (observed: '4') that does not match the
    originally assumed 0/1 encoding, so no value mapping is applied — the raw
    value is shown. Meaning unconfirmed, therefore disabled by default.
    """

    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: HttpSettingsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "sp", "Mains Voltage")


# ---------------------------------------------------------------------------
# Station presets (UDP, always available)
# ---------------------------------------------------------------------------

# The device has 8 station preset slots (s1–s8 / n1–n8).
PRESET_SLOTS = 8


class BuschRadioStationPresetsSensor(SensorEntity):
    """Number of stored station presets, with per-slot name/url attributes.

    Data comes from ALL_STATION_INFO via UDP (the coordinator's station_list).
    The state is the count of occupied presets; attributes `1_name`/`1_url` …
    `8_name`/`8_url` expose every slot (empty slots have empty strings), so a
    Lovelace card can render the presets.
    """

    _attr_has_entity_name = True
    _attr_name = "Station Presets"
    _attr_icon = "mdi:radio"

    def __init__(self, coordinator: BuschRadioCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._entry = entry
        self._attr_unique_id = f"{entry.unique_id}_station_presets"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry.unique_id)})

    @property
    def available(self) -> bool:
        """Unavailable until the station list has actually been received.

        native_value counts the list, so an outstanding answer would read as a
        genuine "no presets stored" instead of "not known yet".
        """
        return self._coordinator.available and self._coordinator.station_list_known

    @property
    def native_value(self) -> int:
        return len(self._coordinator.station_list)

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        by_slot = {s["id"]: s for s in self._coordinator.station_list}
        attrs: dict[str, str] = {}
        for slot in range(1, PRESET_SLOTS + 1):
            station = by_slot.get(slot)
            attrs[f"{slot}_name"] = station["name"] if station else ""
            attrs[f"{slot}_url"] = station.get("url", "") if station else ""
        return attrs

    async def async_added_to_hass(self) -> None:
        """Register callback so coordinator can push state updates."""
        self._coordinator.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister callback when entity is removed."""
        self._coordinator.unregister_callback(self.async_write_ha_state)


# ---------------------------------------------------------------------------
# Platform setup
# ---------------------------------------------------------------------------

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor entities.

    The station-presets sensor (UDP data) is always added. The diagnostic
    sensors (energy mode, sw, sp) need the HTTP coordinator and are only added
    when expose_http_settings is enabled.
    """
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: BuschRadioCoordinator = data["coordinator"]
    http_coordinator: HttpSettingsCoordinator | None = data["http_coordinator"]

    entities: list[SensorEntity] = [
        BuschRadioStationPresetsSensor(coordinator, entry),
    ]
    if http_coordinator is not None:
        entities += [
            BuschRadioEnergyModeSensor(coordinator, entry),
            SwitchInputSensor(http_coordinator, entry),
            MainsVoltageSensor(http_coordinator, entry),
        ]

    async_add_entities(entities)
