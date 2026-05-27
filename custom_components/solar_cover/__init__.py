"""Solar Cover integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, ENTRY_TYPE_INTEGRATION, ENTRY_TYPE_ZONE

PLATFORMS_ZONE = ["cover"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    entry_type = entry.data.get("entry_type", ENTRY_TYPE_ZONE)
    if entry_type == ENTRY_TYPE_INTEGRATION:
        hass.data[DOMAIN]["integration"] = entry.data
        return True
    # Zone entry - coordinator setup added in Task 5
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    entry_type = entry.data.get("entry_type", ENTRY_TYPE_ZONE)
    if entry_type == ENTRY_TYPE_INTEGRATION:
        hass.data[DOMAIN].pop("integration", None)
        return True
    return bool(await hass.config_entries.async_unload_platforms(entry, PLATFORMS_ZONE))
