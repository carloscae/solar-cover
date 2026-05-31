"""Tests for the Solar Cover reset-timers button."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from homeassistant.helpers.entity import EntityCategory

from custom_components.solar_cover.button import SolarCoverResetTimersButton


def _make_button() -> tuple[SolarCoverResetTimersButton, MagicMock]:
    coordinator = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.title = "Zone: Test"
    return SolarCoverResetTimersButton(coordinator, entry), coordinator


class TestResetTimersButton:
    def test_is_config_category(self) -> None:
        button, _ = _make_button()
        assert button.entity_category == EntityCategory.CONFIG

    def test_unique_id_is_entry_id_plus_key(self) -> None:
        button, _ = _make_button()
        assert button.unique_id == "test_entry_reset_timers"

    @pytest.mark.asyncio
    async def test_press_resets_timers(self) -> None:
        button, coordinator = _make_button()
        await button.async_press()
        coordinator.reset_timers.assert_called_once_with()
