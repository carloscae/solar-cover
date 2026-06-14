"""Tests for coordinator safety guards: horizon, enabled flag, state persistence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.solar_cover.const import CONF_STABILITY_DELAY, Intent
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
            config_entry=MagicMock(entry_id="test_entry"),
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


class TestManualOverride:
    @staticmethod
    def _wire_solar(coord: SolarCoverCoordinator) -> None:
        # Sun high and dead-centre in the FOV with clear weather, so the only
        # thing that can produce MANUAL_OVERRIDE is the active override.
        coord._solar.sun_position = MagicMock(return_value=(180.0, 45.0))
        coord._solar.hourly_curve = MagicMock(return_value=[])
        coord._solar.fov_window = MagicMock(return_value=(None, None))

    @pytest.mark.asyncio
    async def test_active_override_holds_position(self) -> None:
        coord = _make_coordinator()
        self._wire_solar(coord)
        coord.hass.states.get = MagicMock(return_value=None)
        coord.hass.services.async_call = AsyncMock()
        coord._last_intent = Intent.SHADING
        coord._last_commanded = 30.0
        coord._manual_override_until = datetime.now(tz=UTC) + timedelta(minutes=120)

        data = await coord._async_update_data()

        # Override wins, and the coordinator must NOT drive to the rest position.
        assert data.intent == Intent.MANUAL_OVERRIDE
        assert coord.hass.services.async_call.await_count == 0
        assert data.commanded_position == pytest.approx(30.0)
        # The hold timer is surfaced, and the reason matches the committed intent.
        assert data.manual_override_until is not None
        assert data.reason.startswith("Manual override")


class TestResetTimers:
    def test_reset_timers_clears_both_holds(self) -> None:
        coord = _make_coordinator()
        coord._manual_override_until = datetime.now(tz=UTC) + timedelta(minutes=60)
        coord._pending_intent = Intent.INACTIVE_OVERCAST
        coord._pending_since = datetime.now(tz=UTC)

        coord.reset_timers()

        assert coord._manual_override_until is None
        assert coord._pending_intent is None
        assert coord._pending_since is None

    def test_reset_timers_triggers_refresh(self) -> None:
        coord = _make_coordinator()
        coord.reset_timers()
        coord.hass.async_create_task.assert_called_once()

    def test_reset_timers_bypasses_stability_hold(self) -> None:
        # With a delay configured and SHADING committed, a worsening candidate
        # would normally open a fresh hold. After reset_timers the very next
        # evaluation must commit immediately -- otherwise the button just
        # restarts the delay instead of bypassing it.
        coord = _make_coordinator()
        coord._integration = {CONF_STABILITY_DELAY: 10}
        coord._last_intent = Intent.SHADING

        coord.reset_timers()

        now = datetime.now(tz=UTC)
        assert coord._evaluate_stability(Intent.INACTIVE_OVERCAST, now) is True
        assert coord._pending_since is None


class TestExternalMoveDetection:
    """_handle_cover_state_change auto-sets override on external cover moves."""

    def _make_event(
        self,
        position: float,
        is_opening: bool = False,
        is_closing: bool = False,
    ) -> MagicMock:
        """Build a fake state_changed event."""
        state = MagicMock()
        state.state = "open"
        state.attributes = {"current_position": position}
        if is_opening:
            state.attributes["is_opening"] = True
        if is_closing:
            state.attributes["is_closing"] = True
        event = MagicMock()
        event.data = {"new_state": state}
        return event

    def test_external_move_sets_override(self) -> None:
        """Large position divergence after debounce window triggers override."""
        coord = _make_coordinator()
        coord._last_commanded = 50.0
        # last_command_time is old (> 30 s ago)
        coord._last_command_time = datetime.now(tz=UTC) - timedelta(seconds=60)

        coord._handle_cover_state_change(self._make_event(80.0))

        assert coord._manual_override_until is not None
        assert coord._last_commanded == pytest.approx(80.0)
        coord.hass.async_create_task.assert_called()

    def test_recent_command_debounce_suppresses_small_delta(self) -> None:
        """Motor coasting a few percent past the commanded position within the
        debounce window is treated as an echo and does not set an override."""
        coord = _make_coordinator()
        coord._last_commanded = 50.0
        # 4 % delta is above hysteresis (3 %) but within the coasting margin
        # (2 × 3 % = 6 %), so a change arriving 5 s after a command is debounced.
        coord._last_command_time = datetime.now(tz=UTC) - timedelta(seconds=5)

        coord._handle_cover_state_change(self._make_event(54.0))

        assert coord._manual_override_until is None
        coord.hass.async_create_task.assert_not_called()

    def test_large_delta_within_debounce_sets_override(self) -> None:
        """An immediate manual countermand (large position divergence) must set an
        override even if it arrives within the 30-second debounce window."""
        coord = _make_coordinator()
        coord._last_commanded = 80.0
        # User closes the shade to 0 % just 5 s after the coordinator opened it.
        coord._last_command_time = datetime.now(tz=UTC) - timedelta(seconds=5)

        coord._handle_cover_state_change(self._make_event(0.0))

        assert coord._manual_override_until is not None
        assert coord._manual_position == pytest.approx(0.0)
        assert coord._last_commanded == pytest.approx(0.0)
        coord.hass.async_create_task.assert_called()

    def test_coasting_margin_boundary_sets_override(self) -> None:
        """A delta exactly equal to the coasting margin (2 × hysteresis) is NOT
        suppressed -- the strict less-than means the boundary favours the user."""
        coord = _make_coordinator()
        coord._last_commanded = 50.0
        # delta = 6.0 == 2 × DEFAULT_HYSTERESIS (3.0); strict '<' lets it through.
        coord._last_command_time = datetime.now(tz=UTC) - timedelta(seconds=5)

        coord._handle_cover_state_change(self._make_event(56.0))

        assert coord._manual_override_until is not None
        assert coord._manual_position == pytest.approx(56.0)

    def test_is_closing_suppresses_trigger(self) -> None:
        """Cover travelling to coordinator-commanded position is not external."""
        coord = _make_coordinator()
        coord._last_commanded = 50.0
        coord._last_command_time = datetime.now(tz=UTC) - timedelta(seconds=60)

        coord._handle_cover_state_change(self._make_event(80.0, is_closing=True))

        assert coord._manual_override_until is None

    def test_delta_below_hysteresis_does_not_trigger(self) -> None:
        """Small position noise does not count as a manual move."""
        coord = _make_coordinator()
        coord._last_commanded = 50.0
        coord._last_command_time = datetime.now(tz=UTC) - timedelta(seconds=60)
        # Default hysteresis is 3 %; move of 1 % is inside the dead-band.
        coord._handle_cover_state_change(self._make_event(51.0))

        assert coord._manual_override_until is None

    def test_disabled_automation_skips_detection(self) -> None:
        """No override is set when automation is turned off."""
        coord = _make_coordinator()
        coord._last_commanded = 50.0
        coord._last_command_time = datetime.now(tz=UTC) - timedelta(seconds=60)
        coord._enabled = False

        coord._handle_cover_state_change(self._make_event(80.0))

        assert coord._manual_override_until is None

    def test_no_last_commanded_skips_detection(self) -> None:
        """If the coordinator has never commanded a position, skip detection."""
        coord = _make_coordinator()
        coord._last_commanded = None
        coord._last_command_time = datetime.now(tz=UTC) - timedelta(seconds=60)

        coord._handle_cover_state_change(self._make_event(80.0))

        assert coord._manual_override_until is None

    def test_none_new_state_skips_detection(self) -> None:
        """Event with no new_state (entity removed) is handled gracefully."""
        coord = _make_coordinator()
        coord._last_commanded = 50.0
        event = MagicMock()
        event.data = {"new_state": None}

        coord._handle_cover_state_change(event)  # must not raise

        assert coord._manual_override_until is None
