"""Tests for cover command behaviour: tilt axis routing and manual-position restore.

Covers two correctness fixes:
- Bug A: venetian (tilt) zones must drive set_cover_tilt_position, not position.
- Bug B: a transient weather retraction during a manual override must not
  permanently discard the user's manual position.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.solar_cover.const import Intent
from custom_components.solar_cover.coordinator import SolarCoverCoordinator
from custom_components.solar_cover.intent import IntentResult

_T0 = datetime(2026, 6, 8, 12, 0, 0, tzinfo=UTC)


def _make_coordinator(
    cover_type: str = "vertical",
    integration: dict[str, Any] | None = None,
) -> SolarCoverCoordinator:
    hass = MagicMock()
    hass.data = {}
    hass.async_create_task = MagicMock()
    zone = {
        "name": "test",
        "cover_type": cover_type,
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
            integration_data=integration or {},
            solar_engine=MagicMock(),
            config_entry=MagicMock(entry_id="test_entry"),
        )
        coord._store = MockStore.return_value
    return coord


class TestCommandAxis:
    """Bug A -- the geometry output must reach the axis the cover actually uses."""

    @pytest.mark.asyncio
    async def test_tilt_uses_tilt_service(self) -> None:
        coord = _make_coordinator(cover_type="tilt")
        coord.hass.services.async_call = AsyncMock()
        await coord._command_covers(50.0)
        call = coord.hass.services.async_call.call_args
        assert call.args[1] == "set_cover_tilt_position"
        assert call.args[2]["tilt_position"] == 50
        assert "position" not in call.args[2]

    @pytest.mark.asyncio
    async def test_vertical_uses_position_service(self) -> None:
        coord = _make_coordinator(cover_type="vertical")
        coord.hass.services.async_call = AsyncMock()
        await coord._command_covers(50.0)
        call = coord.hass.services.async_call.call_args
        assert call.args[1] == "set_cover_position"
        assert call.args[2]["position"] == 50
        assert "tilt_position" not in call.args[2]


class TestManualPositionRestore:
    """Bug B -- weather retraction mid-override must not erase the manual position."""

    @staticmethod
    def _wire_solar(coord: SolarCoverCoordinator) -> None:
        coord._solar.sun_position = MagicMock(return_value=(180.0, 45.0))
        coord._solar.hourly_curve = MagicMock(return_value=[])
        coord._solar.fov_window = MagicMock(return_value=(None, None))

    @pytest.mark.asyncio
    async def test_manual_position_restored_after_weather(self) -> None:
        coord = _make_coordinator()  # stability delay defaults to 0
        self._wire_solar(coord)
        coord.hass.states.get = MagicMock(return_value=None)
        coord.hass.services.async_call = AsyncMock()

        # User has a manual override holding the cover at 70%.
        coord._last_commanded = 70.0
        coord._manual_position = 70.0
        coord._last_intent = Intent.MANUAL_OVERRIDE

        results = [
            IntentResult(Intent.INACTIVE_WEATHER, None, "weather", []),
            IntentResult(Intent.MANUAL_OVERRIDE, None, "override", []),
        ]
        with (
            patch(
                "custom_components.solar_cover.coordinator.evaluate_intent",
                side_effect=results,
            ),
            patch("custom_components.solar_cover.coordinator.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = _T0

            # Wind picks up -> safety retract to the rest position (0).
            await coord._async_update_data()
            assert coord.hass.services.async_call.await_count == 1
            assert coord.hass.services.async_call.call_args.args[2]["position"] == 0
            assert coord._last_commanded == 0.0

            # Wind drops, override still active -> the 70% manual position is
            # restored rather than left at the rest position.
            await coord._async_update_data()
            assert coord.hass.services.async_call.await_count == 2
            assert coord.hass.services.async_call.call_args.args[2]["position"] == 70
            assert coord._last_commanded == 70.0

    @pytest.mark.asyncio
    async def test_steady_override_does_not_recommand(self) -> None:
        # While holding at the manual position with no drift, the coordinator
        # must not keep re-issuing commands (which would fight the user).
        coord = _make_coordinator()
        self._wire_solar(coord)
        coord.hass.states.get = MagicMock(return_value=None)
        coord.hass.services.async_call = AsyncMock()

        coord._last_commanded = 70.0
        coord._manual_position = 70.0
        coord._last_intent = Intent.MANUAL_OVERRIDE

        with (
            patch(
                "custom_components.solar_cover.coordinator.evaluate_intent",
                return_value=IntentResult(Intent.MANUAL_OVERRIDE, None, "override", []),
            ),
            patch("custom_components.solar_cover.coordinator.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = _T0
            await coord._async_update_data()
            assert coord.hass.services.async_call.await_count == 0


class TestCommandFailureHandling:
    """A failed cover command must not be recorded as committed (else hysteresis
    would suppress every retry and strand the cover at the wrong position)."""

    @staticmethod
    def _wire_solar(coord: SolarCoverCoordinator) -> None:
        coord._solar.sun_position = MagicMock(return_value=(180.0, 45.0))
        coord._solar.hourly_curve = MagicMock(return_value=[])
        coord._solar.fov_window = MagicMock(return_value=(None, None))

    @pytest.mark.asyncio
    async def test_failed_command_not_recorded_then_retried(self) -> None:
        coord = _make_coordinator()
        self._wire_solar(coord)
        coord.hass.states.get = MagicMock(return_value=None)
        coord.hass.services.async_call = AsyncMock(
            side_effect=HomeAssistantError("device offline")
        )

        with (
            patch(
                "custom_components.solar_cover.coordinator.evaluate_intent",
                return_value=IntentResult(Intent.SHADING, 50.0, "shading", []),
            ),
            patch("custom_components.solar_cover.coordinator.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = _T0

            # Command raises -> position is NOT recorded as committed.
            await coord._async_update_data()
            assert coord.hass.services.async_call.await_count == 1
            assert coord._last_commanded is None

            # Next cycle retries (still failing, still not recorded).
            await coord._async_update_data()
            assert coord.hass.services.async_call.await_count == 2
            assert coord._last_commanded is None

            # Device recovers -> the move finally lands and is recorded.
            coord.hass.services.async_call.side_effect = None
            await coord._async_update_data()
            assert coord.hass.services.async_call.await_count == 3
            assert coord._last_commanded == 50.0

    @pytest.mark.asyncio
    async def test_override_restore_works_below_horizon(self) -> None:
        # The user's explicit manual position must be restorable even at night;
        # the below-horizon command suppression applies to automatic intents only.
        coord = _make_coordinator()
        coord._solar.sun_position = MagicMock(return_value=(180.0, -8.0))
        coord._solar.hourly_curve = MagicMock(return_value=[])
        coord._solar.fov_window = MagicMock(return_value=(None, None))
        coord.hass.states.get = MagicMock(return_value=None)
        coord.hass.services.async_call = AsyncMock()

        coord._last_commanded = 0.0  # drifted off the manual position
        coord._manual_position = 70.0
        coord._last_intent = Intent.MANUAL_OVERRIDE

        with (
            patch(
                "custom_components.solar_cover.coordinator.evaluate_intent",
                return_value=IntentResult(Intent.MANUAL_OVERRIDE, None, "override", []),
            ),
            patch("custom_components.solar_cover.coordinator.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = _T0
            await coord._async_update_data()
            assert coord.hass.services.async_call.await_count == 1
            assert coord.hass.services.async_call.call_args.args[2]["position"] == 70
            assert coord._last_commanded == 70.0


class TestExternalMoveTiltAxis:
    """Bug A -- external-move detection must watch the tilt axis on tilt zones."""

    @staticmethod
    def _event(attrs: dict[str, Any]) -> MagicMock:
        state = MagicMock()
        state.state = "open"
        state.attributes = attrs
        event = MagicMock()
        event.data = {"new_state": state}
        return event

    def test_tilt_external_move_sets_override(self) -> None:
        coord = _make_coordinator(cover_type="tilt")
        coord._last_commanded = 70.0
        coord._handle_cover_state_change(self._event({"current_tilt_position": 30}))
        assert coord._manual_override_until is not None
        assert coord._manual_position == 30.0
        assert coord._last_commanded == 30.0

    def test_tilt_zone_ignores_missing_tilt_position(self) -> None:
        # A cover that reports no tilt position must not be read as "moved to 0".
        coord = _make_coordinator(cover_type="tilt")
        coord._last_commanded = 70.0
        coord._handle_cover_state_change(self._event({"current_position": 30}))
        assert coord._manual_override_until is None
        assert coord._manual_position is None
