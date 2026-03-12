"""Coordinator for Busch-Radio iNet HTTP settings (polling + Read-Modify-Write)."""

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .http_client import HttpSettingsClient

_LOGGER = logging.getLogger(__name__)


class HttpSettingsCoordinator(DataUpdateCoordinator[dict[str, str]]):
    """Polls /radio.cfg and manages Read-Modify-Write for all HTTP settings."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: HttpSettingsClient,
        poll_interval_minutes: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="Busch-Radio iNet HTTP Settings",
            update_interval=timedelta(minutes=poll_interval_minutes),
        )
        self._client = client

    async def _async_update_data(self) -> dict[str, str]:
        """Fetch /radio.cfg. Called by DataUpdateCoordinator on every poll."""
        try:
            return await self._client.async_get_config()
        except Exception as exc:
            raise UpdateFailed(f"Cannot read /radio.cfg: {exc}") from exc

    async def async_set(self, fields: dict[str, str]) -> None:
        """Read-Modify-Write: fetch full config, patch fields, POST back, refresh.

        Used for all write operations:
        - Single field (number/select/switch): coordinator.async_set({"sm": "1"})
        - Two fields atomically (time entities): coordinator.async_set({"ah": "7", "am": "30"})
        """
        try:
            current = await self._client.async_get_config()
            current.update(fields)
            await self._client.async_post_general(current)
        except Exception as exc:
            raise HomeAssistantError(
                f"Failed to write settings {list(fields)}: {exc}"
            ) from exc
        await self.async_refresh()
