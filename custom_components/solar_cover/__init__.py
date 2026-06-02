"""Solar Cover integration."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import (
    DOMAIN,
    ENTRY_TYPE_INTEGRATION,
    ENTRY_TYPE_ZONE,
)
from .coordinator import SolarCoverCoordinator
from .solar import SolarEngine

PLATFORMS_ZONE = ["button", "sensor", "switch"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {"coordinators": {}})

    entry_type = entry.data.get("entry_type", ENTRY_TYPE_ZONE)

    if entry_type == ENTRY_TYPE_INTEGRATION:
        if entry.title != "Global Settings":
            hass.config_entries.async_update_entry(entry, title="Global Settings")
        integration_data = {**entry.data, **entry.options}
        hass.data[DOMAIN]["integration"] = integration_data
        entry.async_on_unload(
            entry.add_update_listener(_async_update_integration_listener)
        )

        async def _handle_set_position(call: ServiceCall) -> None:
            entry_id: str = call.data["entry_id"]
            position: float = float(call.data["position"])
            coordinator = (
                hass.data.get(DOMAIN, {}).get("coordinators", {}).get(entry_id)
            )
            if coordinator is None:
                return
            until = datetime.now(tz=UTC) + timedelta(
                minutes=coordinator._get_override_duration()
            )
            await coordinator.async_apply_manual_position(position, until)

        if not hass.services.has_service(DOMAIN, "set_position"):
            hass.services.async_register(
                DOMAIN,
                "set_position",
                _handle_set_position,
                schema=vol.Schema(
                    {
                        vol.Required("entry_id"): cv.string,
                        vol.Required("position"): vol.All(
                            vol.Coerce(float), vol.Range(min=0, max=100)
                        ),
                    }
                ),
            )
        return True

    # Zone entry
    integration_data = hass.data[DOMAIN].get("integration", {})
    zone_data = {**entry.data, **entry.options}
    zone_name = zone_data.get("name", "Cover Zone")
    expected_title = f"Zone: {zone_name}"
    if entry.title != expected_title:
        hass.config_entries.async_update_entry(entry, title=expected_title)
    solar = SolarEngine(
        lat=hass.config.latitude,
        lon=hass.config.longitude,
        elev=hass.config.elevation,
    )

    coordinator = SolarCoverCoordinator(
        hass=hass,
        zone_data=zone_data,
        integration_data=integration_data,
        solar_engine=solar,
        entry_id=entry.entry_id,
    )
    await coordinator.async_restore_state()
    await coordinator.async_config_entry_first_refresh()
    coordinator.async_setup_cover_listeners()
    entry.async_on_unload(coordinator.cancel_cover_listeners)
    entry.async_on_unload(coordinator.cancel_sensor_listeners)

    hass.data[DOMAIN]["coordinators"][entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS_ZONE)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
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


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_update_integration_listener(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Reload integration entry and all zone entries when global options change.

    Zone coordinators hold a snapshot of integration_data at construction time.
    Without this cascade, changing the weather entity (or cloud/radiation sensors)
    in global settings would be silently ignored by running zone coordinators.
    """
    await hass.config_entries.async_reload(entry.entry_id)
    for zone_entry in hass.config_entries.async_entries(DOMAIN):
        if zone_entry.data.get("entry_type", ENTRY_TYPE_ZONE) == ENTRY_TYPE_ZONE:
            await hass.config_entries.async_reload(zone_entry.entry_id)
