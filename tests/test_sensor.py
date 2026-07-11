"""Tests for the Solar Cover diagnostic sensor platform (zone + per-cover)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solar_cover.const import DOMAIN, ENTRY_TYPE_ZONE, Intent
from custom_components.solar_cover.coordinator import CoordinatorData, CoverSnapshot
from custom_components.solar_cover.sensor import (
    PER_COVER_SENSOR_DESCRIPTIONS,
    SENSOR_DESCRIPTIONS,
    SolarCoverCoverSensorEntity,
    SolarCoverSensorDescription,
    async_setup_entry,
)


def _make_snapshot(
    commanded_position: float = 65.0,
    manual_override_until: str | None = None,
    intent: Intent = Intent.SHADING,
) -> CoverSnapshot:
    return CoverSnapshot(
        commanded_position=commanded_position,
        manual_override_until=manual_override_until,
        intent=intent,
    )


def _make_coordinator_data(
    intent: Intent = Intent.SHADING,
    computed_position: float | None = 65.0,
    sun_azimuth: float = 195.3,
    sun_elevation: float = 42.7,
    gamma: float = 15.5,
    fov_entry: str | None = "2026-05-28T08:30:00+00:00",
    fov_exit: str | None = "2026-05-28T17:45:00+00:00",
    reason: str = "Shading: sun 42.7 elevation, 15.5 off-axis, target 65%",
    reason_detail: list[dict[str, object]] | None = None,
    stability_pending_until: str | None = None,
    pending_intent: str | None = None,
    position_curve: list[dict[str, object]] | None = None,
    covers: dict[str, CoverSnapshot] | None = None,
) -> CoordinatorData:
    return CoordinatorData(
        intent=intent,
        computed_position=computed_position,
        sun_azimuth=sun_azimuth,
        sun_elevation=sun_elevation,
        gamma=gamma,
        position_curve=position_curve if position_curve is not None else [],
        fov_entry=fov_entry,
        fov_exit=fov_exit,
        reason=reason,
        reason_detail=reason_detail if reason_detail is not None else [],
        stability_pending_until=stability_pending_until,
        pending_intent=pending_intent,
        covers=covers if covers is not None else {"cover.test": _make_snapshot()},
    )


class TestSensorDescriptions:
    def test_zone_keys_present(self) -> None:
        keys = {d.key for d in SENSOR_DESCRIPTIONS}
        assert keys == {
            "intent",
            "reason",
            "sun_elevation",
            "sun_azimuth",
            "surface_azimuth",
            "computed_position",
            "fov_entry",
            "fov_exit",
            "stability_pending_until",
        }

    def test_per_cover_keys_present(self) -> None:
        keys = {d.key for d in PER_COVER_SENSOR_DESCRIPTIONS}
        assert keys == {"commanded_position", "manual_override_until", "intent"}

    def test_intent_and_reason_are_primary_entities(self) -> None:
        for key in ("intent", "reason"):
            desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == key)
            assert desc.entity_category is None

    def test_remaining_zone_descriptions_are_diagnostic(self) -> None:
        for desc in SENSOR_DESCRIPTIONS:
            if desc.key in ("intent", "reason"):
                continue
            assert desc.entity_category == EntityCategory.DIAGNOSTIC

    def test_zone_measurement_sensors_have_state_class(self) -> None:
        measurement_keys = {
            "sun_elevation",
            "sun_azimuth",
            "surface_azimuth",
            "computed_position",
        }
        for desc in SENSOR_DESCRIPTIONS:
            if desc.key in measurement_keys:
                assert desc.state_class == SensorStateClass.MEASUREMENT

    def test_timestamp_sensors_have_correct_device_class(self) -> None:
        for desc in SENSOR_DESCRIPTIONS:
            if desc.key in ("fov_entry", "fov_exit"):
                assert desc.device_class == SensorDeviceClass.TIMESTAMP


class TestZoneSensorValueFunctions:
    def _get(self, key: str) -> SolarCoverSensorDescription:
        return next(d for d in SENSOR_DESCRIPTIONS if d.key == key)

    def test_intent_value_fn_returns_string(self) -> None:
        data = _make_coordinator_data(intent=Intent.INACTIVE_SUN_LOW)
        assert self._get("intent").value_fn(data) == "inactive_sun_low"

    def test_sun_elevation_rounds(self) -> None:
        data = _make_coordinator_data(sun_elevation=42.78)
        assert self._get("sun_elevation").value_fn(data) == 42.8

    def test_computed_position_none_stays_none(self) -> None:
        data = _make_coordinator_data(computed_position=None)
        assert self._get("computed_position").value_fn(data) is None

    def test_intent_exposes_position_curve_attr(self) -> None:
        curve = [{"time": "2026-05-28T08:00:00+00:00", "position": 50}]
        data = _make_coordinator_data(position_curve=curve)
        assert self._get("intent").attr_fn(data) == {"position_curve": curve}


class TestPerCoverValueFunctions:
    def _get(self, key: str):  # noqa: ANN202
        return next(d for d in PER_COVER_SENSOR_DESCRIPTIONS if d.key == key)

    def test_commanded_position_rounds(self) -> None:
        snap = _make_snapshot(commanded_position=42.345)
        assert self._get("commanded_position").value_fn(snap) == 42.3

    def test_intent_value_fn(self) -> None:
        snap = _make_snapshot(intent=Intent.MANUAL_OVERRIDE)
        assert self._get("intent").value_fn(snap) == "manual_override"

    def test_manual_override_until_returns_datetime(self) -> None:
        snap = _make_snapshot(manual_override_until="2026-05-28T14:00:00+00:00")
        result = self._get("manual_override_until").value_fn(snap)
        assert isinstance(result, datetime)

    def test_manual_override_until_none(self) -> None:
        snap = _make_snapshot(manual_override_until=None)
        assert self._get("manual_override_until").value_fn(snap) is None


class TestPerCoverEntity:
    def _entity(self, key: str) -> SolarCoverCoverSensorEntity:
        desc = next(d for d in PER_COVER_SENSOR_DESCRIPTIONS if d.key == key)
        coordinator = MagicMock()
        coordinator.data = _make_coordinator_data(
            covers={"cover.living_a": _make_snapshot(commanded_position=30.0)}
        )
        entry = MagicMock(spec=MockConfigEntry)
        entry.entry_id = "test_entry_id"
        entry.title = "Living Room South"
        with patch(
            "custom_components.solar_cover.sensor.CoordinatorEntity.__init__",
            return_value=None,
        ):
            entity = SolarCoverCoverSensorEntity(
                coordinator, entry, desc, "cover.living_a"
            )
            entity.coordinator = coordinator
        return entity

    def test_unique_id_scheme(self) -> None:
        entity = self._entity("commanded_position")
        assert (
            entity._attr_unique_id == "test_entry_id_cover_living_a_commanded_position"
        )

    def test_native_value_reads_snapshot(self) -> None:
        entity = self._entity("commanded_position")
        assert entity.native_value == 30.0

    def test_device_info_nested_via_zone(self) -> None:
        entity = self._entity("intent")
        info = entity._attr_device_info
        assert (DOMAIN, "test_entry_id_cover_living_a") in info["identifiers"]
        assert info["via_device"] == (DOMAIN, "test_entry_id")

    def test_native_value_none_when_cover_absent(self) -> None:
        entity = self._entity("intent")
        entity.coordinator.data = _make_coordinator_data(covers={})
        assert entity.native_value is None


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: None) -> None:  # noqa: PT004
    """Activate the custom component loader for every test in this module."""


async def test_platform_creates_zone_and_per_cover_entities(
    hass: HomeAssistant,
) -> None:
    integration_entry = MockConfigEntry(
        domain=DOMAIN, data={"entry_type": "integration"}, title="Solar Cover"
    )
    integration_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(integration_entry.entry_id)
    await hass.async_block_till_done()

    fake_coordinator = MagicMock()
    fake_coordinator.data = _make_coordinator_data()
    fake_coordinator.async_add_listener = MagicMock(return_value=lambda: None)
    fake_coordinator.cover_entities = ["cover.a", "cover.b"]

    zone_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "entry_type": ENTRY_TYPE_ZONE,
            "name": "Test Zone",
            "azimuth": 180,
            "fov_left": 90,
            "fov_right": 90,
            "elevation_threshold": 27.0,
            "cover_type": "vertical",
            "cover_entities": ["cover.a", "cover.b"],
        },
        title="Test Zone",
        entry_id="test_zone_entry",
    )
    zone_entry.add_to_hass(hass)
    zone_entry.runtime_data = fake_coordinator

    with patch(
        "custom_components.solar_cover.sensor.CoordinatorEntity.__init_subclass__",
    ):
        added: list[object] = []

        def _add(entities: list[object], **_: object) -> None:
            added.extend(entities)

        await async_setup_entry(hass, zone_entry, _add)

    # 9 zone sensors + 3 per-cover sensors x 2 covers = 15.
    assert len(added) == len(SENSOR_DESCRIPTIONS) + 2 * len(
        PER_COVER_SENSOR_DESCRIPTIONS
    )
