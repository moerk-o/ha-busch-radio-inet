"""Config flow for Busch-Radio iNet."""

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_EXPOSE_HTTP_SETTINGS,
    CONF_HOST,
    CONF_HTTP_POLL_INTERVAL,
    CONF_ICY_ENABLED,
    CONF_ICY_INTERVAL,
    CONF_ICY_MODE,
    CONF_NAME,
    CONF_PORT,
    CONNECT_TIMEOUT,
    DEFAULT_EXPOSE_HTTP_SETTINGS,
    DEFAULT_HTTP_POLL_INTERVAL,
    DEFAULT_ICY_ENABLED,
    DEFAULT_ICY_INTERVAL,
    DEFAULT_ICY_MODE,
    DEFAULT_LISTEN_PORT,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DOMAIN,
    ICY_MODE_INTERVAL,
    ICY_MODE_LIVE,
)
from .udp_client import BuschRadioUDPClient

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
    }
)


class CannotConnect(Exception):
    """Raised when a connection attempt to the device fails."""


class _ValidationProtocol(asyncio.DatagramProtocol):
    """Temporary datagram protocol used only during config flow validation.

    Resolves the given future when an INFO_BLOCK response with a SERNO field
    is received.  Rejects the future on socket errors.
    """

    def __init__(self, future: asyncio.Future) -> None:
        self._future = future

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        try:
            message = data.decode("utf-8")
            fields: dict = {}
            for raw_line in message.split("\r\n"):
                line = raw_line.strip()
                if ":" in line:
                    key, _, value = line.partition(":")
                    key = key.strip()
                    value = value.strip()
                    # Skip the command echo ID field
                    if key == "ID" and value == "HA":
                        continue
                    fields[key] = value
            if "SERNO" in fields and not self._future.done():
                self._future.set_result(fields)
        except Exception:  # noqa: BLE001
            pass

    def error_received(self, exc: Exception) -> None:
        if not self._future.done():
            self._future.set_exception(exc)

    def connection_lost(self, exc: Exception | None) -> None:
        if exc and not self._future.done():
            self._future.set_exception(exc)


async def validate_connection(host: str, port: int) -> dict:
    """Send GET INFO_BLOCK and wait for the response.

    Returns the parsed device info fields on success.
    Raises CannotConnect on timeout or socket error.
    """
    loop = asyncio.get_running_loop()
    future: asyncio.Future = loop.create_future()

    transport = None
    try:
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _ValidationProtocol(future),
            local_addr=("0.0.0.0", DEFAULT_LISTEN_PORT),
        )
        client = BuschRadioUDPClient(host, port)
        await client.send_get("INFO_BLOCK")
        return await asyncio.wait_for(future, timeout=CONNECT_TIMEOUT)
    except (OSError, asyncio.TimeoutError) as exc:
        raise CannotConnect from exc
    finally:
        if transport is not None:
            transport.close()


class BuschRadioINetConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial setup UI for Busch-Radio iNet."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle the user step (IP / port / name)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]

            # Abort early if a config entry with the same host already exists.
            # This prevents validate_connection from failing with OSError when
            # port 4242 is already bound by the running listener.
            self._async_abort_entries_match({CONF_HOST: host})

            try:
                info = await validate_connection(host, port)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                serial = info.get("SERNO", "")
                await self.async_set_unique_id(serial)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> "BuschRadioOptionsFlowHandler":
        """Return the options flow handler."""
        return BuschRadioOptionsFlowHandler(config_entry)


class BuschRadioOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options for Busch-Radio iNet (ICY metadata settings)."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Show the ICY options form."""
        if user_input is not None:
            user_input[CONF_ICY_INTERVAL] = int(user_input[CONF_ICY_INTERVAL])
            user_input[CONF_HTTP_POLL_INTERVAL] = int(user_input[CONF_HTTP_POLL_INTERVAL])
            return self.async_create_entry(title="", data=user_input)

        opts = self._entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ICY_ENABLED,
                        default=opts.get(CONF_ICY_ENABLED, DEFAULT_ICY_ENABLED),
                    ): selector.BooleanSelector(),
                    vol.Required(
                        CONF_ICY_MODE,
                        default=opts.get(CONF_ICY_MODE, DEFAULT_ICY_MODE),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {
                                    "value": ICY_MODE_INTERVAL,
                                    "label": "Interval (every N seconds)",
                                },
                                {
                                    "value": ICY_MODE_LIVE,
                                    "label": "Live (persistent connection)",
                                },
                            ],
                        )
                    ),
                    vol.Required(
                        CONF_ICY_INTERVAL,
                        default=opts.get(CONF_ICY_INTERVAL, DEFAULT_ICY_INTERVAL),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=10,
                            max=300,
                            step=10,
                            unit_of_measurement="s",
                            mode=selector.NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Required(
                        CONF_EXPOSE_HTTP_SETTINGS,
                        default=opts.get(
                            CONF_EXPOSE_HTTP_SETTINGS, DEFAULT_EXPOSE_HTTP_SETTINGS
                        ),
                    ): selector.BooleanSelector(),
                    vol.Required(
                        CONF_HTTP_POLL_INTERVAL,
                        default=opts.get(
                            CONF_HTTP_POLL_INTERVAL, DEFAULT_HTTP_POLL_INTERVAL
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1,
                            max=60,
                            step=1,
                            unit_of_measurement="min",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
        )
