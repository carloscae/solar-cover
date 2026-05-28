"""Tests for coordinator safety guards: horizon, enabled flag, state persistence."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.solar_cover.coordinator import SolarCoverCoordinator


def _make_coordinator(hass: MagicMock | None = None) -> SolarCoverCoordinator:
    if hass is None:
        hass = MagicMock()
        hass.data = {}
        hass.async_create_task = MagicMock()
    zone = {
        "name": "test",
        "cover_type": "vertical",
        "azimuth": 180,
        "fov_left": 90,
        "fov_right": 90,
        "elevation_threshold": 25.0,
        "cover_entities": ["cover.test"],
    }
    with patch(
        "custom_components.solar_cover.coordinator.Store", autospec=True
    ) as MockStore:
        MockStore.return_value.async_load = AsyncMock(return_value=None)
        MockStore.return_value.async_save = AsyncMock()
        coord = SolarCoverCoordinator(
            hass=hass,
            zone_data=zone,
            integration_data={},
            solar_engine=MagicMock(),
            entry_id="test_entry",
        )
        coord._store = MockStore.return_value
    return coord


class TestEnabledFlag:
    def test_enabled_by_default(self) -> None:
        coord = _make_coordinator()
        assert coord.enabled is True

    def test_set_enabled_false(self) -> None:
        coord = _make_coordinator()
        coord.set_enabled(False)
        assert coord.enabled is False

    def test_set_enabled_true(self) -> None:
        coord = _make_coordinator()
        coord._enabled = False
        coord.set_enabled(True)
        assert coord.enabled is True

    def test_set_enabled_triggers_refresh(self) -> None:
        coord = _make_coordinator()
        coord.set_enabled(False)
        coord.hass.async_create_task.assert_called_once()


class TestStatePersistence:
    @pytest.mark.asyncio
    async def test_restore_state_loads_last_commanded(self) -> None:
        coord = _make_coordinator()
        coord._store.async_load = AsyncMock(return_value={"last_commanded": 42.5})
        await coord.async_restore_state()
        assert coord._last_commanded == pytest.approx(42.5)

    @pytest.mark.asyncio
    async def test_restore_state_ignores_missing_store(self) -> None:
        coord = _make_coordinator()
        coord._store.async_load = AsyncMock(return_value=None)
        await coord.async_restore_state()
        assert coord._last_commanded is None

    @pytest.mark.asyncio
    async def test_restore_state_ignores_empty_store(self) -> None:
        coord = _make_coordinator()
        coord._store.async_load = AsyncMock(return_value={})
        await coord.async_restore_state()
        assert coord._last_commanded is None
