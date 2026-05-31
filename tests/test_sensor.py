"""Tests for the Solar Cover diagnostic sensor platform."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solar_cover.const import DOMAIN, ENTRY_TYPE_ZONE, Intent
from custom_components.solar_cover.coordinator import CoordinatorData
from custom_components.solar_cover.sensor import (
    SENSOR_DESCRIPTIONS,
    SolarCoverSensorDescription,
    SolarCoverSensorEntity,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_coordinator_data(
    intent: Intent = Intent.SHADING,
    computed_position: float | None = 65.0,
    commanded_position: float = 65.0,
    sun_azimuth: float = 195.3,
    sun_elevation: float = 42.7,
    gamma: float = 15.5,
    fov_entry: str | None = "2026-05-28T08:30:00+00:00",
    fov_exit: str | None = "2026-05-28T17:45:00+00:00",
    reason: str = "Shading: sun 42.7° elevation, 15.5° off-axis, target 65%",
    reason_detail: list[dict[str, object]] | None = None,
    stability_pending_until: str | None = None,
    pending_intent: str | None = None,
    manual_override_until: str | None = None,
) -> CoordinatorData:
    return CoordinatorData(
        intent=intent,
        computed_position=computed_position,
        commanded_position=commanded_position,
        sun_azimuth=sun_azimuth,
        sun_elevation=sun_elevation,
        gamma=gamma,
        position_curve=[],
        fov_entry=fov_entry,
        fov_exit=fov_exit,
        reason=reason,
        reason_detail=reason_detail if reason_detail is not None else [],
        stability_pending_until=stability_pending_until,
        pending_intent=pending_intent,
        manual_override_until=manual_override_until,
    )


def _make_sensor_entity(
    description: SolarCoverSensorDescription,
    data: CoordinatorData | None = None,
) -> SolarCoverSensorEntity:
    """Build a SolarCoverSensorEntity with a mocked coordinator and entry."""
    coordinator = MagicMock()
    coordinator.data = data or _make_coordinator_data()

    entry = MagicMock(spec=MockConfigEntry)
    entry.entry_id = "test_entry_id"
    entry.title = "Living Room South"

    with patch(
        "custom_components.solar_cover.sensor.CoordinatorEntity.__init__",
        return_value=None,
    ):
        entity = SolarCoverSensorEntity(coordinator, entry, description)
        entity.coordinator = coordinator

    return entity


# ---------------------------------------------------------------------------
# Descriptor-level unit tests (no HA fixture needed)
# ---------------------------------------------------------------------------


class TestSensorDescriptions:
    def test_all_expected_keys_present(self) -> None:
        keys = {d.key for d in SENSOR_DESCRIPTIONS}
        expected = {
            "intent",
            "sun_elevation",
            "sun_azimuth",
            "surface_azimuth",
            "computed_position",
            "fov_entry",
            "fov_exit",
            "stability_pending_until",
            "manual_override_until",
        }
        assert keys == expected

    def test_all_descriptions_are_diagnostic(self) -> None:
        for desc in SENSOR_DESCRIPTIONS:
            assert desc.entity_category == EntityCategory.DIAGNOSTIC, (
                f"{desc.key} should be DIAGNOSTIC"
            )

    def test_measurement_sensors_have_state_class(self) -> None:
        measurement_keys = {
            "sun_elevation",
            "sun_azimuth",
            "surface_azimuth",
            "computed_position",
        }
        for desc in SENSOR_DESCRIPTIONS:
            if desc.key in measurement_keys:
                assert desc.state_class == SensorStateClass.MEASUREMENT, (
                    f"{desc.key} should be MEASUREMENT"
                )

    def test_timestamp_sensors_have_correct_device_class(self) -> None:
        timestamp_keys = {"fov_entry", "fov_exit"}
        for desc in SENSOR_DESCRIPTIONS:
            if desc.key in timestamp_keys:
                assert desc.device_class == SensorDeviceClass.TIMESTAMP, (
                    f"{desc.key} should have TIMESTAMP device class"
                )


# ---------------------------------------------------------------------------
# value_fn tests
# ---------------------------------------------------------------------------


class TestSensorValueFunctions:
    def _get_desc(self, key: str) -> SolarCoverSensorDescription:
        return next(d for d in SENSOR_DESCRIPTIONS if d.key == key)

    def test_intent_value_fn_returns_string(self) -> None:
        data = _make_coordinator_data(intent=Intent.INACTIVE_SUN_LOW)
        result = self._get_desc("intent").value_fn(data)
        assert result == "inactive_sun_low"
        assert isinstance(result, str)

    def test_sun_elevation_rounds_to_one_decimal(self) -> None:
        data = _make_coordinator_data(sun_elevation=42.78)
        result = self._get_desc("sun_elevation").value_fn(data)
        assert result == 42.8

    def test_sun_azimuth_rounds_to_one_decimal(self) -> None:
        data = _make_coordinator_data(sun_azimuth=195.345)
        result = self._get_desc("sun_azimuth").value_fn(data)
        assert result == 195.3

    def test_surface_azimuth_rounds_to_one_decimal(self) -> None:
        data = _make_coordinator_data(gamma=15.55)
        result = self._get_desc("surface_azimuth").value_fn(data)
        assert result == 15.6

    def test_computed_position_rounds_to_one_decimal(self) -> None:
        data = _make_coordinator_data(computed_position=73.456)
        result = self._get_desc("computed_position").value_fn(data)
        assert result == 73.5

    def test_computed_position_falls_back_to_commanded_when_inactive(self) -> None:
        # When the geometry didn't run (inactive intent), the sensor falls back to
        # the commanded position so it never goes unavailable.
        data = _make_coordinator_data(computed_position=None, commanded_position=0.0)
        result = self._get_desc("computed_position").value_fn(data)
        assert result == 0.0

    def test_fov_entry_returns_datetime_object(self) -> None:
        data = _make_coordinator_data(fov_entry="2026-05-28T08:30:00+00:00")
        result = self._get_desc("fov_entry").value_fn(data)
        assert isinstance(result, datetime)
        assert result.tzinfo is not None

    def test_fov_exit_returns_none_when_none(self) -> None:
        data = _make_coordinator_data(fov_exit=None)
        result = self._get_desc("fov_exit").value_fn(data)
        assert result is None

    def test_fov_entry_returns_none_when_none(self) -> None:
        data = _make_coordinator_data(fov_entry=None)
        result = self._get_desc("fov_entry").value_fn(data)
        assert result is None

    def test_stability_pending_until_returns_datetime_when_set(self) -> None:
        data = _make_coordinator_data(
            stability_pending_until="2026-05-28T12:05:00+00:00"
        )
        result = self._get_desc("stability_pending_until").value_fn(data)
        assert isinstance(result, datetime)
        assert result.tzinfo is not None

    def test_stability_pending_until_returns_none_when_unset(self) -> None:
        data = _make_coordinator_data(stability_pending_until=None)
        result = self._get_desc("stability_pending_until").value_fn(data)
        assert result is None

    def test_stability_pending_until_exposes_pending_intent_attr(self) -> None:
        data = _make_coordinator_data(pending_intent="inactive_overcast")
        attrs = self._get_desc("stability_pending_until").attr_fn(data)
        assert attrs == {"pending_intent": "inactive_overcast"}

    def test_manual_override_until_returns_datetime_when_set(self) -> None:
        data = _make_coordinator_data(manual_override_until="2026-05-28T14:00:00+00:00")
        result = self._get_desc("manual_override_until").value_fn(data)
        assert isinstance(result, datetime)
        assert result.tzinfo is not None

    def test_manual_override_until_returns_none_when_unset(self) -> None:
        data = _make_coordinator_data(manual_override_until=None)
        result = self._get_desc("manual_override_until").value_fn(data)
        assert result is None


# ---------------------------------------------------------------------------
# Entity-level tests
# ---------------------------------------------------------------------------


class TestSolarCoverSensorEntity:
    def _get_desc(self, key: str) -> SolarCoverSensorDescription:
        return next(d for d in SENSOR_DESCRIPTIONS if d.key == key)

    def test_unique_id_is_entry_id_plus_key(self) -> None:
        desc = self._get_desc("intent")
        entity = _make_sensor_entity(desc)
        assert entity._attr_unique_id == "test_entry_id_intent"

    def test_native_value_delegates_to_value_fn(self) -> None:
        data = _make_coordinator_data(intent=Intent.SHADING)
        desc = self._get_desc("intent")
        entity = _make_sensor_entity(desc, data)
        assert entity.native_value == "shading"

    def test_native_value_sun_elevation(self) -> None:
        data = _make_coordinator_data(sun_elevation=30.0)
        desc = self._get_desc("sun_elevation")
        entity = _make_sensor_entity(desc, data)
        assert entity.native_value == 30.0

    def test_all_intent_values_are_valid_strings(self) -> None:
        desc = self._get_desc("intent")
        for intent in Intent:
            data = _make_coordinator_data(intent=intent)
            entity = _make_sensor_entity(desc, data)
            assert isinstance(entity.native_value, str)
            assert entity.native_value == intent.value

    def test_has_entity_name_is_true(self) -> None:
        desc = self._get_desc("sun_azimuth")
        entity = _make_sensor_entity(desc)
        assert entity._attr_has_entity_name is True

    def test_device_info_uses_entry_id_as_identifier(self) -> None:
        desc = self._get_desc("sun_elevation")
        entity = _make_sensor_entity(desc)
        assert (DOMAIN, "test_entry_id") in entity._attr_device_info["identifiers"]


# ---------------------------------------------------------------------------
# Platform setup integration test (requires HA fixture)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: None) -> None:  # noqa: PT004
    """Activate the custom component loader for every test in this module."""


async def test_sensor_platform_creates_all_entities(hass: HomeAssistant) -> None:
    """All 7 sensor descriptions should produce entities when the platform loads."""
    integration_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": "integration"},
        title="Solar Cover",
    )
    integration_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(integration_entry.entry_id)
    await hass.async_block_till_done()

    # Build a fake coordinator
    fake_coordinator = MagicMock()
    fake_coordinator.data = _make_coordinator_data()
    fake_coordinator.async_add_listener = MagicMock(return_value=lambda: None)

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
            "cover_entities": [],
            "window_height": 2.5,
            "glare_depth": 1.0,
        },
        title="Test Zone",
        entry_id="test_zone_entry",
    )
    zone_entry.add_to_hass(hass)

    hass.data.setdefault(DOMAIN, {"coordinators": {}})
    hass.data[DOMAIN]["coordinators"]["test_zone_entry"] = fake_coordinator

    with patch(
        "custom_components.solar_cover.sensor.CoordinatorEntity.__init_subclass__",
    ):
        from custom_components.solar_cover import sensor as sensor_module

        added: list[SolarCoverSensorEntity] = []

        def _add(entities: list[SolarCoverSensorEntity], **_: object) -> None:
            added.extend(entities)

        await sensor_module.async_setup_entry(hass, zone_entry, _add)

    assert len(added) == len(SENSOR_DESCRIPTIONS)
    keys = {e.entity_description.key for e in added}
    assert keys == {d.key for d in SENSOR_DESCRIPTIONS}
