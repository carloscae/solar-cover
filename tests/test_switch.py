"""Tests for the Solar Cover automation enable/disable switch."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_cover.switch import SolarCoverSwitch


def _make_switch() -> tuple[SolarCoverSwitch, MagicMock]:
    coordinator = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.title = "Zone: Test"
    return SolarCoverSwitch(coordinator, entry), coordinator


class TestSolarCoverSwitch:
    def test_unique_id_is_entry_id_plus_key(self) -> None:
        switch, _ = _make_switch()
        assert switch.unique_id == "test_entry_automation_enabled"

    def test_is_on_reflects_coordinator_enabled(self) -> None:
        switch, coordinator = _make_switch()
        coordinator.enabled = True
        assert switch.is_on is True
        coordinator.enabled = False
        assert switch.is_on is False

    @pytest.mark.asyncio
    async def test_turn_on_delegates_to_coordinator(self) -> None:
        switch, coordinator = _make_switch()
        switch.async_write_ha_state = MagicMock()
        await switch.async_turn_on()
        coordinator.set_enabled.assert_called_once_with(True)
        switch.async_write_ha_state.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_turn_off_delegates_to_coordinator(self) -> None:
        switch, coordinator = _make_switch()
        switch.async_write_ha_state = MagicMock()
        await switch.async_turn_off()
        coordinator.set_enabled.assert_called_once_with(False)
        switch.async_write_ha_state.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_restore_off_disables_via_coordinator(self) -> None:
        switch, coordinator = _make_switch()
        last_state = MagicMock()
        last_state.state = "off"
        switch.async_get_last_state = AsyncMock(return_value=last_state)
        await switch.async_added_to_hass()
        coordinator.restore_enabled.assert_called_once_with(False)

    @pytest.mark.asyncio
    async def test_restore_on_enables_via_coordinator(self) -> None:
        switch, coordinator = _make_switch()
        last_state = MagicMock()
        last_state.state = "on"
        switch.async_get_last_state = AsyncMock(return_value=last_state)
        await switch.async_added_to_hass()
        coordinator.restore_enabled.assert_called_once_with(True)

    @pytest.mark.asyncio
    async def test_restore_none_does_not_touch_coordinator(self) -> None:
        switch, coordinator = _make_switch()
        switch.async_get_last_state = AsyncMock(return_value=None)
        await switch.async_added_to_hass()
        coordinator.restore_enabled.assert_not_called()
