"""Solar Cover entity -- reads coordinator state, exposes observability attributes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_OVERRIDE_DURATION,
    CONF_OVERRIDE_DURATION_OVERRIDE,
    DEFAULT_OVERRIDE_DURATION,
    DOMAIN,
)
from .coordinator import SolarCoverCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Solar Cover entities from a config entry."""
    coordinator: SolarCoverCoordinator = hass.data[DOMAIN]["coordinators"][
        entry.entry_id
    ]
    integration_data: dict[str, Any] = hass.data[DOMAIN].get("integration", {})
    async_add_entities([SolarCoverEntity(coordinator, entry, integration_data)])


class SolarCoverEntity(CoordinatorEntity[SolarCoverCoordinator], CoverEntity):
    """Represents a Solar Cover zone -- commands all physical covers in the zone."""

    _attr_has_entity_name = True
    _attr_supported_features = CoverEntityFeature.SET_POSITION

    def __init__(
        self,
        coordinator: SolarCoverCoordinator,
        entry: ConfigEntry,
        integration_data: dict[str, Any],
    ) -> None:
        """Initialise with coordinator, config entry and integration-level data."""
        super().__init__(coordinator)
        self._entry = entry
        self._integration_data = integration_data
        self._attr_unique_id = entry.entry_id
        self._attr_device_class = CoverDeviceClass.BLIND
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Solar Cover",
        )

    @property
    def is_closed(self) -> bool | None:
        """Return True when commanded position is 0 (fully closed)."""
        if self.coordinator.data is None:
            return None
        pos = self.coordinator.data.commanded_position
        return pos is not None and pos == 0

    @property
    def current_cover_position(self) -> int | None:
        """Return the current commanded cover position (0-100)."""
        if self.coordinator.data is None:
            return None
        pos = self.coordinator.data.commanded_position
        return round(pos) if pos is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return observability attributes required by the spec."""
        data = self.coordinator.data
        if data is None:
            return {}
        return {
            "intent": str(data.intent),
            "sun_azimuth": round(data.sun_azimuth, 1),
            "sun_elevation": round(data.sun_elevation, 1),
            "surface_azimuth": round(data.gamma, 1),
            "computed_position": (
                round(data.computed_position)
                if data.computed_position is not None
                else None
            ),
            "commanded_position": (
                round(data.commanded_position)
                if data.commanded_position is not None
                else None
            ),
            "fov_entry": data.fov_entry,
            "fov_exit": data.fov_exit,
            "position_curve": data.position_curve,
        }

    @property
    def _override_duration(self) -> int:
        """Return the override duration in minutes from config."""
        return int(
            self._entry.data.get(
                CONF_OVERRIDE_DURATION_OVERRIDE,
                self._integration_data.get(
                    CONF_OVERRIDE_DURATION, DEFAULT_OVERRIDE_DURATION
                ),
            )
        )

    async def _apply_manual(self, position: float) -> None:
        """Command the covers to a position under a manual override."""
        until = datetime.now(tz=UTC) + timedelta(minutes=self._override_duration)
        await self.coordinator.async_apply_manual_position(position, until)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Set a manual override and immediately command the physical covers."""
        await self._apply_manual(float(kwargs.get("position", 0)))

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover fully and set a manual override."""
        await self._apply_manual(100.0)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover fully and set a manual override."""
        await self._apply_manual(0.0)
