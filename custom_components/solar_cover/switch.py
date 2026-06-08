"""Switch entity to enable/disable Solar Cover automation for a zone."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .coordinator import (
    SolarCoverConfigEntry,
    SolarCoverCoordinator,
    zone_device_info,
)

# Toggles a coordinator flag in memory; no device I/O to serialise.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SolarCoverConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the automation enable/disable switch for a zone."""
    async_add_entities([SolarCoverSwitch(entry.runtime_data, entry)])


class SolarCoverSwitch(SwitchEntity, RestoreEntity):
    """Switch that pauses Solar Cover automation for a zone.

    When off, the coordinator keeps computing solar intent but stops sending
    position commands to cover entities. Covers stay wherever they are.
    State survives HA restarts via RestoreEntity.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "automation_enabled"
    _attr_icon = "mdi:sun-clock"
    _attr_should_poll = False

    def __init__(self, coordinator: SolarCoverCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_automation_enabled"
        self._attr_device_info = zone_device_info(entry)

    async def async_added_to_hass(self) -> None:
        """Restore enabled state from last known state on HA startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            # Restore silently -- coordinator handles first refresh separately
            self._coordinator._enabled = last_state.state != "off"

    @property
    def is_on(self) -> bool:
        return self._coordinator.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._coordinator.set_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._coordinator.set_enabled(False)
        self.async_write_ha_state()
