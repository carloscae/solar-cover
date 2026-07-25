"""Tests for the Solar Cover reset-timers button."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.helpers.entity import EntityCategory

from custom_components.solar_cover.button import (  # noqa: E402
    SolarCoverResetCoverButton,
    SolarCoverResetTimersButton,
)
from custom_components.solar_cover.const import DOMAIN, Intent  # noqa: E402
from custom_components.solar_cover.coordinator import CoverSnapshot  # noqa: E402


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
        coordinator.async_request_refresh = AsyncMock()
        await button.async_press()
        coordinator.reset_timers.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_press_awaits_refresh(self) -> None:
        button, coordinator = _make_button()
        coordinator.async_request_refresh = AsyncMock()
        await button.async_press()
        coordinator.async_request_refresh.assert_awaited_once_with()

    def test_extra_state_attributes_reports_zone_intent(self) -> None:
        button, coordinator = _make_button()
        coordinator.data.intent = Intent.SHADING
        assert button.extra_state_attributes == {"intent": "shading"}

    def test_extra_state_attributes_none_before_first_refresh(self) -> None:
        button, coordinator = _make_button()
        coordinator.data = None
        assert button.extra_state_attributes is None


def _make_cover_button() -> tuple[SolarCoverResetCoverButton, MagicMock]:
    coordinator = MagicMock()
    coordinator.async_request_refresh = AsyncMock()
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.title = "Zone: Test"
    button = SolarCoverResetCoverButton(coordinator, entry, "cover.living_a")
    return button, coordinator


class TestResetCoverButton:
    def test_unique_id_scheme(self) -> None:
        button, _ = _make_cover_button()
        assert button.unique_id == "test_entry_cover_living_a_reset_override"

    def test_device_info_is_shared_zone_device(self) -> None:
        # Per-cover buttons live on the zone device, not their own -- fewer
        # devices in the UI, disambiguated by a translation placeholder instead.
        button, _ = _make_cover_button()
        info = button._attr_device_info
        assert (DOMAIN, "test_entry") in info["identifiers"]
        assert "via_device" not in info

    def test_translation_placeholder_identifies_the_cover(self) -> None:
        button, _ = _make_cover_button()
        assert button._attr_translation_placeholders == {"cover": "living_a"}

    @pytest.mark.asyncio
    async def test_press_resets_only_this_cover(self) -> None:
        button, coordinator = _make_cover_button()
        await button.async_press()
        coordinator.reset_cover_override.assert_called_once_with("cover.living_a")

    @pytest.mark.asyncio
    async def test_press_awaits_refresh(self) -> None:
        button, coordinator = _make_cover_button()
        await button.async_press()
        coordinator.async_request_refresh.assert_awaited_once_with()

    def test_extra_state_attributes_reports_this_covers_intent(self) -> None:
        button, coordinator = _make_cover_button()
        coordinator.data.covers = {
            "cover.living_a": CoverSnapshot(
                commanded_position=50.0,
                manual_override_until="2026-01-01T00:00:00+00:00",
                intent=Intent.MANUAL_OVERRIDE,
            )
        }
        assert button.extra_state_attributes == {"intent": "manual_override"}

    def test_extra_state_attributes_none_when_cover_not_in_snapshot(self) -> None:
        button, coordinator = _make_cover_button()
        coordinator.data.covers = {}
        assert button.extra_state_attributes is None

    def test_extra_state_attributes_none_before_first_refresh(self) -> None:
        button, coordinator = _make_cover_button()
        coordinator.data = None
        assert button.extra_state_attributes is None
