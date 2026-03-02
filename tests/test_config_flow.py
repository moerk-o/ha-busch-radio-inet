"""Tests for the Busch-Radio iNet config flow."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from custom_components.busch_radio_inet.config_flow import (
    CannotConnect,
    _ValidationProtocol,
    validate_connection,
)
from custom_components.busch_radio_inet.const import DOMAIN


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

INFO_BLOCK_RESPONSE = (
    b"COMMAND:GET\r\nINFO_BLOCK\r\nID:HA\r\n"
    b"NAME:RADIO-INET3745C\r\nIPADDR:192.168.1.179\r\n"
    b"SERNO:78C40E33745C\r\nSW-VERSION:03.12\r\nRESPONSE:ACK\r\n"
)


def make_protocol_with_future():
    """Create a _ValidationProtocol with a real asyncio Future."""
    loop = asyncio.get_event_loop()
    future = loop.create_future()
    proto = _ValidationProtocol(future)
    return proto, future


# ===========================================================================
# _ValidationProtocol – unit tests (no loop manipulation needed)
# ===========================================================================


async def test_protocol_resolves_future_on_serno_response():
    proto, future = make_protocol_with_future()
    proto.datagram_received(INFO_BLOCK_RESPONSE, ("192.168.1.179", 4242))
    assert future.done()
    result = await future
    assert result["SERNO"] == "78C40E33745C"
    assert result["SW-VERSION"] == "03.12"


async def test_protocol_ignores_packet_without_serno():
    proto, future = make_protocol_with_future()
    proto.datagram_received(
        b"COMMAND:GET\r\nPOWER_STATUS\r\nPOWER:ON\r\nRESPONSE:ACK\r\n",
        ("192.168.1.179", 4242),
    )
    assert not future.done()


async def test_protocol_skips_id_ha_echo():
    proto, future = make_protocol_with_future()
    proto.datagram_received(INFO_BLOCK_RESPONSE, ("192.168.1.179", 4242))
    result = await future
    # ID:HA must be dropped; only real data fields survive
    assert result.get("ID") != "HA"


async def test_protocol_does_not_resolve_future_twice():
    proto, future = make_protocol_with_future()
    proto.datagram_received(INFO_BLOCK_RESPONSE, ("192.168.1.179", 4242))
    # Second packet – must not raise InvalidStateError
    proto.datagram_received(INFO_BLOCK_RESPONSE, ("192.168.1.179", 4242))
    assert future.done()


async def test_protocol_ignores_decode_errors():
    proto, future = make_protocol_with_future()
    proto.datagram_received(b"\xff\xfe invalid utf-8 SERNO:test", ("192.168.1.179", 4242))
    assert not future.done()


async def test_protocol_error_received_sets_future_exception():
    proto, future = make_protocol_with_future()
    proto.error_received(OSError("socket error"))
    assert future.done()
    with pytest.raises(OSError):
        await future


async def test_protocol_error_received_does_not_overwrite_result():
    proto, future = make_protocol_with_future()
    proto.datagram_received(INFO_BLOCK_RESPONSE, ("192.168.1.179", 4242))
    proto.error_received(OSError("late error"))  # Must not raise
    assert (await future)["SERNO"] == "78C40E33745C"


async def test_protocol_connection_lost_with_exc_sets_exception():
    proto, future = make_protocol_with_future()
    proto.connection_lost(OSError("lost"))
    assert future.done()
    with pytest.raises(OSError):
        await future


async def test_protocol_connection_lost_without_exc_leaves_future_pending():
    proto, future = make_protocol_with_future()
    proto.connection_lost(None)
    assert not future.done()


async def test_protocol_connection_lost_does_not_overwrite_result():
    proto, future = make_protocol_with_future()
    proto.datagram_received(INFO_BLOCK_RESPONSE, ("192.168.1.179", 4242))
    proto.connection_lost(OSError("late"))  # Must not raise
    assert (await future)["SERNO"] == "78C40E33745C"


# ===========================================================================
# validate_connection – OSError path (socket bind fails before wait_for)
# ===========================================================================


async def test_validate_connection_raises_cannot_connect_on_oserror():
    """OSError when binding the socket → CannotConnect."""
    with patch(
        "custom_components.busch_radio_inet.config_flow.asyncio.get_running_loop"
    ) as mock_get_loop:
        mock_loop = MagicMock()
        mock_loop.create_future.return_value = MagicMock()
        mock_loop.create_datagram_endpoint = AsyncMock(
            side_effect=OSError("address already in use")
        )
        mock_get_loop.return_value = mock_loop

        with pytest.raises(CannotConnect):
            await validate_connection("192.168.1.179", 4244)


async def test_validate_connection_no_transport_to_close_on_oserror():
    """When create_datagram_endpoint raises, transport is None – no crash."""
    with patch(
        "custom_components.busch_radio_inet.config_flow.asyncio.get_running_loop"
    ) as mock_get_loop:
        mock_loop = MagicMock()
        mock_loop.create_future.return_value = MagicMock()
        mock_loop.create_datagram_endpoint = AsyncMock(
            side_effect=OSError("address already in use")
        )
        mock_get_loop.return_value = mock_loop

        # Must not raise AttributeError or anything from the finally block
        with pytest.raises(CannotConnect):
            await validate_connection("192.168.1.179", 4244)


# ===========================================================================
# Full config flow (via hass) – these test the whole async_step_user path
# ===========================================================================


async def test_config_flow_aborts_when_host_already_configured(
    hass: HomeAssistant,
) -> None:
    """If the same host is already configured the flow must abort, not show cannot_connect."""
    device_info = {"SERNO": "78C40E33745C"}
    with patch(
        "custom_components.busch_radio_inet.config_flow.validate_connection",
        return_value=device_info,
    ), patch(
        "custom_components.busch_radio_inet.__init__.BuschRadioUDPListener"
    ) as mock_listener_cls, patch(
        "custom_components.busch_radio_inet.__init__.BuschRadioUDPClient"
    ) as mock_client_cls:
        mock_listener = MagicMock()
        mock_listener.start = AsyncMock()
        mock_listener_cls.return_value = mock_listener
        mock_client = MagicMock()
        mock_client.send_get = AsyncMock()
        mock_client_cls.return_value = mock_client

        # First setup – succeeds
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"host": "192.168.1.179", "port": 4244, "name": "Radio"},
        )

    # Second attempt with same host – must abort before validate_connection runs
    with patch(
        "custom_components.busch_radio_inet.config_flow.validate_connection",
    ) as mock_validate:
        result2 = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result2 = await hass.config_entries.flow.async_configure(
            result2["flow_id"],
            {"host": "192.168.1.179", "port": 4244, "name": "Radio"},
        )

    assert result2["type"] == "abort"
    assert result2["reason"] == "already_configured"
    mock_validate.assert_not_called()


async def test_config_flow_shows_form_on_first_step(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == "form"
    assert result["step_id"] == "user"
    assert result["errors"] == {}


async def test_config_flow_success_creates_entry(hass: HomeAssistant):
    device_info = {"SERNO": "78C40E33745C", "SW-VERSION": "03.12"}
    with patch(
        "custom_components.busch_radio_inet.config_flow.validate_connection",
        return_value=device_info,
    ), patch(
        "custom_components.busch_radio_inet.__init__.BuschRadioUDPListener"
    ) as mock_listener_cls, patch(
        "custom_components.busch_radio_inet.__init__.BuschRadioUDPClient"
    ) as mock_client_cls:
        mock_listener = MagicMock()
        mock_listener.start = AsyncMock()
        mock_listener_cls.return_value = mock_listener
        mock_client = MagicMock()
        mock_client.send_get = AsyncMock()
        mock_client_cls.return_value = mock_client

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"host": "192.168.1.179", "port": 4244, "name": "Busch-Radio iNet"},
        )

    assert result["type"] == "create_entry"
    assert result["title"] == "Busch-Radio iNet"
    assert result["data"]["host"] == "192.168.1.179"
    assert result["data"]["port"] == 4244


async def test_config_flow_stores_correct_data(hass: HomeAssistant):
    device_info = {"SERNO": "78C40E33745C"}
    with patch(
        "custom_components.busch_radio_inet.config_flow.validate_connection",
        return_value=device_info,
    ), patch(
        "custom_components.busch_radio_inet.__init__.BuschRadioUDPListener"
    ) as mock_listener_cls, patch(
        "custom_components.busch_radio_inet.__init__.BuschRadioUDPClient"
    ) as mock_client_cls:
        mock_listener = MagicMock()
        mock_listener.start = AsyncMock()
        mock_listener_cls.return_value = mock_listener
        mock_client = MagicMock()
        mock_client.send_get = AsyncMock()
        mock_client_cls.return_value = mock_client

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"host": "10.0.0.5", "port": 9999, "name": "My Radio"},
        )

    assert result["data"] == {"host": "10.0.0.5", "port": 9999, "name": "My Radio"}


async def test_config_flow_cannot_connect_shows_error(hass: HomeAssistant):
    with patch(
        "custom_components.busch_radio_inet.config_flow.validate_connection",
        side_effect=CannotConnect,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"host": "192.168.1.1", "port": 4244, "name": "Busch-Radio iNet"},
        )

    assert result["type"] == "form"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_config_flow_can_retry_after_error(hass: HomeAssistant):
    """After a connection error, the user can submit again successfully."""
    device_info = {"SERNO": "78C40E33745C"}
    with patch(
        "custom_components.busch_radio_inet.config_flow.validate_connection",
        side_effect=CannotConnect,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"host": "bad.ip", "port": 4244, "name": "Radio"},
        )
    assert result["type"] == "form"

    with patch(
        "custom_components.busch_radio_inet.config_flow.validate_connection",
        return_value=device_info,
    ), patch(
        "custom_components.busch_radio_inet.__init__.BuschRadioUDPListener"
    ) as mock_listener_cls, patch(
        "custom_components.busch_radio_inet.__init__.BuschRadioUDPClient"
    ) as mock_client_cls:
        mock_listener = MagicMock()
        mock_listener.start = AsyncMock()
        mock_listener_cls.return_value = mock_listener
        mock_client = MagicMock()
        mock_client.send_get = AsyncMock()
        mock_client_cls.return_value = mock_client

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"host": "192.168.1.179", "port": 4244, "name": "Radio"},
        )

    assert result["type"] == "create_entry"


async def test_config_flow_duplicate_device_aborted(hass: HomeAssistant):
    """A second entry for the same serial number must be aborted."""
    device_info = {"SERNO": "78C40E33745C"}

    with patch(
        "custom_components.busch_radio_inet.config_flow.validate_connection",
        return_value=device_info,
    ), patch(
        "custom_components.busch_radio_inet.__init__.BuschRadioUDPListener"
    ) as mock_listener_cls, patch(
        "custom_components.busch_radio_inet.__init__.BuschRadioUDPClient"
    ) as mock_client_cls:
        mock_listener = MagicMock()
        mock_listener.start = AsyncMock()
        mock_listener_cls.return_value = mock_listener
        mock_client = MagicMock()
        mock_client.send_get = AsyncMock()
        mock_client_cls.return_value = mock_client

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"host": "192.168.1.179", "port": 4244, "name": "Radio 1"},
        )

    with patch(
        "custom_components.busch_radio_inet.config_flow.validate_connection",
        return_value=device_info,
    ):
        result2 = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result2 = await hass.config_entries.flow.async_configure(
            result2["flow_id"],
            {"host": "192.168.1.179", "port": 4244, "name": "Radio 2"},
        )

    assert result2["type"] == "abort"
    assert result2["reason"] == "already_configured"
