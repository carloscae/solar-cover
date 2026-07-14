"""Diagnostic sensor entities for Solar Cover zones (zone + per-cover)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import DEGREE, PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import (
    CoordinatorData,
    CoverSnapshot,
    SolarCoverConfigEntry,
    SolarCoverCoordinator,
    cover_label,
    cover_slug,
    zone_device_info,
)

# Read-only diagnostic sensors backed by the coordinator; no device I/O.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class SolarCoverSensorDescription(SensorEntityDescription):
    """Zone sensor description with value/attribute extractors over CoordinatorData."""

    value_fn: Callable[[CoordinatorData], Any]
    attr_fn: Callable[[CoordinatorData], dict[str, Any]] | None = None


@dataclass(frozen=True, kw_only=True)
class SolarCoverCoverSensorDescription(SensorEntityDescription):
    """Per-cover sensor description with a value extractor over a CoverSnapshot."""

    value_fn: Callable[[CoverSnapshot], Any]


SENSOR_DESCRIPTIONS: tuple[SolarCoverSensorDescription, ...] = (
    SolarCoverSensorDescription(
        key="intent",
        translation_key="intent",
        icon="mdi:sun-compass",
        value_fn=lambda d: d.intent.value,
        attr_fn=lambda d: {"position_curve": d.position_curve},
    ),
    SolarCoverSensorDescription(
        key="reason",
        translation_key="reason",
        icon="mdi:text",
        value_fn=lambda d: d.reason,
        attr_fn=lambda d: {"reason_detail": d.reason_detail},
    ),
    SolarCoverSensorDescription(
        key="sun_elevation",
        translation_key="sun_elevation",
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:angle-acute",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: round(d.sun_elevation, 1),
    ),
    SolarCoverSensorDescription(
        key="sun_azimuth",
        translation_key="sun_azimuth",
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:compass",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: round(d.sun_azimuth, 1),
    ),
    SolarCoverSensorDescription(
        key="surface_azimuth",
        translation_key="surface_azimuth",
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:angle-right",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: round(d.gamma, 1),
    ),
    SolarCoverSensorDescription(
        key="computed_position",
        translation_key="computed_position",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:percent",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (
            round(d.computed_position, 1) if d.computed_position is not None else None
        ),
    ),
    SolarCoverSensorDescription(
        key="fov_entry",
        translation_key="fov_entry",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: datetime.fromisoformat(d.fov_entry) if d.fov_entry else None,
    ),
    SolarCoverSensorDescription(
        key="fov_exit",
        translation_key="fov_exit",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: datetime.fromisoformat(d.fov_exit) if d.fov_exit else None,
    ),
    SolarCoverSensorDescription(
        key="stability_pending_until",
        translation_key="stability_pending_until",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:timer-sand",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (
            datetime.fromisoformat(d.stability_pending_until)
            if d.stability_pending_until
            else None
        ),
        attr_fn=lambda d: {"pending_intent": d.pending_intent},
    ),
)


PER_COVER_SENSOR_DESCRIPTIONS: tuple[SolarCoverCoverSensorDescription, ...] = (
    SolarCoverCoverSensorDescription(
        key="commanded_position",
        translation_key="commanded_position",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:percent",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: round(s.commanded_position, 1),
    ),
    SolarCoverCoverSensorDescription(
        key="intent",
        translation_key="cover_intent",
        icon="mdi:sun-compass",
        value_fn=lambda s: s.intent.value,
    ),
    SolarCoverCoverSensorDescription(
        key="manual_override_until",
        translation_key="manual_override_until",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:timer-lock",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: (
            datetime.fromisoformat(s.manual_override_until)
            if s.manual_override_until
            else None
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SolarCoverConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up zone and per-cover diagnostic sensor entities from a config entry."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        SolarCoverSensorEntity(coordinator, entry, description)
        for description in SENSOR_DESCRIPTIONS
    ]
    for entity_id in coordinator.cover_entities:
        for description in PER_COVER_SENSOR_DESCRIPTIONS:
            entities.append(
                SolarCoverCoverSensorEntity(coordinator, entry, description, entity_id)
            )
    async_add_entities(entities)


class SolarCoverSensorEntity(CoordinatorEntity[SolarCoverCoordinator], SensorEntity):
    """A single zone-level diagnostic sensor for a Solar Cover zone."""

    entity_description: SolarCoverSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SolarCoverCoordinator,
        entry: ConfigEntry,
        description: SolarCoverSensorDescription,
    ) -> None:
        """Initialise with coordinator, config entry, and sensor description."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = zone_device_info(entry)

    @property
    def native_value(self) -> Any:
        """Return the current sensor value derived from coordinator data."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes for sensors that define an attr_fn."""
        if self.coordinator.data is None or self.entity_description.attr_fn is None:
            return None
        return self.entity_description.attr_fn(self.coordinator.data)


class SolarCoverCoverSensorEntity(
    CoordinatorEntity[SolarCoverCoordinator], SensorEntity
):
    """A single per-cover diagnostic sensor, living on the shared zone device."""

    entity_description: SolarCoverCoverSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SolarCoverCoordinator,
        entry: ConfigEntry,
        description: SolarCoverCoverSensorDescription,
        entity_id: str,
    ) -> None:
        """Initialise with coordinator, config entry, description, and cover entity_id.

        The entity_id is the physical cover this sensor reports on.
        """
        super().__init__(coordinator)
        self.entity_description = description
        self._entity_id = entity_id
        slug = cover_slug(entity_id)
        self._attr_unique_id = f"{entry.entry_id}_{slug}_{description.key}"
        self._attr_device_info = zone_device_info(entry)
        self._attr_translation_placeholders = {"cover": cover_label(entity_id)}

    @property
    def native_value(self) -> Any:
        """Return the current value derived from this cover's snapshot."""
        data = self.coordinator.data
        if data is None:
            return None
        snapshot = data.covers.get(self._entity_id)
        if snapshot is None:
            return None
        return self.entity_description.value_fn(snapshot)
