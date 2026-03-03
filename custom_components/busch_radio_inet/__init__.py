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
    CONF_HOST,
    CONF_ICY_ENABLED,
    CONF_ICY_INTERVAL,
    CONF_ICY_MODE,
    CONF_PORT,
    DEFAULT_ICY_ENABLED,
    DEFAULT_ICY_INTERVAL,
    DEFAULT_ICY_MODE,
    DEFAULT_LISTEN_PORT,
    DOMAIN,
    ICY_MODE_LIVE,
)
from .coordinator import BuschRadioCoordinator
from .icy_client import IcyClient, IcyIntervalScheduler, IcyPersistentConnection
from .udp_client import BuschRadioUDPClient
from .udp_listener import BuschRadioUDPListener

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["media_player"]


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

    coordinator.start_polling()

    entry.add_update_listener(async_reload_entry)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "listener": listener,
        "client": client,
        "cancel_startup_icy": cancel_startup_icy,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Busch-Radio iNet config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        data["cancel_startup_icy"]()
        data["coordinator"].stop_polling()
        data["coordinator"].stop_icy()
        data["listener"].stop()

    return unload_ok
