"""Busch-Radio iNet – Home Assistant integration.

Sets up the shared UDP listener, coordinator and media_player platform for
one or more Busch-Radio iNet devices (model 8216 U).

A single SharedUDPListener is created on first device setup and shared by all
config entries.  Each entry registers its device IP with the listener and
unregisters on unload.  The listener is stopped when the last device is removed.
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
from .udp_listener import SharedUDPListener

_LOGGER = logging.getLogger(__name__)

# media_player + sensor are UDP-based and always loaded. The sensor platform
# adds the station-presets sensor (always) and the HTTP diagnostic sensors only
# when expose_http_settings is on (see sensor.py).
ALWAYS_PLATFORMS = ["media_player", "sensor"]
HTTP_PLATFORMS = ["number", "select", "switch", "time", "button"]

_SHARED_LISTENER_KEY = "shared_listener"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Busch-Radio iNet from a config entry."""
    host: str = entry.data[CONF_HOST]
    port: int = entry.data[CONF_PORT]

    domain_data = hass.data.setdefault(DOMAIN, {})

    # Create the shared listener on first device; reuse it for subsequent devices.
    if _SHARED_LISTENER_KEY not in domain_data:
        shared_listener = SharedUDPListener(port=DEFAULT_LISTEN_PORT)
        try:
            await shared_listener.start()
        except OSError as exc:
            raise ConfigEntryNotReady(
                f"Cannot bind to UDP port {DEFAULT_LISTEN_PORT}: {exc}"
            ) from exc
        domain_data[_SHARED_LISTENER_KEY] = shared_listener
    else:
        shared_listener: SharedUDPListener = domain_data[_SHARED_LISTENER_KEY]

    client = BuschRadioUDPClient(host, port)
    coordinator = BuschRadioCoordinator(hass, client, host)

    # Reachability probe for the fallback poll (independent of expose_http_settings).
    coordinator.set_reachability_client(HttpSettingsClient(hass, host))

    shared_listener.register(
        host,
        on_packet=coordinator.handle_packet,
        client=client,
        on_notification=coordinator.handle_notification,
    )

    # Startup queries run in the background: they are spaced out and repeated
    # (see BuschRadioCoordinator.async_run_startup_queries), which must not
    # hold up setup.  Responses arrive via the shared listener.
    startup_queries = hass.async_create_task(
        coordinator.async_run_startup_queries()
    )

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

    artwork_client = ArtworkClient(hass, "0.5.1")
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

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    platforms = list(ALWAYS_PLATFORMS)
    if expose_http:
        platforms.extend(HTTP_PLATFORMS)

    domain_data[entry.entry_id] = {
        "coordinator": coordinator,
        "client": client,
        "cancel_startup_icy": cancel_startup_icy,
        "startup_queries": startup_queries,
        "http_coordinator": http_coordinator,
        "platforms": platforms,
        "host": host,
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
        data["startup_queries"].cancel()
        data["coordinator"].stop_polling()
        data["coordinator"].stop_icy()
        data["coordinator"].stop_artwork()

        # Unregister this device from the shared listener.
        shared_listener: SharedUDPListener = hass.data[DOMAIN][_SHARED_LISTENER_KEY]
        shared_listener.unregister(data["host"])

        # Stop and remove the shared listener when the last device is gone.
        if not shared_listener.has_devices:
            shared_listener.stop()
            del hass.data[DOMAIN][_SHARED_LISTENER_KEY]

        # http_coordinator is a DataUpdateCoordinator – no explicit stop() needed

    return unload_ok
