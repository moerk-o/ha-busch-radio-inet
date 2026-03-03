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
    CONF_PORT,
    DEFAULT_LISTEN_PORT,
    DOMAIN,
)
from .coordinator import BuschRadioCoordinator
from .icy_client import IcyClient, IcyIntervalScheduler, IcyPersistentConnection
from .udp_client import BuschRadioUDPClient
from .udp_listener import BuschRadioUDPListener

# Temporary Mode B switch – replaced by config entry options in Phase 3.
# Set to "live" to use IcyPersistentConnection, "interval" for IcyIntervalScheduler.
_ICY_MODE = "interval"

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

    if _ICY_MODE == "live":
        icy_fetcher = IcyPersistentConnection(
            hass=hass,
            on_title=coordinator.set_media_title,
        )
    else:
        icy_fetcher = IcyIntervalScheduler(
            hass=hass,
            fetcher=IcyClient(hass),
            on_title=coordinator.set_media_title,
            interval_seconds=60,  # Phase 3: read from config entry options
        )
    coordinator.set_icy_fetcher(icy_fetcher)
    coordinator.start_polling()

    # If the radio is already playing when the integration loads, no URL_IS_PLAYING
    # event will arrive. Schedule a one-time check after startup queries have settled.
    cancel_startup_icy = async_call_later(
        hass, 5, lambda _now: coordinator.start_icy_if_playing()
    )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "listener": listener,
        "client": client,
        "cancel_startup_icy": cancel_startup_icy,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


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
