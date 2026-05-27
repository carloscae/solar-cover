"""Solar Cover integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    ENTRY_TYPE_INTEGRATION,
    ENTRY_TYPE_ZONE,
)
from .coordinator import SolarCoverCoordinator
from .solar import SolarEngine

PLATFORMS_ZONE = ["cover"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {"coordinators": {}})

    entry_type = entry.data.get("entry_type", ENTRY_TYPE_ZONE)

    if entry_type == ENTRY_TYPE_INTEGRATION:
        hass.data[DOMAIN]["integration"] = dict(entry.data)
        return True

    # Zone entry
    integration_data = hass.data[DOMAIN].get("integration", {})
    solar = SolarEngine(
        lat=hass.config.latitude,
        lon=hass.config.longitude,
        elev=hass.config.elevation,
    )

    coordinator = SolarCoverCoordinator(
        hass=hass,
        zone_data=dict(entry.data),
        integration_data=integration_data,
        solar_engine=solar,
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN]["coordinators"][entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS_ZONE)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    entry_type = entry.data.get("entry_type", ENTRY_TYPE_ZONE)

    if entry_type == ENTRY_TYPE_INTEGRATION:
        hass.data[DOMAIN].pop("integration", None)
        return True

    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS_ZONE)
    if unloaded:
        hass.data[DOMAIN]["coordinators"].pop(entry.entry_id, None)
    return unloaded
