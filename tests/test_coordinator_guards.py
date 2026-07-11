"""Tests for coordinator safety guards: enabled flag, per-cover persistence,
per-cover external-move detection, reset (all + single-cover)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.solar_cover.const import CONF_STABILITY_DELAY, Intent
from custom_components.solar_cover.coordinator import (
    SolarCoverCoordinator,
    _SolarCoverStore,
)


def _make_coordinator(
    covers: list[str] | None = None,
    hass: MagicMock | None = None,
) -> SolarCoverCoordinator:
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
        "cover_entities": covers if covers is not None else ["cover.test"],
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


class TestStorePayload:
    def test_payload_shapes_per_cover(self) -> None:
        coord = _make_coordinator(covers=["cover.a", "cover.b"])
        until = datetime.now(tz=UTC) + timedelta(minutes=30)
        coord._last_commanded = {"cover.a": 70.0, "cover.b": 0.0}
        coord._manual_position = {"cover.a": 70.0}
        coord._manual_override_until = {"cover.a": until}
        payload = coord._store_payload()
        assert payload == {
            "covers": {
                "cover.a": {
                    "last_commanded": 70.0,
                    "manual_position": 70.0,
                    "manual_override_until": until.isoformat(),
                },
                "cover.b": {
                    "last_commanded": 0.0,
                    "manual_position": None,
                    "manual_override_until": None,
                },
            }
        }


class TestStatePersistence:
    @pytest.mark.asyncio
    async def test_restore_state_ignores_missing_store(self) -> None:
        coord = _make_coordinator()
        coord._store.async_load = AsyncMock(return_value=None)
        await coord.async_restore_state()
        assert coord._last_commanded == {}

    @pytest.mark.asyncio
    async def test_restore_state_ignores_empty_store(self) -> None:
        coord = _make_coordinator()
        coord._store.async_load = AsyncMock(return_value={})
        await coord.async_restore_state()
        assert coord._last_commanded == {}

    @pytest.mark.asyncio
    async def test_restore_state_loads_per_cover_last_commanded(self) -> None:
        coord = _make_coordinator(covers=["cover.a", "cover.b"])
        coord._store.async_load = AsyncMock(
            return_value={
                "covers": {
                    "cover.a": {
                        "last_commanded": 42.5,
                        "manual_position": None,
                        "manual_override_until": None,
                    },
                    "cover.b": {
                        "last_commanded": 10.0,
                        "manual_position": None,
                        "manual_override_until": None,
                    },
                }
            }
        )
        await coord.async_restore_state()
        assert coord._last_commanded == {"cover.a": 42.5, "cover.b": 10.0}

    @pytest.mark.asyncio
    async def test_restore_state_rehydrates_active_override(self) -> None:
        coord = _make_coordinator()
        until = (datetime.now(tz=UTC) + timedelta(minutes=90)).isoformat()
        coord._store.async_load = AsyncMock(
            return_value={
                "covers": {
                    "cover.test": {
                        "last_commanded": 70.0,
                        "manual_position": 70.0,
                        "manual_override_until": until,
                    }
                }
            }
        )
        await coord.async_restore_state()
        assert coord._last_commanded == {"cover.test": 70.0}
        assert coord._manual_position == {"cover.test": 70.0}
        assert coord._manual_override_until["cover.test"].isoformat() == until

    @pytest.mark.asyncio
    async def test_restore_state_drops_expired_override(self) -> None:
        coord = _make_coordinator()
        until = (datetime.now(tz=UTC) - timedelta(minutes=5)).isoformat()
        coord._store.async_load = AsyncMock(
            return_value={
                "covers": {
                    "cover.test": {
                        "last_commanded": 70.0,
                        "manual_position": 70.0,
                        "manual_override_until": until,
                    }
                }
            }
        )
        await coord.async_restore_state()
        assert coord._last_commanded == {"cover.test": 70.0}
        assert "cover.test" not in coord._manual_override_until
        assert "cover.test" not in coord._manual_position

    @pytest.mark.asyncio
    async def test_restore_state_prunes_stale_cover_keys(self) -> None:
        # A cover dropped from cover_entities must be pruned from the store and
        # the store re-saved, or its hold lingers forever.
        coord = _make_coordinator(covers=["cover.test"])
        coord._store.async_load = AsyncMock(
            return_value={
                "covers": {
                    "cover.test": {
                        "last_commanded": 20.0,
                        "manual_position": None,
                        "manual_override_until": None,
                    },
                    "cover.gone": {
                        "last_commanded": 99.0,
                        "manual_position": None,
                        "manual_override_until": None,
                    },
                }
            }
        )
        await coord.async_restore_state()
        assert coord._last_commanded == {"cover.test": 20.0}
        coord._store.async_save.assert_awaited()


class TestStoreMigration:
    @pytest.mark.asyncio
    async def test_v1_payload_migrates_to_empty_covers(self) -> None:
        # The subclass override itself returns no active overrides for any pre-v2
        # payload. Constructed via __new__ to skip Store.__init__ (which needs a
        # real hass); _async_migrate_func does not use self.
        store = _SolarCoverStore.__new__(_SolarCoverStore)
        result = await store._async_migrate_func(
            1,
            1,
            {
                "last_commanded": 70.0,
                "manual_position": 70.0,
                "manual_override_until": "2026-07-11T18:00:00+00:00",
            },
        )
        assert result == {"covers": {}}


class TestRestoreEnabled:
    def test_restore_enabled_sets_flag_without_refresh(self) -> None:
        coord = _make_coordinator()
        coord.restore_enabled(False)
        assert coord.enabled is False
        coord.hass.async_create_task.assert_not_called()

    def test_restore_enabled_true(self) -> None:
        coord = _make_coordinator()
        coord._enabled = False
        coord.restore_enabled(True)
        assert coord.enabled is True
        coord.hass.async_create_task.assert_not_called()


class TestZoneIntentAggregation:
    @staticmethod
    def _wire_solar(coord: SolarCoverCoordinator) -> None:
        coord._solar.sun_position = MagicMock(return_value=(180.0, 45.0))
        coord._solar.hourly_curve = MagicMock(return_value=[])
        coord._solar.fov_window = MagicMock(return_value=(None, None))

    @pytest.mark.asyncio
    async def test_all_held_reports_manual_override(self) -> None:
        coord = _make_coordinator()  # single cover
        self._wire_solar(coord)
        coord.hass.states.get = MagicMock(return_value=None)
        coord.hass.services.async_call = AsyncMock()
        coord._last_intent = Intent.SHADING
        coord._last_commanded = {"cover.test": 30.0}
        coord._manual_position = {"cover.test": 30.0}
        coord._manual_override_until = {
            "cover.test": datetime.now(tz=UTC) + timedelta(minutes=120)
        }

        data = await coord._async_update_data()

        assert data.intent == Intent.MANUAL_OVERRIDE
        assert coord.hass.services.async_call.await_count == 0
        # Read per-cover snapshot fields (they survive the Task 3 removal of the
        # transitional zone-level commanded_position / manual_override_until).
        assert data.covers["cover.test"].commanded_position == pytest.approx(30.0)
        assert data.covers["cover.test"].manual_override_until is not None
        assert data.reason.startswith("Manual override")
        assert data.covers["cover.test"].intent == Intent.MANUAL_OVERRIDE

    @pytest.mark.asyncio
    async def test_partial_hold_keeps_zone_on_automatic_intent(self) -> None:
        coord = _make_coordinator(covers=["cover.a", "cover.b"])
        self._wire_solar(coord)
        coord.hass.states.get = MagicMock(return_value=None)
        coord.hass.services.async_call = AsyncMock()
        coord._last_commanded = {"cover.a": 30.0, "cover.b": 30.0}
        coord._manual_position = {"cover.a": 30.0}
        coord._manual_override_until = {
            "cover.a": datetime.now(tz=UTC) + timedelta(minutes=120)
        }

        data = await coord._async_update_data()

        # cover.a held, cover.b not -> zone sensor stays on the automatic intent.
        assert data.intent != Intent.MANUAL_OVERRIDE
        assert data.covers["cover.a"].intent == Intent.MANUAL_OVERRIDE
        assert data.covers["cover.b"].intent != Intent.MANUAL_OVERRIDE


class TestResetTimers:
    def test_reset_timers_clears_all_holds(self) -> None:
        coord = _make_coordinator()
        coord._manual_override_until = {
            "cover.test": datetime.now(tz=UTC) + timedelta(minutes=60)
        }
        coord._manual_position = {"cover.test": 40.0}
        coord._pending_intent = Intent.INACTIVE_OVERCAST
        coord._pending_since = datetime.now(tz=UTC)

        coord.reset_timers()

        assert coord._manual_override_until == {}
        assert coord._manual_position == {}
        assert coord._pending_intent is None
        assert coord._pending_since is None

    def test_reset_timers_triggers_refresh(self) -> None:
        coord = _make_coordinator()
        coord.reset_timers()
        assert coord.hass.async_create_task.call_count == 2

    def test_reset_timers_bypasses_stability_hold(self) -> None:
        coord = _make_coordinator()
        coord._integration = {CONF_STABILITY_DELAY: 10}
        coord._last_intent = Intent.SHADING

        coord.reset_timers()

        now = datetime.now(tz=UTC)
        assert coord._evaluate_stability(Intent.INACTIVE_OVERCAST, now) is True
        assert coord._pending_since is None


class TestResetCoverOverride:
    def test_reset_cover_override_clears_only_that_cover(self) -> None:
        coord = _make_coordinator(covers=["cover.a", "cover.b"])
        until = datetime.now(tz=UTC) + timedelta(minutes=60)
        coord._manual_override_until = {"cover.a": until, "cover.b": until}
        coord._manual_position = {"cover.a": 40.0, "cover.b": 60.0}
        coord._pending_intent = Intent.INACTIVE_OVERCAST
        coord._pending_since = datetime.now(tz=UTC)

        coord.reset_cover_override("cover.a")

        assert "cover.a" not in coord._manual_override_until
        assert "cover.a" not in coord._manual_position
        assert coord._manual_override_until["cover.b"] == until
        assert coord._manual_position["cover.b"] == 60.0
        # Zone stability hold is untouched by a per-cover reset.
        assert coord._pending_intent == Intent.INACTIVE_OVERCAST

    def test_reset_cover_override_triggers_refresh(self) -> None:
        coord = _make_coordinator()
        coord.reset_cover_override("cover.test")
        assert coord.hass.async_create_task.call_count == 2


class TestExternalMoveDetection:
    """_handle_cover_state_change keys off event.data['entity_id'] and mutates
    only that cover's per-cover state."""

    def _make_event(
        self,
        entity_id: str,
        position: float,
        is_opening: bool = False,
        is_closing: bool = False,
    ) -> MagicMock:
        state = MagicMock()
        state.state = "opening" if is_opening else "closing" if is_closing else "open"
        state.attributes = {"current_position": position}
        event = MagicMock()
        event.data = {"entity_id": entity_id, "new_state": state}
        return event

    def test_external_move_sets_override_for_that_cover_only(self) -> None:
        coord = _make_coordinator(covers=["cover.a", "cover.b"])
        coord._last_commanded = {"cover.a": 50.0, "cover.b": 50.0}
        coord._last_command_time = {
            "cover.a": datetime.now(tz=UTC) - timedelta(seconds=60)
        }

        coord._handle_cover_state_change(self._make_event("cover.a", 80.0))

        assert coord._manual_override_until["cover.a"] is not None
        assert coord._manual_position["cover.a"] == pytest.approx(80.0)
        assert coord._last_commanded["cover.a"] == pytest.approx(80.0)
        assert "cover.b" not in coord._manual_override_until
        coord.hass.async_create_task.assert_called()

    def test_move_does_not_clear_zone_stability_hold(self) -> None:
        coord = _make_coordinator()
        coord._last_commanded = {"cover.test": 50.0}
        coord._last_command_time = {
            "cover.test": datetime.now(tz=UTC) - timedelta(seconds=60)
        }
        coord._pending_intent = Intent.INACTIVE_OVERCAST
        coord._pending_since = datetime.now(tz=UTC)

        coord._handle_cover_state_change(self._make_event("cover.test", 80.0))

        assert coord._pending_intent == Intent.INACTIVE_OVERCAST
        assert coord._pending_since is not None

    def test_event_without_entity_id_ignored(self) -> None:
        coord = _make_coordinator()
        event = MagicMock()
        state = MagicMock()
        state.state = "open"
        state.attributes = {"current_position": 80.0}
        event.data = {"new_state": state}  # no entity_id

        coord._handle_cover_state_change(event)

        assert coord._manual_override_until == {}

    def test_unconfigured_entity_ignored(self) -> None:
        coord = _make_coordinator(covers=["cover.test"])
        coord._handle_cover_state_change(self._make_event("cover.other", 80.0))
        assert coord._manual_override_until == {}

    def test_debounce_isolation_between_covers(self) -> None:
        # cover.b was just commanded; a genuine move of uncommanded cover.a
        # within 30 s must still arm (not swallowed by cover.b's debounce).
        coord = _make_coordinator(covers=["cover.a", "cover.b"])
        coord._last_commanded = {"cover.a": 50.0, "cover.b": 50.0}
        coord._last_command_time = {"cover.b": datetime.now(tz=UTC)}  # a has no stamp

        coord._handle_cover_state_change(self._make_event("cover.a", 80.0))

        assert coord._manual_override_until["cover.a"] is not None

    def test_travel_window_extension_isolated(self) -> None:
        # A slow motor on cover.a (opening state, inside debounce) extends only
        # cover.a's window, never cover.b's stamp.
        coord = _make_coordinator(covers=["cover.a", "cover.b"])
        t_a = datetime.now(tz=UTC) - timedelta(seconds=5)
        t_b = datetime.now(tz=UTC) - timedelta(seconds=5)
        coord._last_commanded = {"cover.a": 50.0, "cover.b": 50.0}
        coord._last_command_time = {"cover.a": t_a, "cover.b": t_b}

        coord._handle_cover_state_change(
            self._make_event("cover.a", 65.0, is_closing=True)
        )

        assert coord._last_command_time["cover.a"] > t_a  # extended
        assert coord._last_command_time["cover.b"] == t_b  # untouched

    def test_recent_command_debounce_suppresses_small_delta(self) -> None:
        coord = _make_coordinator()
        coord._last_commanded = {"cover.test": 50.0}
        coord._last_command_time = {
            "cover.test": datetime.now(tz=UTC) - timedelta(seconds=5)
        }

        coord._handle_cover_state_change(self._make_event("cover.test", 54.0))

        assert coord._manual_override_until == {}
        coord.hass.async_create_task.assert_not_called()

    def test_large_delta_within_debounce_sets_override(self) -> None:
        coord = _make_coordinator()
        coord._last_commanded = {"cover.test": 80.0}
        coord._last_command_time = {
            "cover.test": datetime.now(tz=UTC) - timedelta(seconds=5)
        }

        coord._handle_cover_state_change(self._make_event("cover.test", 0.0))

        assert coord._manual_override_until["cover.test"] is not None
        assert coord._manual_position["cover.test"] == pytest.approx(0.0)
        assert coord._last_commanded["cover.test"] == pytest.approx(0.0)

    def test_is_closing_suppresses_trigger(self) -> None:
        coord = _make_coordinator()
        coord._last_commanded = {"cover.test": 50.0}
        coord._last_command_time = {
            "cover.test": datetime.now(tz=UTC) - timedelta(seconds=60)
        }

        coord._handle_cover_state_change(
            self._make_event("cover.test", 80.0, is_closing=True)
        )

        assert coord._manual_override_until == {}

    def test_delta_below_hysteresis_does_not_trigger(self) -> None:
        coord = _make_coordinator()
        coord._last_commanded = {"cover.test": 50.0}
        coord._last_command_time = {
            "cover.test": datetime.now(tz=UTC) - timedelta(seconds=60)
        }

        coord._handle_cover_state_change(self._make_event("cover.test", 51.0))

        assert coord._manual_override_until == {}

    def test_disabled_automation_skips_detection(self) -> None:
        coord = _make_coordinator()
        coord._last_commanded = {"cover.test": 50.0}
        coord._last_command_time = {
            "cover.test": datetime.now(tz=UTC) - timedelta(seconds=60)
        }
        coord._enabled = False

        coord._handle_cover_state_change(self._make_event("cover.test", 80.0))

        assert coord._manual_override_until == {}

    def test_no_last_commanded_adopts_external_move(self) -> None:
        coord = _make_coordinator()
        coord._last_commanded = {}
        coord._last_command_time = {}

        coord._handle_cover_state_change(self._make_event("cover.test", 80.0))

        assert coord._manual_override_until["cover.test"] is not None
        assert coord._manual_position["cover.test"] == pytest.approx(80.0)
        assert coord._last_commanded["cover.test"] == pytest.approx(80.0)

    def test_no_last_commanded_in_debounce_window_ignored(self) -> None:
        coord = _make_coordinator()
        coord._last_commanded = {}
        coord._last_command_time = {
            "cover.test": datetime.now(tz=UTC) - timedelta(seconds=5)
        }

        coord._handle_cover_state_change(self._make_event("cover.test", 80.0))

        assert coord._manual_override_until == {}
        assert coord._manual_position == {}

    def test_none_new_state_skips_detection(self) -> None:
        coord = _make_coordinator()
        event = MagicMock()
        event.data = {"entity_id": "cover.test", "new_state": None}

        coord._handle_cover_state_change(event)  # must not raise

        assert coord._manual_override_until == {}
