"""Tests for cover command behaviour: dict-batched command path, tilt axis
routing, per-cover manual-position restore, partial-batch failure, and the
multi-await race regression guard."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.exceptions import HomeAssistantError

from custom_components.solar_cover.const import Intent
from custom_components.solar_cover.coordinator import SolarCoverCoordinator
from custom_components.solar_cover.intent import IntentResult

_T0 = datetime(2026, 6, 8, 12, 0, 0, tzinfo=UTC)


def _make_coordinator(
    cover_type: str = "vertical",
    covers: list[str] | None = None,
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
        failed = await coord._command_covers({"cover.test": 50.0})
        assert failed == set()
        call = coord.hass.services.async_call.call_args
        assert call.args[1] == "set_cover_tilt_position"
        assert call.args[2]["tilt_position"] == 50
        assert "position" not in call.args[2]

    @pytest.mark.asyncio
    async def test_vertical_uses_position_service(self) -> None:
        coord = _make_coordinator(cover_type="vertical")
        coord.hass.services.async_call = AsyncMock()
        failed = await coord._command_covers({"cover.test": 50.0})
        assert failed == set()
        call = coord.hass.services.async_call.call_args
        assert call.args[1] == "set_cover_position"
        assert call.args[2]["position"] == 50
        assert "tilt_position" not in call.args[2]


class TestCommandBatching:
    @pytest.mark.asyncio
    async def test_identical_targets_collapse_to_one_call(self) -> None:
        coord = _make_coordinator(covers=["cover.a", "cover.b"])
        coord.hass.services.async_call = AsyncMock()
        await coord._command_covers({"cover.a": 40.0, "cover.b": 40.0})
        assert coord.hass.services.async_call.await_count == 1
        entities = coord.hass.services.async_call.call_args.args[2][ATTR_ENTITY_ID]
        assert set(entities) == {"cover.a", "cover.b"}

    @pytest.mark.asyncio
    async def test_divergent_targets_one_call_each(self) -> None:
        coord = _make_coordinator(covers=["cover.a", "cover.b"])
        coord.hass.services.async_call = AsyncMock()
        await coord._command_covers({"cover.a": 40.0, "cover.b": 70.0})
        assert coord.hass.services.async_call.await_count == 2

    @pytest.mark.asyncio
    async def test_empty_targets_is_noop(self) -> None:
        coord = _make_coordinator(covers=[])
        coord.hass.services.async_call = AsyncMock()
        failed = await coord._command_covers({})
        assert failed == set()
        assert coord.hass.services.async_call.await_count == 0

    @pytest.mark.asyncio
    async def test_commits_all_entities_up_front(self) -> None:
        coord = _make_coordinator(covers=["cover.a", "cover.b"])
        coord.hass.services.async_call = AsyncMock()
        await coord._command_covers({"cover.a": 40.0, "cover.b": 70.0})
        assert coord._last_commanded == {"cover.a": 40.0, "cover.b": 70.0}
        assert set(coord._last_command_time) == {"cover.a", "cover.b"}


class TestPartialBatchFailure:
    @pytest.mark.asyncio
    async def test_only_failed_group_reverts(self) -> None:
        # cover.a group succeeds, cover.b group fails: only cover.b reverts.
        coord = _make_coordinator(covers=["cover.a", "cover.b"])
        coord._last_commanded = {"cover.a": 10.0, "cover.b": 10.0}

        async def fake_call(
            domain: str, service: str, data: dict, blocking: bool
        ) -> None:
            if "cover.b" in data[ATTR_ENTITY_ID]:
                raise HomeAssistantError("cover.b offline")

        coord.hass.services.async_call = AsyncMock(side_effect=fake_call)

        failed = await coord._command_covers({"cover.a": 40.0, "cover.b": 70.0})

        assert failed == {"cover.b"}
        assert coord._last_commanded["cover.a"] == 40.0  # committed
        assert coord._last_commanded["cover.b"] == 10.0  # reverted
        assert "cover.b" not in coord._last_command_time  # stamp cleared


class TestMultiAwaitRace:
    @pytest.mark.asyncio
    async def test_late_manual_move_survives_second_group_send(self) -> None:
        # Two covers command to different targets in one cycle. While the first
        # group's service call is awaited, a genuine manual countermand of the
        # second cover arrives. Because _command_covers commits every entity's
        # _last_commanded up front (before the first await), the second group's
        # send does NOT re-commit and silently overwrite the armed override.
        coord = _make_coordinator(covers=["cover.a", "cover.b"])
        coord._last_commanded = {"cover.a": 50.0, "cover.b": 50.0}

        def _event(entity_id: str, position: float) -> MagicMock:
            state = MagicMock()
            state.state = "open"
            state.attributes = {"current_position": position}
            event = MagicMock()
            event.data = {"entity_id": entity_id, "new_state": state}
            return event

        async def fake_call(
            domain: str, service: str, data: dict, blocking: bool
        ) -> None:
            if "cover.a" in data[ATTR_ENTITY_ID]:
                # Manual countermand of cover.b lands during cover.a's await.
                coord._handle_cover_state_change(_event("cover.b", 5.0))

        coord.hass.services.async_call = AsyncMock(side_effect=fake_call)

        await coord._command_covers({"cover.a": 80.0, "cover.b": 90.0})

        # The racing manual move is honoured and not clobbered by group 2.
        assert coord._manual_override_until["cover.b"] is not None
        assert coord._manual_position["cover.b"] == pytest.approx(5.0)
        assert coord._last_commanded["cover.b"] == pytest.approx(5.0)


class TestManualPositionRestore:
    """Bug B, now per cover -- weather retraction mid-override must not erase the
    manual position; the hold resumes when weather clears."""

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

        coord._last_commanded = {"cover.test": 70.0}
        coord._manual_position = {"cover.test": 70.0}
        coord._manual_override_until = {"cover.test": _T0 + timedelta(hours=2)}

        results = [
            IntentResult(Intent.INACTIVE_WEATHER, None, "weather", []),
            IntentResult(Intent.SHADING, None, "shading", []),
        ]
        with (
            patch(
                "custom_components.solar_cover.coordinator.evaluate_intent",
                side_effect=results,
            ),
            patch("custom_components.solar_cover.coordinator.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = _T0

            # Wind picks up -> safety retract to the rest position (0), hold kept.
            await coord._async_update_data()
            assert coord.hass.services.async_call.await_count == 1
            assert coord.hass.services.async_call.call_args.args[2]["position"] == 0
            assert coord._last_commanded["cover.test"] == 0.0
            assert "cover.test" in coord._manual_override_until  # hold survives

            # Wind drops -> the 70% manual position is restored.
            await coord._async_update_data()
            assert coord.hass.services.async_call.await_count == 2
            assert coord.hass.services.async_call.call_args.args[2]["position"] == 70
            assert coord._last_commanded["cover.test"] == 70.0

    @pytest.mark.asyncio
    async def test_steady_override_does_not_recommand(self) -> None:
        coord = _make_coordinator()
        self._wire_solar(coord)
        coord.hass.states.get = MagicMock(return_value=None)
        coord.hass.services.async_call = AsyncMock()

        coord._last_commanded = {"cover.test": 70.0}
        coord._manual_position = {"cover.test": 70.0}
        coord._manual_override_until = {"cover.test": _T0 + timedelta(hours=2)}

        with (
            patch(
                "custom_components.solar_cover.coordinator.evaluate_intent",
                return_value=IntentResult(Intent.SHADING, None, "shading", []),
            ),
            patch("custom_components.solar_cover.coordinator.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = _T0
            await coord._async_update_data()
            assert coord.hass.services.async_call.await_count == 0

    @pytest.mark.asyncio
    async def test_per_cover_independence(self) -> None:
        # cover.a is held; cover.b keeps tracking the automatic SHADING target
        # in the same refresh cycle.
        coord = _make_coordinator(covers=["cover.a", "cover.b"])
        self._wire_solar(coord)
        coord.hass.states.get = MagicMock(return_value=None)
        coord.hass.services.async_call = AsyncMock()

        coord._last_commanded = {"cover.a": 0.0, "cover.b": 0.0}
        coord._manual_position = {"cover.a": 70.0}
        coord._manual_override_until = {"cover.a": _T0 + timedelta(hours=2)}

        with (
            patch(
                "custom_components.solar_cover.coordinator.evaluate_intent",
                return_value=IntentResult(Intent.SHADING, 50.0, "shading", []),
            ),
            patch("custom_components.solar_cover.coordinator.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = _T0
            await coord._async_update_data()

        # cover.a restored to its manual 70; cover.b driven to the auto 50.
        assert coord._last_commanded["cover.a"] == 70.0
        assert coord._last_commanded["cover.b"] == 50.0


class TestCommandFailureHandling:
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

            await coord._async_update_data()
            assert coord.hass.services.async_call.await_count == 1
            assert coord._last_commanded.get("cover.test") is None

            await coord._async_update_data()
            assert coord.hass.services.async_call.await_count == 2
            assert coord._last_commanded.get("cover.test") is None

            coord.hass.services.async_call.side_effect = None
            await coord._async_update_data()
            assert coord.hass.services.async_call.await_count == 3
            assert coord._last_commanded["cover.test"] == 50.0

    @pytest.mark.asyncio
    async def test_failed_command_clears_debounce_stamp(self) -> None:
        coord = _make_coordinator()
        coord.hass.services.async_call = AsyncMock(
            side_effect=HomeAssistantError("offline")
        )
        failed = await coord._command_covers({"cover.test": 50.0})
        assert failed == {"cover.test"}
        assert "cover.test" not in coord._last_command_time

    @pytest.mark.asyncio
    async def test_successful_command_stamps_debounce(self) -> None:
        coord = _make_coordinator()
        coord.hass.services.async_call = AsyncMock()
        failed = await coord._command_covers({"cover.test": 50.0})
        assert failed == set()
        assert "cover.test" in coord._last_command_time

    @pytest.mark.asyncio
    async def test_override_restore_works_below_horizon(self) -> None:
        coord = _make_coordinator()
        coord._solar.sun_position = MagicMock(return_value=(180.0, -8.0))
        coord._solar.hourly_curve = MagicMock(return_value=[])
        coord._solar.fov_window = MagicMock(return_value=(None, None))
        coord.hass.states.get = MagicMock(return_value=None)
        coord.hass.services.async_call = AsyncMock()

        coord._last_commanded = {"cover.test": 0.0}
        coord._manual_position = {"cover.test": 70.0}
        coord._manual_override_until = {"cover.test": _T0 + timedelta(hours=2)}

        with (
            patch(
                "custom_components.solar_cover.coordinator.evaluate_intent",
                return_value=IntentResult(Intent.SHADING, None, "shading", []),
            ),
            patch("custom_components.solar_cover.coordinator.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = _T0
            await coord._async_update_data()
            assert coord.hass.services.async_call.await_count == 1
            assert coord.hass.services.async_call.call_args.args[2]["position"] == 70
            assert coord._last_commanded["cover.test"] == 70.0


class TestExternalMoveTiltAxis:
    @staticmethod
    def _event(entity_id: str, attrs: dict[str, Any]) -> MagicMock:
        state = MagicMock()
        state.state = "open"
        state.attributes = attrs
        event = MagicMock()
        event.data = {"entity_id": entity_id, "new_state": state}
        return event

    def test_tilt_external_move_sets_override(self) -> None:
        coord = _make_coordinator(cover_type="tilt")
        coord._last_commanded = {"cover.test": 70.0}
        coord._handle_cover_state_change(
            self._event("cover.test", {"current_tilt_position": 30})
        )
        assert coord._manual_override_until["cover.test"] is not None
        assert coord._manual_position["cover.test"] == 30.0
        assert coord._last_commanded["cover.test"] == 30.0

    def test_tilt_zone_ignores_missing_tilt_position(self) -> None:
        coord = _make_coordinator(cover_type="tilt")
        coord._last_commanded = {"cover.test": 70.0}
        coord._handle_cover_state_change(
            self._event("cover.test", {"current_position": 30})
        )
        assert coord._manual_override_until == {}
        assert coord._manual_position == {}
