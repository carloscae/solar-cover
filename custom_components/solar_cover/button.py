"""Button entity to reset Solar Cover timers for a zone."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import SolarCoverCoordinator, zone_device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the reset-timers button for a zone."""
    coordinator: SolarCoverCoordinator = hass.data[DOMAIN]["coordinators"][
        entry.entry_id
    ]
    async_add_entities([SolarCoverResetTimersButton(coordinator, entry)])


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
