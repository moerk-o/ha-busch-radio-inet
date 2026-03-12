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

    # Fields that must NEVER be included in a POST (hardware-level, dangerous)
    _BLOCKED_FIELDS = frozenset({"sw", "sp"})

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

        Safety rules applied before sending:
        - sw and sp are always removed (hardware-level, must never be set via HTTP)
        - Checkbox fields always present: "1" if truthy, "" if falsy/missing
        """
        safe = {k: v for k, v in fields.items() if k not in self._BLOCKED_FIELDS}

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
