"""HTTP client for Busch-Radio iNet device settings."""

import logging

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=8)


def parse_radio_cfg(text: str) -> dict[str, str]:
    """Parse /radio.cfg INI-like format into a flat key→value dict.

    Format: lines like '&bb=100' or '&aw=' (empty = checkbox off).
    Section headers ([general], [system]) are ignored.
    """
    result: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("["):
            continue
        if line.startswith("&"):
            line = line[1:]  # strip leading &
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip()
    return result


class HttpSettingsClient:
    """Low-level HTTP client for reading and writing device settings."""

    # All checkbox fields – always sent, either "1" (on) or "" (off)
    _CHECKBOX_FIELDS = frozenset({"aw", "sz", "ea", "et", "es"})

    def __init__(self, hass: HomeAssistant, host: str) -> None:
        self._hass = hass
        self._host = host

    async def async_get_config(self) -> dict[str, str]:
        """GET http://<host>/radio.cfg and return parsed key→value dict."""
        session = async_get_clientsession(self._hass)
        url = f"http://{self._host}/radio.cfg"
        async with session.get(url, timeout=_REQUEST_TIMEOUT) as resp:
            resp.raise_for_status()
            text = await resp.text(encoding="latin-1")
        return parse_radio_cfg(text)

    async def async_post_general(self, fields: dict[str, str]) -> None:
        """POST the full settings dict to /en/general.cgi.

        Every field read from /radio.cfg is written back unchanged (the caller
        only patches the field being set). No field is dropped: the device
        resets any managed field that is absent from the form to its default
        (observed with 'sw'/'sp' resetting to 0 on every write), so omitting a
        field is unsafe. The only adjustment is checkbox normalization, which
        ensures every checkbox field is present ("1" on / "" off) because an
        absent checkbox would likewise be read as off.
        """
        safe = dict(fields)

        # Ensure all checkbox fields are present (even when off)
        for cb in self._CHECKBOX_FIELDS:
            safe[cb] = "1" if safe.get(cb) == "1" else ""

        _LOGGER.debug(
            "async_post_general: posting %d fields to /en/general.cgi; "
            "time-related: hr=%s mi=%s zs=%s",
            len(safe),
            safe.get("hr", "<missing>"),
            safe.get("mi", "<missing>"),
            safe.get("zs", "<missing>"),
        )

        session = async_get_clientsession(self._hass)
        url = f"http://{self._host}/en/general.cgi"
        async with session.post(
            url,
            data=safe,
            timeout=_REQUEST_TIMEOUT,
        ) as resp:
            resp.raise_for_status()
            _LOGGER.debug("async_post_general: response HTTP %s", resp.status)
        # HTML response body is intentionally ignored
