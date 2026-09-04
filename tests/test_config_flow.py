"""Tests for the Busch-Radio iNet config flow."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from custom_components.busch_radio_inet.config_flow import (
    CannotConnect,
    _ValidationProtocol,
    _suggested_name,
    validate_connection,
)
from custom_components.busch_radio_inet.const import DEFAULT_NAME, DOMAIN


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


def _mock_hass_no_listener():
    """Return a mock hass with no shared listener (first device scenario)."""
    hass = MagicMock()
    hass.data = {}
    return hass


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
            await validate_connection(_mock_hass_no_listener(), "192.168.1.179", 4244)


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
            await validate_connection(_mock_hass_no_listener(), "192.168.1.179", 4244)


async def test_validate_connection_reuses_shared_listener():
    """When a SharedUDPListener exists, validation registers on it instead of binding port 4242."""
    mock_listener = MagicMock()
    captured_callback = {}
    undo_register = MagicMock()

    def fake_register(host, on_packet, client, on_notification=None):
        captured_callback["on_packet"] = on_packet
        return undo_register

    mock_listener.register = fake_register

    hass = MagicMock()
    hass.data = {"busch_radio_inet": {"shared_listener": mock_listener}}

    with patch(
        "custom_components.busch_radio_inet.config_flow.BuschRadioUDPClient"
    ) as mock_client_cls:
        mock_client = MagicMock()

        async def fake_send_get(cmd):
            # Simulate device response arriving via the shared listener callback
            captured_callback["on_packet"]({"SERNO": "AABBCC112233", "NAME": "RADIO"})

        mock_client.send_get = fake_send_get
        mock_client_cls.return_value = mock_client

        result = await validate_connection(hass, "192.168.1.20", 4244)

    assert result["SERNO"] == "AABBCC112233"
    undo_register.assert_called_once()


async def test_validate_connection_shared_listener_timeout_raises_cannot_connect():
    """Timeout via shared listener path → CannotConnect."""
    mock_listener = MagicMock()
    mock_listener.register = MagicMock()

    hass = MagicMock()
    hass.data = {"busch_radio_inet": {"shared_listener": mock_listener}}

    with patch(
        "custom_components.busch_radio_inet.config_flow.BuschRadioUDPClient"
    ) as mock_client_cls:
        mock_client = MagicMock()
        mock_client.send_get = AsyncMock()
        mock_client_cls.return_value = mock_client

        with patch(
            "custom_components.busch_radio_inet.config_flow.asyncio.wait_for",
            side_effect=asyncio.TimeoutError,
        ):
            with pytest.raises(CannotConnect):
                await validate_connection(hass, "192.168.1.20", 4244)

    # The probe registration is undone even when validation fails.
    mock_listener.register.return_value.assert_called_once()


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
        "custom_components.busch_radio_inet.__init__.SharedUDPListener"
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


# ===========================================================================
# validate_connection – no shared listener, success path
# ===========================================================================


async def test_validate_connection_no_listener_success():
    """Without a shared listener, a temporary socket is opened and closed again."""
    hass = _mock_hass_no_listener()
    mock_transport = MagicMock()
    mock_loop = MagicMock()
    mock_loop.create_future.return_value = MagicMock()
    mock_loop.create_datagram_endpoint = AsyncMock(
        return_value=(mock_transport, MagicMock())
    )

    with patch(
        "custom_components.busch_radio_inet.config_flow.asyncio.get_running_loop",
        return_value=mock_loop,
    ), patch(
        "custom_components.busch_radio_inet.config_flow.BuschRadioUDPClient"
    ) as mock_client_cls, patch(
        "custom_components.busch_radio_inet.config_flow.asyncio.wait_for",
        new=AsyncMock(return_value={"SERNO": "AABBCC112233"}),
    ):
        mock_client = MagicMock()
        mock_client.send_get = AsyncMock()
        mock_client_cls.return_value = mock_client

        result = await validate_connection(hass, "192.168.1.50", 4244)

    assert result["SERNO"] == "AABBCC112233"
    mock_transport.close.assert_called_once()


# ===========================================================================
# validate_connection – must not evict a live registration
# ===========================================================================


def _listener_with_live_device(host):
    """Real SharedUDPListener with one device registered (no socket needed)."""
    from custom_components.busch_radio_inet.udp_listener import SharedUDPListener

    listener = SharedUDPListener(port=4242)
    live_on_packet = MagicMock()
    live_client = MagicMock()
    listener.register(host, live_on_packet, live_client)
    hass = MagicMock()
    hass.data = {DOMAIN: {"shared_listener": listener}}
    return listener, hass, live_on_packet, live_client


async def test_validate_connection_restores_live_registration_on_success():
    """Probing a host that a loaded entry owns must leave that entry routed."""
    host = "192.168.1.179"
    listener, hass, live_on_packet, live_client = _listener_with_live_device(host)

    with patch(
        "custom_components.busch_radio_inet.config_flow.BuschRadioUDPClient"
    ) as mock_client_cls:
        mock_client = MagicMock()

        async def fake_send_get(cmd):
            # Answer whichever callback is registered while the probe runs.
            listener._devices[host][0]({"SERNO": "78C40E33745C"})

        mock_client.send_get = fake_send_get
        mock_client_cls.return_value = mock_client

        result = await validate_connection(hass, host, 4244)

    assert result["SERNO"] == "78C40E33745C"
    on_packet, _on_notification, client = listener._devices[host]
    assert on_packet is live_on_packet
    assert client is live_client


async def test_validate_connection_restores_live_registration_on_timeout():
    """Same, but the probe fails – the live device must still be routed."""
    host = "192.168.1.179"
    listener, hass, live_on_packet, live_client = _listener_with_live_device(host)

    with patch(
        "custom_components.busch_radio_inet.config_flow.BuschRadioUDPClient"
    ) as mock_client_cls, patch(
        "custom_components.busch_radio_inet.config_flow.asyncio.wait_for",
        side_effect=asyncio.TimeoutError,
    ):
        mock_client = MagicMock()
        mock_client.send_get = AsyncMock()
        mock_client_cls.return_value = mock_client

        with pytest.raises(CannotConnect):
            await validate_connection(hass, host, 4244)

    on_packet, _on_notification, client = listener._devices[host]
    assert on_packet is live_on_packet
    assert client is live_client


# ===========================================================================
# Reconfigure flow
# ===========================================================================


def _patch_entry_setup():
    """Patch the UDP pieces so a reload triggered by reconfigure stays offline."""
    listener_patch = patch(
        "custom_components.busch_radio_inet.__init__.SharedUDPListener"
    )
    client_patch = patch(
        "custom_components.busch_radio_inet.__init__.BuschRadioUDPClient"
    )
    return listener_patch, client_patch


async def test_reconfigure_flow_shows_form_with_current_values(
    hass: HomeAssistant, mock_config_entry
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reconfigure_flow(hass)

    assert result["type"] == "form"
    assert result["step_id"] == "reconfigure"

    suggested = {
        str(key): key.description.get("suggested_value")
        for key in result["data_schema"].schema
        if key.description
    }
    assert suggested["host"] == "192.168.1.179"
    assert suggested["port"] == 4244


async def test_reconfigure_flow_updates_host_and_port(
    hass: HomeAssistant, mock_config_entry, device_serial
) -> None:
    """The new address is stored in the entry data; the entry is not recreated."""
    mock_config_entry.add_to_hass(hass)
    entry_id = mock_config_entry.entry_id

    listener_patch, client_patch = _patch_entry_setup()
    with patch(
        "custom_components.busch_radio_inet.config_flow.validate_connection",
        return_value={"SERNO": device_serial},
    ), listener_patch as mock_listener_cls, client_patch as mock_client_cls:
        mock_listener = MagicMock()
        mock_listener.start = AsyncMock()
        mock_listener_cls.return_value = mock_listener
        mock_client = MagicMock()
        mock_client.send_get = AsyncMock()
        mock_client_cls.return_value = mock_client

        result = await mock_config_entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"host": "192.168.3.65", "port": 4244},
        )
        await hass.async_block_till_done()

    assert result["type"] == "abort"
    assert result["reason"] == "reconfigure_successful"

    entry = hass.config_entries.async_get_entry(entry_id)
    assert entry.data["host"] == "192.168.3.65"
    assert entry.data["port"] == 4244
    # Untouched fields survive, and the entry keeps its identity.
    assert entry.data["name"] == "Busch-Radio iNet"
    assert entry.unique_id == device_serial


async def test_reconfigure_flow_cannot_connect_shows_error(
    hass: HomeAssistant, mock_config_entry
) -> None:
    mock_config_entry.add_to_hass(hass)

    with patch(
        "custom_components.busch_radio_inet.config_flow.validate_connection",
        side_effect=CannotConnect,
    ):
        result = await mock_config_entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"host": "192.168.3.99", "port": 4244},
        )

    assert result["type"] == "form"
    assert result["errors"] == {"base": "cannot_connect"}
    # Nothing was written to the entry.
    assert mock_config_entry.data["host"] == "192.168.1.179"


async def test_reconfigure_flow_can_retry_after_error(
    hass: HomeAssistant, mock_config_entry, device_serial
) -> None:
    """A failed attempt keeps the flow open so the address can be corrected."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "custom_components.busch_radio_inet.config_flow.validate_connection",
        side_effect=CannotConnect,
    ):
        result = await mock_config_entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "192.168.3.99", "port": 4244}
        )

    listener_patch, client_patch = _patch_entry_setup()
    with patch(
        "custom_components.busch_radio_inet.config_flow.validate_connection",
        return_value={"SERNO": device_serial},
    ), listener_patch as mock_listener_cls, client_patch as mock_client_cls:
        mock_listener = MagicMock()
        mock_listener.start = AsyncMock()
        mock_listener_cls.return_value = mock_listener
        mock_client = MagicMock()
        mock_client.send_get = AsyncMock()
        mock_client_cls.return_value = mock_client

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "192.168.3.65", "port": 4244}
        )
        await hass.async_block_till_done()

    assert result["type"] == "abort"
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data["host"] == "192.168.3.65"


async def test_reconfigure_flow_rejects_a_different_device(
    hass: HomeAssistant, mock_config_entry
) -> None:
    """A radio with another serial must not take over this entry."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "custom_components.busch_radio_inet.config_flow.validate_connection",
        return_value={"SERNO": "OTHERSERIAL01"},
    ):
        result = await mock_config_entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"host": "192.168.3.65", "port": 4244},
        )

    assert result["type"] == "abort"
    assert result["reason"] == "wrong_device"
    assert mock_config_entry.data["host"] == "192.168.1.179"


async def test_reconfigure_flow_rejects_host_of_another_entry(
    hass: HomeAssistant, mock_config_entry
) -> None:
    """Two entries pointing at the same radio would collide in the UDP listener."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    mock_config_entry.add_to_hass(hass)
    second_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"host": "192.168.1.180", "port": 4244, "name": "Radio 2"},
        unique_id="AABBCC112233",
        version=1,
    )
    second_entry.add_to_hass(hass)

    with patch(
        "custom_components.busch_radio_inet.config_flow.validate_connection",
    ) as mock_validate:
        result = await mock_config_entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"host": "192.168.1.180", "port": 4244},
        )

    assert result["type"] == "form"
    assert result["errors"] == {"base": "already_configured"}
    mock_validate.assert_not_called()


async def test_reconfigure_flow_accepts_the_entrys_own_host(
    hass: HomeAssistant, mock_config_entry, device_serial
) -> None:
    """Re-submitting the unchanged host (e.g. to fix only the port) is allowed."""
    mock_config_entry.add_to_hass(hass)

    listener_patch, client_patch = _patch_entry_setup()
    with patch(
        "custom_components.busch_radio_inet.config_flow.validate_connection",
        return_value={"SERNO": device_serial},
    ), listener_patch as mock_listener_cls, client_patch as mock_client_cls:
        mock_listener = MagicMock()
        mock_listener.start = AsyncMock()
        mock_listener_cls.return_value = mock_listener
        mock_client = MagicMock()
        mock_client.send_get = AsyncMock()
        mock_client_cls.return_value = mock_client

        result = await mock_config_entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"host": "192.168.1.179", "port": 4245},
        )
        await hass.async_block_till_done()

    assert result["type"] == "abort"
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data["port"] == 4245


# ===========================================================================
# Options flow
# ===========================================================================


async def test_options_flow_shows_form(hass: HomeAssistant, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] == "form"
    assert result["step_id"] == "init"


async def test_options_flow_submit_creates_entry(hass: HomeAssistant, mock_config_entry):
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "icy_enabled": True,
            "icy_mode": "interval",
            "icy_interval": 60,
            "expose_http_settings": False,
            "http_poll_interval": 5,
        },
    )
    assert result["type"] == "create_entry"


def test_async_get_options_flow_returns_handler():
    from custom_components.busch_radio_inet.config_flow import (
        BuschRadioINetConfigFlow,
        BuschRadioOptionsFlowHandler,
    )

    handler = BuschRadioINetConfigFlow.async_get_options_flow(MagicMock())
    assert isinstance(handler, BuschRadioOptionsFlowHandler)


def test_suggested_name_first_device():
    assert _suggested_name(0) == DEFAULT_NAME


def test_suggested_name_second_device():
    assert _suggested_name(1) == f"{DEFAULT_NAME} 2"


def test_suggested_name_third_device():
    assert _suggested_name(2) == f"{DEFAULT_NAME} 3"


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
        "custom_components.busch_radio_inet.__init__.SharedUDPListener"
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
        "custom_components.busch_radio_inet.__init__.SharedUDPListener"
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
        "custom_components.busch_radio_inet.__init__.SharedUDPListener"
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
        "custom_components.busch_radio_inet.__init__.SharedUDPListener"
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
