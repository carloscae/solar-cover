"""Button entity to reset Solar Cover timers for a zone."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import (
    SolarCoverConfigEntry,
    SolarCoverCoordinator,
    zone_device_info,
)

# Action goes through the coordinator (in-memory timer reset); nothing to serialise.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SolarCoverConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the reset-timers button for a zone."""
    async_add_entities([SolarCoverResetTimersButton(entry.runtime_data, entry)])


class SolarCoverResetTimersButton(ButtonEntity):
    """Clears the stability hold and manual override in one press.

    After a press the current live solar evaluation takes effect on the next
    refresh -- no waiting out a stability delay or a manual hold.
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
        """Reset both timers."""
        self._coordinator.reset_timers()
