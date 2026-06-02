"""Tests for the coordinator stability-delay state machine."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.solar_cover.const import (
    CONF_STABILITY_DELAY,
    CONF_STABILITY_DELAY_ON_RECOVERY,
    CONF_STABILITY_DELAY_ON_WORSENING,
    Intent,
)
from custom_components.solar_cover.coordinator import SolarCoverCoordinator
from custom_components.solar_cover.intent import IntentResult


def _make_coordinator(
    integration: dict[str, Any] | None = None,
) -> SolarCoverCoordinator:
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
            integration_data=integration or {},
            solar_engine=MagicMock(),
            entry_id="test_entry",
        )
        coord._store = MockStore.return_value
    return coord


_T0 = datetime(2026, 5, 30, 12, 0, 0, tzinfo=UTC)


class TestNoDelayConfigured:
    def test_intent_change_commits_immediately(self) -> None:
        coord = _make_coordinator()  # delay defaults to 0
        coord._last_intent = Intent.SHADING
        assert coord._evaluate_stability(Intent.INACTIVE_OVERCAST, _T0) is True
        assert coord._pending_intent is None
        assert coord._pending_since is None


class TestDelayHolds:
    def test_unchanged_intent_commits_and_clears_pending(self) -> None:
        # The equality branch runs regardless of the configured delay.
        coord = _make_coordinator({CONF_STABILITY_DELAY: 10})
        coord._last_intent = Intent.SHADING
        coord._pending_intent = Intent.INACTIVE_OVERCAST
        coord._pending_since = _T0
        assert coord._evaluate_stability(Intent.SHADING, _T0) is True
        assert coord._pending_intent is None
        assert coord._pending_since is None

    def test_holds_until_delay_elapsed_then_commits_once(self) -> None:
        coord = _make_coordinator({CONF_STABILITY_DELAY: 10})
        coord._last_intent = Intent.SHADING

        # First evaluation starts the clock and holds.
        assert coord._evaluate_stability(Intent.INACTIVE_OVERCAST, _T0) is False
        assert coord._pending_intent == Intent.INACTIVE_OVERCAST
        assert coord._pending_since == _T0

        # Still within the window -- keep holding.
        assert (
            coord._evaluate_stability(
                Intent.INACTIVE_OVERCAST, _T0 + timedelta(minutes=5)
            )
            is False
        )

        # Window elapsed -- commit and clear pending.
        assert (
            coord._evaluate_stability(
                Intent.INACTIVE_OVERCAST, _T0 + timedelta(minutes=10)
            )
            is True
        )
        assert coord._pending_intent is None
        assert coord._pending_since is None

    def test_oscillation_back_clears_pending_without_commit(self) -> None:
        coord = _make_coordinator({CONF_STABILITY_DELAY: 10})
        coord._last_intent = Intent.SHADING

        assert coord._evaluate_stability(Intent.INACTIVE_OVERCAST, _T0) is False
        assert coord._pending_intent == Intent.INACTIVE_OVERCAST

        # Conditions recover before the delay elapsed -- back to last committed.
        assert (
            coord._evaluate_stability(Intent.SHADING, _T0 + timedelta(minutes=3))
            is True
        )
        assert coord._pending_intent is None
        assert coord._pending_since is None

    def test_candidate_change_keeps_clock_running(self) -> None:
        # Two different "worsening" candidates alternating must NOT keep
        # resetting the clock -- otherwise a stormy day (clouds + wind flipping)
        # would pin the cover deployed forever. The clock measures time since
        # we diverged from the committed intent.
        coord = _make_coordinator({CONF_STABILITY_DELAY: 10})
        coord._last_intent = Intent.SHADING

        assert coord._evaluate_stability(Intent.INACTIVE_OVERCAST, _T0) is False
        assert coord._pending_since == _T0

        # A different worsening candidate arrives -- clock keeps its origin.
        t1 = _T0 + timedelta(minutes=4)
        assert coord._evaluate_stability(Intent.INACTIVE_WEATHER, t1) is False
        assert coord._pending_intent == Intent.INACTIVE_WEATHER
        assert coord._pending_since == _T0

        # Delay measured from the original divergence -- commits at T0 + 10.
        assert (
            coord._evaluate_stability(
                Intent.INACTIVE_OVERCAST, _T0 + timedelta(minutes=10)
            )
            is True
        )
        assert coord._pending_intent is None
        assert coord._pending_since is None


class TestDirectionFlags:
    def test_worsening_disabled_commits_worsening_immediately(self) -> None:
        coord = _make_coordinator(
            {
                CONF_STABILITY_DELAY: 10,
                CONF_STABILITY_DELAY_ON_WORSENING: False,
                CONF_STABILITY_DELAY_ON_RECOVERY: True,
            }
        )
        coord._last_intent = Intent.SHADING
        # Worsening transition -- not delayed.
        assert coord._evaluate_stability(Intent.INACTIVE_OVERCAST, _T0) is True
        assert coord._pending_intent is None

    def test_worsening_disabled_still_delays_recovery(self) -> None:
        coord = _make_coordinator(
            {
                CONF_STABILITY_DELAY: 10,
                CONF_STABILITY_DELAY_ON_WORSENING: False,
                CONF_STABILITY_DELAY_ON_RECOVERY: True,
            }
        )
        coord._last_intent = Intent.INACTIVE_OVERCAST
        assert coord._evaluate_stability(Intent.SHADING, _T0) is False
        assert coord._pending_intent == Intent.SHADING

    def test_recovery_disabled_commits_recovery_immediately(self) -> None:
        coord = _make_coordinator(
            {
                CONF_STABILITY_DELAY: 10,
                CONF_STABILITY_DELAY_ON_WORSENING: True,
                CONF_STABILITY_DELAY_ON_RECOVERY: False,
            }
        )
        coord._last_intent = Intent.INACTIVE_WEATHER
        assert coord._evaluate_stability(Intent.SHADING, _T0) is True
        assert coord._pending_intent is None

    def test_recovery_disabled_still_delays_worsening(self) -> None:
        coord = _make_coordinator(
            {
                CONF_STABILITY_DELAY: 10,
                CONF_STABILITY_DELAY_ON_WORSENING: True,
                CONF_STABILITY_DELAY_ON_RECOVERY: False,
            }
        )
        coord._last_intent = Intent.SHADING
        assert coord._evaluate_stability(Intent.INACTIVE_WEATHER, _T0) is False
        assert coord._pending_intent == Intent.INACTIVE_WEATHER


class TestClassifyTransition:
    def test_shading_to_inactive_is_worsening(self) -> None:
        coord = _make_coordinator()
        coord._last_intent = Intent.SHADING
        assert coord._classify_transition(Intent.INACTIVE_OVERCAST) == "worsening"
        assert coord._classify_transition(Intent.INACTIVE_WEATHER) == "worsening"
        assert coord._classify_transition(Intent.INACTIVE_SUN_LOW) == "worsening"

    def test_inactive_weather_to_shading_is_recovery(self) -> None:
        coord = _make_coordinator()
        coord._last_intent = Intent.INACTIVE_OVERCAST
        assert coord._classify_transition(Intent.SHADING) == "recovery"
        coord._last_intent = Intent.INACTIVE_WEATHER
        assert coord._classify_transition(Intent.SHADING) == "recovery"

    def test_inactive_to_inactive_is_other(self) -> None:
        coord = _make_coordinator()
        coord._last_intent = Intent.INACTIVE_SUN_LOW
        assert coord._classify_transition(Intent.INACTIVE_OUTSIDE_FOV) == "other"

    def test_other_transition_commits_immediately(self) -> None:
        coord = _make_coordinator(
            {
                CONF_STABILITY_DELAY: 10,
                CONF_STABILITY_DELAY_ON_WORSENING: True,
                CONF_STABILITY_DELAY_ON_RECOVERY: True,
            }
        )
        coord._last_intent = Intent.INACTIVE_SUN_LOW
        # "other" direction is never delayed regardless of flags.
        assert coord._evaluate_stability(Intent.INACTIVE_OUTSIDE_FOV, _T0) is True
        assert coord._pending_intent is None

    def test_first_run_commits_immediately(self) -> None:
        coord = _make_coordinator({CONF_STABILITY_DELAY: 10})
        # _last_intent is None on first evaluation.
        assert coord._evaluate_stability(Intent.SHADING, _T0) is True
        assert coord._pending_intent is None


class TestStabilityEndToEnd:
    """Drive the full _async_update_data loop to verify the hold wiring:
    a held candidate suppresses cover commands and the snapshot keeps
    exposing the last committed intent until the delay elapses.
    """

    @staticmethod
    def _wire_solar(coord: SolarCoverCoordinator) -> None:
        coord._solar.sun_position = MagicMock(return_value=(180.0, 45.0))
        coord._solar.hourly_curve = MagicMock(return_value=[])
        coord._solar.fov_window = MagicMock(return_value=(None, None))

    async def test_hold_then_commit_through_update_loop(self) -> None:
        coord = _make_coordinator({CONF_STABILITY_DELAY: 10})
        self._wire_solar(coord)
        coord.hass.states.get = MagicMock(return_value=None)
        coord.hass.services.async_call = AsyncMock()

        intents = [
            IntentResult(Intent.SHADING, 50.0, "Shading", []),
            IntentResult(Intent.INACTIVE_OVERCAST, None, "Idle (overcast)", []),
            IntentResult(Intent.INACTIVE_OVERCAST, None, "Idle (overcast)", []),
            IntentResult(Intent.INACTIVE_OVERCAST, None, "Idle (overcast)", []),
        ]
        times = [
            _T0,                              # run 1: _async_update_data now -> SHADING
            _T0 + timedelta(minutes=1),       # run 1: _command_covers now
            _T0 + timedelta(minutes=5),       # run 2: _async_update_data now -> worsening held
            _T0 + timedelta(minutes=11),      # run 3: _async_update_data now -> still held (6 min < 10)
            _T0 + timedelta(minutes=16),      # run 4: _async_update_data now -> elapsed (11 min >= 10)
            _T0 + timedelta(minutes=16),      # run 4: _command_covers now
        ]

        with (
            patch(
                "custom_components.solar_cover.coordinator.evaluate_intent",
                side_effect=intents,
            ),
            patch("custom_components.solar_cover.coordinator.datetime") as mock_dt,
        ):
            mock_dt.now.side_effect = times

            # First run -- SHADING commits immediately, cover commanded to 50.
            data = await coord._async_update_data()
            assert data.intent == Intent.SHADING
            assert coord.hass.services.async_call.await_count == 1

            # Worsening candidate arrives -- held, no new command, snapshot
            # still reports the committed SHADING intent. The pending timer is
            # now surfaced with the candidate that is waiting to commit.
            data = await coord._async_update_data()
            assert data.intent == Intent.SHADING
            assert coord.hass.services.async_call.await_count == 1
            assert data.stability_pending_until is not None
            assert data.pending_intent == Intent.INACTIVE_OVERCAST.value

            # Still within the window -- keep holding.
            data = await coord._async_update_data()
            assert data.intent == Intent.SHADING
            assert coord.hass.services.async_call.await_count == 1

            # Delay elapsed -- commit the overcast intent and command the cover.
            # The pending timer clears once the candidate is committed.
            data = await coord._async_update_data()
            assert data.intent == Intent.INACTIVE_OVERCAST
            assert coord.hass.services.async_call.await_count == 2
            assert data.stability_pending_until is None
            assert data.pending_intent is None
