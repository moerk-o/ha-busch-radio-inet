"""Tests for HTTP settings entity platforms: number, select, switch, time, button, sensor."""

import pytest
from datetime import time as dt_time
from unittest.mock import AsyncMock, MagicMock, patch

from pytest_homeassistant_custom_component.common import MockConfigEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

UNIQUE_ID = "78C40E33745C"

# Sentinel so callers can distinguish "use default" from "explicit None"
_UNSET = object()


def make_entry():
    return MockConfigEntry(
        domain="busch_radio_inet",
        data={"host": "192.168.1.179", "port": 4244},
        unique_id=UNIQUE_ID,
        version=1,
    )


def make_http_coordinator(data=_UNSET):
    """Create a mock HttpSettingsCoordinator.

    Pass explicit data (including None or {}) to override the default.
    Call without arguments to get the default {"bb": "80", "co": "60"}.
    """
    coord = MagicMock()
    coord.data = {"bb": "80", "co": "60"} if data is _UNSET else data
    coord.async_set = AsyncMock()
    coord.last_update_success = True
    return coord


# ===========================================================================
# number.py
# ===========================================================================


class TestBrightnessNumber:
    def _make(self, data=_UNSET):
        from custom_components.busch_radio_inet.number import BrightnessNumber
        coord = make_http_coordinator({"bb": "75"} if data is _UNSET else data)
        entry = make_entry()
        entity = BrightnessNumber(coord, entry)
        entity.hass = MagicMock()
        return entity, coord

    def test_native_value(self):
        entity, _ = self._make({"bb": "75"})
        assert entity.native_value == 75.0

    def test_native_value_none_when_key_missing(self):
        entity, _ = self._make({})
        assert entity.native_value is None

    def test_native_value_none_on_invalid(self):
        entity, _ = self._make({"bb": "not_a_number"})
        assert entity.native_value is None

    def test_unavailable_when_data_none(self):
        from custom_components.busch_radio_inet.number import BrightnessNumber
        coord = make_http_coordinator(None)
        coord.available = True
        entry = make_entry()
        entity = BrightnessNumber(coord, entry)
        assert not entity.available

    def test_unique_id(self):
        entity, _ = self._make()
        assert entity.unique_id == f"{UNIQUE_ID}_http_bb"

    def test_min_max(self):
        entity, _ = self._make()
        assert entity.native_min_value == 0
        assert entity.native_max_value == 100

    @pytest.mark.asyncio
    async def test_set_native_value(self):
        entity, coord = self._make()
        await entity.async_set_native_value(42.0)
        coord.async_set.assert_awaited_once_with({"bb": "42"})


class TestContrastNumber:
    def _make(self, data=_UNSET):
        from custom_components.busch_radio_inet.number import ContrastNumber
        coord = make_http_coordinator({"co": "50"} if data is _UNSET else data)
        entry = make_entry()
        return ContrastNumber(coord, entry), coord

    def test_native_value(self):
        entity, _ = self._make({"co": "50"})
        assert entity.native_value == 50.0

    @pytest.mark.asyncio
    async def test_set_native_value(self):
        entity, coord = self._make()
        await entity.async_set_native_value(30.0)
        coord.async_set.assert_awaited_once_with({"co": "30"})


class TestTimezoneNumber:
    def _make(self, data=_UNSET):
        from custom_components.busch_radio_inet.number import TimezoneNumber
        coord = make_http_coordinator({"tz": "1"} if data is _UNSET else data)
        entry = make_entry()
        return TimezoneNumber(coord, entry), coord

    def test_min_max(self):
        entity, _ = self._make()
        assert entity.native_min_value == -12
        assert entity.native_max_value == 12

    def test_native_value(self):
        entity, _ = self._make({"tz": "2"})
        assert entity.native_value == 2.0

    @pytest.mark.asyncio
    async def test_set_native_value_negative(self):
        entity, coord = self._make()
        await entity.async_set_native_value(-5.0)
        coord.async_set.assert_awaited_once_with({"tz": "-5"})


class TestShortTimerDurationNumber:
    def _make(self, data=_UNSET):
        from custom_components.busch_radio_inet.number import ShortTimerDurationNumber
        coord = make_http_coordinator({"st": "30"} if data is _UNSET else data)
        entry = make_entry()
        return ShortTimerDurationNumber(coord, entry), coord

    def test_native_value(self):
        entity, _ = self._make({"st": "30"})
        assert entity.native_value == 30.0


class TestSleepTimerDurationNumber:
    def _make(self, data=_UNSET):
        from custom_components.busch_radio_inet.number import SleepTimerDurationNumber
        coord = make_http_coordinator({"ss": "60"} if data is _UNSET else data)
        entry = make_entry()
        return SleepTimerDurationNumber(coord, entry), coord

    def test_native_value(self):
        entity, _ = self._make({"ss": "60"})
        assert entity.native_value == 60.0


# ===========================================================================
# select.py
# ===========================================================================


class TestBacklightSelect:
    def _make(self, data=_UNSET):
        from custom_components.busch_radio_inet.select import BacklightSelect
        coord = make_http_coordinator({"bl": "2"} if data is _UNSET else data)
        entry = make_entry()
        entity = BacklightSelect(coord, entry)
        return entity, coord

    def test_current_option_auto(self):
        entity, _ = self._make({"bl": "2"})
        assert entity.current_option == "Auto"

    def test_current_option_on(self):
        entity, _ = self._make({"bl": "1"})
        assert entity.current_option == "On"

    def test_current_option_off(self):
        entity, _ = self._make({"bl": "0"})
        assert entity.current_option == "Off"

    def test_current_option_unknown_returns_none(self):
        entity, _ = self._make({"bl": "99"})
        assert entity.current_option is None

    def test_options_list(self):
        entity, _ = self._make()
        assert set(entity.options) == {"Off", "On", "Auto"}

    def test_unavailable_when_data_none(self):
        from custom_components.busch_radio_inet.select import BacklightSelect
        coord = make_http_coordinator(None)
        coord.available = True
        entry = make_entry()
        entity = BacklightSelect(coord, entry)
        assert not entity.available

    @pytest.mark.asyncio
    async def test_select_option(self):
        entity, coord = self._make()
        await entity.async_select_option("On")
        coord.async_set.assert_awaited_once_with({"bl": "1"})


class TestTimeSourceSelect:
    def _make(self, data=_UNSET):
        from custom_components.busch_radio_inet.select import TimeSourceSelect
        coord = make_http_coordinator({"zs": "0"} if data is _UNSET else data)
        entry = make_entry()
        return TimeSourceSelect(coord, entry), coord

    def test_internet(self):
        entity, _ = self._make({"zs": "0"})
        assert entity.current_option == "Internet"

    def test_manual(self):
        entity, _ = self._make({"zs": "1"})
        assert entity.current_option == "Manual"

    @pytest.mark.asyncio
    async def test_select_manual(self):
        entity, coord = self._make()
        await entity.async_select_option("Manual")
        coord.async_set.assert_awaited_once_with({"zs": "1"})


class TestLanguageSelect:
    def _make(self, data=_UNSET):
        from custom_components.busch_radio_inet.select import LanguageSelect
        coord = make_http_coordinator({"ln": "de"} if data is _UNSET else data)
        entry = make_entry()
        return LanguageSelect(coord, entry), coord

    def test_current_option_german(self):
        entity, _ = self._make({"ln": "de"})
        assert entity.current_option == "Deutsch"


class TestSoundModeSelect:
    def _make(self, data=_UNSET):
        from custom_components.busch_radio_inet.select import SoundModeSelect
        coord = make_http_coordinator({"sm": "0"} if data is _UNSET else data)
        entry = make_entry()
        return SoundModeSelect(coord, entry), coord

    def test_all_options_present(self):
        entity, _ = self._make()
        assert set(entity.options) == {"Rock", "Jazz", "Classic", "Electro", "Speech"}

    @pytest.mark.asyncio
    async def test_select_jazz(self):
        entity, coord = self._make()
        await entity.async_select_option("Jazz")
        coord.async_set.assert_awaited_once_with({"sm": "1"})


# ===========================================================================
# switch.py
# ===========================================================================


class TestAlarmSwitch:
    def _make(self, data=_UNSET):
        from custom_components.busch_radio_inet.switch import AlarmSwitch
        coord = make_http_coordinator({"ea": "1"} if data is _UNSET else data)
        entry = make_entry()
        return AlarmSwitch(coord, entry), coord

    def test_is_on_when_one(self):
        entity, _ = self._make({"ea": "1"})
        assert entity.is_on is True

    def test_is_off_when_empty(self):
        entity, _ = self._make({"ea": ""})
        assert entity.is_on is False

    def test_unavailable_when_data_none(self):
        from custom_components.busch_radio_inet.switch import AlarmSwitch
        coord = make_http_coordinator(None)
        coord.available = True
        entry = make_entry()
        entity = AlarmSwitch(coord, entry)
        assert not entity.available

    @pytest.mark.asyncio
    async def test_turn_on(self):
        entity, coord = self._make({"ea": ""})
        await entity.async_turn_on()
        coord.async_set.assert_awaited_once_with({"ea": "1"})

    @pytest.mark.asyncio
    async def test_turn_off(self):
        entity, coord = self._make({"ea": "1"})
        await entity.async_turn_off()
        coord.async_set.assert_awaited_once_with({"ea": ""})

    def test_unique_id(self):
        entity, _ = self._make()
        assert entity.unique_id == f"{UNIQUE_ID}_http_ea"


class TestDaylightSavingSwitch:
    def _make(self, data=_UNSET):
        from custom_components.busch_radio_inet.switch import DaylightSavingSwitch
        coord = make_http_coordinator({"sz": "1"} if data is _UNSET else data)
        entry = make_entry()
        return DaylightSavingSwitch(coord, entry), coord

    def test_is_on(self):
        entity, _ = self._make({"sz": "1"})
        assert entity.is_on is True


class TestSleepTimerSwitch:
    def _make(self, data=_UNSET):
        from custom_components.busch_radio_inet.switch import SleepTimerSwitch
        coord = make_http_coordinator({"es": ""} if data is _UNSET else data)
        entry = make_entry()
        return SleepTimerSwitch(coord, entry), coord

    def test_is_off_by_default(self):
        entity, _ = self._make({"es": ""})
        assert entity.is_on is False


# ===========================================================================
# time.py
# ===========================================================================


class TestLocalTimeTime:
    def _make(self, data=_UNSET):
        from custom_components.busch_radio_inet.time import LocalTimeTime
        coord = make_http_coordinator({"hr": "14", "mi": "30"} if data is _UNSET else data)
        entry = make_entry()
        return LocalTimeTime(coord, entry), coord

    def test_native_value(self):
        entity, _ = self._make({"hr": "14", "mi": "30"})
        assert entity.native_value == dt_time(14, 30)

    def test_native_value_midnight(self):
        entity, _ = self._make({"hr": "0", "mi": "0"})
        assert entity.native_value == dt_time(0, 0)

    def test_native_value_none_on_invalid(self):
        entity, _ = self._make({"hr": "bad", "mi": "30"})
        assert entity.native_value is None

    def test_unavailable_when_data_none(self):
        from custom_components.busch_radio_inet.time import LocalTimeTime
        coord = make_http_coordinator(None)
        coord.available = True
        entry = make_entry()
        entity = LocalTimeTime(coord, entry)
        assert not entity.available

    def test_unique_id(self):
        entity, _ = self._make()
        assert entity.unique_id == f"{UNIQUE_ID}_http_hr_mi"

    @pytest.mark.asyncio
    async def test_set_value(self):
        entity, coord = self._make()
        await entity.async_set_value(dt_time(8, 45))
        coord.async_set.assert_awaited_once_with({"hr": "8", "mi": "45"})


class TestAlarmTimeTime:
    def _make(self, data=_UNSET):
        from custom_components.busch_radio_inet.time import AlarmTimeTime
        coord = make_http_coordinator({"ah": "7", "am": "00"} if data is _UNSET else data)
        entry = make_entry()
        return AlarmTimeTime(coord, entry), coord

    def test_native_value(self):
        entity, _ = self._make({"ah": "7", "am": "00"})
        assert entity.native_value == dt_time(7, 0)

    @pytest.mark.asyncio
    async def test_set_value(self):
        entity, coord = self._make()
        await entity.async_set_value(dt_time(6, 30))
        coord.async_set.assert_awaited_once_with({"ah": "6", "am": "30"})


# ===========================================================================
# button.py
# ===========================================================================


class TestRefreshSettingsButton:
    def _make(self):
        from custom_components.busch_radio_inet.button import RefreshSettingsButton
        coord = make_http_coordinator()
        coord.async_request_refresh = AsyncMock()
        coord.async_refresh = AsyncMock()
        entry = make_entry()
        udp_client = MagicMock()
        udp_client.send_get = AsyncMock()
        return RefreshSettingsButton(coord, entry, udp_client), coord, udp_client

    @pytest.mark.asyncio
    async def test_press_refreshes_coordinator(self):
        entity, coord, _ = self._make()
        await entity.async_press()
        coord.async_request_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_press_sends_power_status(self):
        entity, _, udp_client = self._make()
        await entity.async_press()
        udp_client.send_get.assert_awaited_once_with("POWER_STATUS")

    def test_unique_id(self):
        entity, _, _ = self._make()
        assert entity.unique_id == f"{UNIQUE_ID}_http_refresh"


class TestSyncTimeButton:
    def _make(self):
        from custom_components.busch_radio_inet.button import SyncTimeButton
        coord = make_http_coordinator()
        entry = make_entry()
        entity = SyncTimeButton(coord, entry)
        entity.hass = MagicMock()
        return entity, coord

    def test_unique_id(self):
        entity, _ = self._make()
        assert entity.unique_id == f"{UNIQUE_ID}_http_sync_time"

    @pytest.mark.asyncio
    async def test_press_sets_hr_mi_zs(self):
        entity, coord = self._make()
        fixed_time = MagicMock()
        fixed_time.hour = 14
        fixed_time.minute = 25
        fixed_time.utcoffset = MagicMock(return_value=None)
        with patch(
            "custom_components.busch_radio_inet.button.dt_util.now",
            return_value=fixed_time,
        ):
            await entity.async_press()
        coord.async_set.assert_awaited_once_with({"hr": "14", "mi": "25", "zs": "1"})

    @pytest.mark.asyncio
    async def test_press_uses_ha_local_time(self):
        """Verify that dt_util.now() is used (not UTC)."""
        entity, coord = self._make()
        called_args = []

        async def capture_set(fields):
            called_args.append(fields)

        coord.async_set.side_effect = capture_set

        fixed_time = MagicMock()
        fixed_time.hour = 23
        fixed_time.minute = 59
        fixed_time.utcoffset = MagicMock(return_value=None)
        with patch(
            "custom_components.busch_radio_inet.button.dt_util.now",
            return_value=fixed_time,
        ):
            await entity.async_press()

        assert called_args[0]["hr"] == "23"
        assert called_args[0]["mi"] == "59"
        assert called_args[0]["zs"] == "1"


# ===========================================================================
# sensor.py
# ===========================================================================


class TestBuschRadioEnergyModeSensor:
    def _make(self, energy_mode="PREMIUM"):
        from custom_components.busch_radio_inet.sensor import BuschRadioEnergyModeSensor
        coord = MagicMock()
        coord.energy_mode = energy_mode
        coord.register_callback = MagicMock()
        coord.unregister_callback = MagicMock()
        entry = make_entry()
        entity = BuschRadioEnergyModeSensor(coord, entry)
        entity.async_write_ha_state = MagicMock()
        return entity, coord

    def test_native_value_premium(self):
        entity, _ = self._make("PREMIUM")
        assert entity.native_value == "PREMIUM"

    def test_native_value_eco(self):
        entity, _ = self._make("ECO")
        assert entity.native_value == "ECO"

    def test_native_value_none(self):
        entity, _ = self._make(None)
        assert entity.native_value is None

    def test_available_follows_coordinator(self):
        entity, coord = self._make()
        coord.available = True
        assert entity.available is True
        coord.available = False
        assert entity.available is False

    def test_unique_id(self):
        entity, _ = self._make()
        assert entity.unique_id == f"{UNIQUE_ID}_energy_mode"

    @pytest.mark.asyncio
    async def test_added_to_hass_registers_callback(self):
        entity, coord = self._make()
        await entity.async_added_to_hass()
        coord.register_callback.assert_called_once_with(entity.async_write_ha_state)

    @pytest.mark.asyncio
    async def test_will_remove_unregisters_callback(self):
        entity, coord = self._make()
        await entity.async_will_remove_from_hass()
        coord.unregister_callback.assert_called_once_with(entity.async_write_ha_state)


class TestBuschRadioStationPresetsSensor:
    def _make(self, station_list, station_list_known=True, available=True):
        from custom_components.busch_radio_inet.sensor import BuschRadioStationPresetsSensor
        coord = MagicMock()
        coord.station_list = station_list
        coord.station_list_known = station_list_known
        coord.available = available
        coord.register_callback = MagicMock()
        coord.unregister_callback = MagicMock()
        entry = make_entry()
        entity = BuschRadioStationPresetsSensor(coord, entry)
        entity.async_write_ha_state = MagicMock()
        return entity, coord

    def test_unavailable_until_the_station_list_arrives(self):
        """0 would read as 'no presets stored' instead of 'not known yet'."""
        entity, _ = self._make([], station_list_known=False)
        assert entity.available is False

    def test_available_with_zero_presets_once_the_list_arrived(self):
        """A radio without stored presets legitimately reports zero."""
        entity, _ = self._make([], station_list_known=True)
        assert entity.available is True
        assert entity.native_value == 0

    def test_unavailable_when_the_device_is_unreachable(self):
        entity, _ = self._make([], station_list_known=True, available=False)
        assert entity.available is False

    def test_native_value_counts_occupied_presets(self):
        entity, _ = self._make([
            {"id": 1, "name": "WDR 2", "url": "u1"},
            {"id": 2, "name": "NDR 90.3", "url": "u2"},
        ])
        assert entity.native_value == 2

    def test_attributes_cover_all_eight_slots(self):
        entity, _ = self._make([
            {"id": 1, "name": "WDR 2", "url": "u1"},
            {"id": 4, "name": "Relax", "url": "u4"},
        ])
        attrs = entity.extra_state_attributes
        assert attrs["1_name"] == "WDR 2"
        assert attrs["1_url"] == "u1"
        assert attrs["4_name"] == "Relax"
        # empty slots are present with empty strings
        assert attrs["2_name"] == ""
        assert attrs["8_url"] == ""
        assert sum(1 for k in attrs if k.endswith("_name")) == 8
        assert sum(1 for k in attrs if k.endswith("_url")) == 8

    def test_unique_id(self):
        entity, _ = self._make([])
        assert entity.unique_id == f"{UNIQUE_ID}_station_presets"

    def test_available_follows_coordinator(self):
        entity, coord = self._make([])
        coord.available = False
        assert entity.available is False

    @pytest.mark.asyncio
    async def test_added_registers_callback(self):
        entity, coord = self._make([])
        await entity.async_added_to_hass()
        coord.register_callback.assert_called_once_with(entity.async_write_ha_state)

    @pytest.mark.asyncio
    async def test_will_remove_unregisters_callback(self):
        entity, coord = self._make([])
        await entity.async_will_remove_from_hass()
        coord.unregister_callback.assert_called_once_with(entity.async_write_ha_state)
