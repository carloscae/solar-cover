"""Button entities: zone reset-all + per-cover override reset."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import (
    SolarCoverConfigEntry,
    SolarCoverCoordinator,
    cover_label,
    cover_slug,
    zone_device_info,
)

# Actions go through the coordinator (in-memory reset); nothing to serialise.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SolarCoverConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the zone reset-all button plus one reset button per cover."""
    coordinator = entry.runtime_data
    entities: list[ButtonEntity] = [SolarCoverResetTimersButton(coordinator, entry)]
    for entity_id in coordinator.cover_entities:
        entities.append(SolarCoverResetCoverButton(coordinator, entry, entity_id))
    async_add_entities(entities)


class SolarCoverResetTimersButton(ButtonEntity):
    """Reset all: clears the zone stability hold and every per-cover override.

    After a press the live solar evaluation takes effect on the next refresh --
    no waiting out a stability delay or any manual hold.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "reset_timers"
    _attr_icon = "mdi:timer-off"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: SolarCoverCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_reset_timers"
        self._attr_device_info = zone_device_info(entry)

    async def async_press(self) -> None:
        """Reset everything and wait for the refresh to land."""
        self._coordinator.reset_timers()
        await self._coordinator.async_request_refresh()


class SolarCoverResetCoverButton(ButtonEntity):
    """Clears only its own cover's manual override, leaving siblings and the
    zone stability hold untouched."""

    _attr_has_entity_name = True
    _attr_translation_key = "reset_override"
    _attr_icon = "mdi:timer-off"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: SolarCoverCoordinator,
        entry: ConfigEntry,
        entity_id: str,
    ) -> None:
        self._coordinator = coordinator
        self._entity_id = entity_id
        slug = cover_slug(entity_id)
        self._attr_unique_id = f"{entry.entry_id}_{slug}_reset_override"
        self._attr_device_info = zone_device_info(entry)
        self._attr_translation_placeholders = {"cover": cover_label(entity_id)}

    async def async_press(self) -> None:
        """Clear this cover's override and wait for the refresh to land."""
        self._coordinator.reset_cover_override(self._entity_id)
        await self._coordinator.async_request_refresh()
