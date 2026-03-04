"""Busch-Radio iNet – Home Assistant integration.

Sets up the UDP listener, coordinator and media_player platform for a single
Busch-Radio iNet device (model 8216 U).
"""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.event import async_call_later

from .const import (
    CONF_EXPOSE_HTTP_SETTINGS,
    CONF_HOST,
    CONF_HTTP_POLL_INTERVAL,
    CONF_ICY_ENABLED,
    CONF_ICY_INTERVAL,
    CONF_ICY_MODE,
    CONF_PORT,
    DEFAULT_EXPOSE_HTTP_SETTINGS,
    DEFAULT_HTTP_POLL_INTERVAL,
    DEFAULT_ICY_ENABLED,
    DEFAULT_ICY_INTERVAL,
    DEFAULT_ICY_MODE,
    DEFAULT_LISTEN_PORT,
    DOMAIN,
    ICY_MODE_LIVE,
)
from .artwork_client import ArtworkClient
from .coordinator import BuschRadioCoordinator
from .http_client import HttpSettingsClient
from .http_coordinator import HttpSettingsCoordinator
from .icy_client import IcyClient, IcyIntervalScheduler, IcyPersistentConnection
from .udp_client import BuschRadioUDPClient
from .udp_listener import BuschRadioUDPListener

_LOGGER = logging.getLogger(__name__)

ALWAYS_PLATFORMS = ["media_player"]
HTTP_PLATFORMS = ["number", "select", "switch", "time", "button", "sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Busch-Radio iNet from a config entry."""
    host: str = entry.data[CONF_HOST]
    port: int = entry.data[CONF_PORT]

    client = BuschRadioUDPClient(host, port)
    coordinator = BuschRadioCoordinator(hass, client)
    listener = BuschRadioUDPListener(
        port=DEFAULT_LISTEN_PORT,
        on_packet=coordinator.handle_packet,
        client=client,
        on_notification=coordinator.handle_notification,
    )

    try:
        await listener.start()
    except OSError as exc:
        raise ConfigEntryNotReady(
            f"Cannot bind to UDP port {DEFAULT_LISTEN_PORT}: {exc}"
        ) from exc

    # Send startup queries – responses arrive via the listener
    await client.send_get("INFO_BLOCK")
    await client.send_get("ALL_STATION_INFO")
    await client.send_get("POWER_STATUS")
    await client.send_get("VOLUME")
    await client.send_get("PLAYING_MODE")

    icy_enabled = entry.options.get(CONF_ICY_ENABLED, DEFAULT_ICY_ENABLED)
    icy_mode = entry.options.get(CONF_ICY_MODE, DEFAULT_ICY_MODE)
    icy_interval = int(entry.options.get(CONF_ICY_INTERVAL, DEFAULT_ICY_INTERVAL))

    if icy_enabled:
        if icy_mode == ICY_MODE_LIVE:
            icy_fetcher = IcyPersistentConnection(
                hass=hass,
                on_title=coordinator.set_media_title,
            )
        else:
            icy_fetcher = IcyIntervalScheduler(
                hass=hass,
                fetcher=IcyClient(hass),
                on_title=coordinator.set_media_title,
                interval_seconds=icy_interval,
            )
        coordinator.set_icy_fetcher(icy_fetcher)
        # If the radio is already playing when the integration loads, no URL_IS_PLAYING
        # event will arrive. Schedule a one-time check after startup queries have settled.
        cancel_startup_icy = async_call_later(
            hass, 5, lambda _now: coordinator.start_icy_if_playing()
        )
    else:
        cancel_startup_icy = lambda: None  # noqa: E731

    artwork_client = ArtworkClient(hass, "0.4.0")
    coordinator.set_artwork_client(artwork_client)

    expose_http = entry.options.get(CONF_EXPOSE_HTTP_SETTINGS, DEFAULT_EXPOSE_HTTP_SETTINGS)
    http_poll_interval = int(
        entry.options.get(CONF_HTTP_POLL_INTERVAL, DEFAULT_HTTP_POLL_INTERVAL)
    )

    http_coordinator: HttpSettingsCoordinator | None = None
    if expose_http:
        http_client = HttpSettingsClient(hass, host)
        http_coordinator = HttpSettingsCoordinator(hass, http_client, http_poll_interval)
        # Start in background – does not block main setup if HTTP is unavailable.
        # Entities will be 'unavailable' until the first successful fetch.
        hass.async_create_task(http_coordinator.async_refresh())

    coordinator.start_polling()

    entry.add_update_listener(async_reload_entry)

    platforms = list(ALWAYS_PLATFORMS)
    if expose_http:
        platforms.extend(HTTP_PLATFORMS)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "listener": listener,
        "client": client,
        "cancel_startup_icy": cancel_startup_icy,
        "http_coordinator": http_coordinator,
        "platforms": platforms,
    }

    await hass.config_entries.async_forward_entry_setups(entry, platforms)
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Busch-Radio iNet config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, data["platforms"]
    )

    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        data["cancel_startup_icy"]()
        data["coordinator"].stop_polling()
        data["coordinator"].stop_icy()
        data["coordinator"].stop_artwork()
        data["listener"].stop()
        # http_coordinator is a DataUpdateCoordinator – no explicit stop() needed

    return unload_ok
