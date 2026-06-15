"""HTTP client for Busch-Radio iNet device settings."""

import logging

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=8)
_REACHABILITY_TIMEOUT = aiohttp.ClientTimeout(total=5)


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

    # Fields the device's /<lang>/general.cgi settings form manages (captured
    # from the web UI). Only these are sent on a write — everything else in
    # /radio.cfg (network, stations, firmware) is ignored by the form and omitted.
    _VALUE_FIELDS = frozenset({
        "bb", "co", "bl", "dm", "ms", "sm", "ln",
        "hr", "mi", "zs", "tz", "ah", "am", "st", "ss", "sw", "sp",
    })

    # Checkbox fields – sent as "1" only when on, omitted when off (HTML form
    # semantics: an absent checkbox is read as off).
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

    async def async_is_reachable(self) -> bool:
        """Return True if the device answers an HTTP GET within a short timeout.

        Used by the fallback poll to detect when the radio goes offline. UDP is
        fire-and-forget and cannot confirm reachability, so a quick HTTP GET to
        /radio.cfg is used as the liveness probe.
        """
        try:
            session = async_get_clientsession(self._hass)
            url = f"http://{self._host}/radio.cfg"
            async with session.get(url, timeout=_REACHABILITY_TIMEOUT) as resp:
                return resp.status == 200
        except Exception:  # noqa: BLE001 - any error means "not reachable"
            return False

    async def async_post_general(self, fields: dict[str, str]) -> None:
        """POST the managed settings to /<lang>/general.cgi.

        Mirrors the device's own web form exactly (captured from the UI):
        - only the managed fields are sent (`_VALUE_FIELDS` + checked checkboxes);
          all other fields from /radio.cfg are ignored by the form and omitted,
        - checkboxes are sent as "1" when on and omitted when off,
        - the submit field ``save=Save`` is required — without it the CGI returns
          HTTP 200 but does not persist the change,
        - the path matches the device language (``ln``); the device serves the
          settings form per locale, e.g. ``/de/general.cgi`` on a German device.
        """
        payload = {k: fields[k] for k in self._VALUE_FIELDS if k in fields}
        for cb in self._CHECKBOX_FIELDS:
            if fields.get(cb) == "1":
                payload[cb] = "1"
        payload["save"] = "Save"

        lang = fields.get("ln") or "en"
        url = f"http://{self._host}/{lang}/general.cgi"

        _LOGGER.debug(
            "async_post_general: POST %d fields to %s; dm=%s ms=%s sm=%s sw=%s sp=%s",
            len(payload), url,
            payload.get("dm"), payload.get("ms"), payload.get("sm"),
            payload.get("sw"), payload.get("sp"),
        )

        session = async_get_clientsession(self._hass)
        async with session.post(
            url,
            data=payload,
            timeout=_REQUEST_TIMEOUT,
        ) as resp:
            resp.raise_for_status()
            _LOGGER.debug("async_post_general: response HTTP %s", resp.status)
        # HTML response body is intentionally ignored
