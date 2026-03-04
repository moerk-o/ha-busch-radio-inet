"""Button entity for Busch-Radio iNet HTTP settings."""

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .http_coordinator import HttpSettingsCoordinator


class RefreshSettingsButton(
    CoordinatorEntity[HttpSettingsCoordinator], ButtonEntity
):
    """Button to immediately refresh all settings entities.

    On press:
    - re-fetches /radio.cfg (HTTP coordinator) → updates all HTTP settings entities
    - sends GET POWER_STATUS (UDP) → updates energy mode sensor
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_name = "Refresh Settings"
    _attr_icon = "mdi:refresh"

    def __init__(
        self,
        coordinator: HttpSettingsCoordinator,
        entry: ConfigEntry,
        udp_client,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._udp_client = udp_client
        self._attr_unique_id = f"{entry.unique_id}_http_refresh"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry.unique_id)})

    async def async_press(self) -> None:
        await self.coordinator.async_request_refresh()
        await self._udp_client.send_get("POWER_STATUS")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the refresh button for HTTP settings."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: HttpSettingsCoordinator = data["http_coordinator"]
    udp_client = data["client"]
    async_add_entities([RefreshSettingsButton(coordinator, entry, udp_client)])
